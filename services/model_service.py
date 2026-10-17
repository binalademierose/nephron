"""
model_service.py - loads the saved model, checks it very strictly, and runs it. It NEVER trains anything.

WHY SO STRICT
  The saved pipeline fills gaps by itself: a missing answer becomes the most common value, and a category it has never
  seen is quietly treated as the first one. A screening tool must not guess for a person. So before the model may
  be used, this file proves that:
    1. the model file is exactly the one that was recorded (SHA-256), saved with the library versions installed here;
    2. its inputs are exactly the questions in ml/feature_catalog.json (names, order, and the answers each accepts);
    3. its classes and threshold are what the metadata says, and the model really runs;
    4. every input can be traced to a share of the model's feature importance.
  If ANY check fails the service is "not ready": the app keeps running, screening says it is unavailable, the reason is
  written to the log, and no result is ever made up.

THE FILES (in ml/model/)
  model_metadata.json  - what the model is: see ml/README.md for the fields and for the notebook cell that writes it
  <artifact_file>      - the fitted pipeline saved with joblib (a pipeline, or a dict with a "pipeline" key)

EXPLAINING ONE RESULT
  explain() shows how much each question pushed ONE person's estimate up or down, compared with an average person in the data
  the model learned from (XGBoost's built-in TreeSHAP contributions, no extra library). It is only offered when those contributions
  add up to exactly the probability the model gave; otherwise no explanation is shown, never a wrong one.
  factors() is different: it is the model-wide importance, used only by verify_model.py to check the model.

RISK LANGUAGE
  Predicted Risk Probability = the model's probability of the HIGH-RISK class.
  Risk Classification        = High Preliminary Risk when that probability >= threshold, otherwise Low Preliminary Risk.
  The threshold is the one validated for THIS model and is read from its metadata, never written in the program.
"""
import hashlib
import importlib.metadata
import json
import math
import os
import re
from collections import namedtuple

from services import screening_contract as contract

METADATA_FILE = "model_metadata.json"
REQUIRED_METADATA_KEYS = ("schema_version", "artifact_file", "artifact_sha256", "model_name", "model_version", "high_risk_class",
                          "threshold", "threshold_method", "stage", "features", "library_versions")
SCHEMA_VERSION = 1
ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9._-]+\.(joblib|pkl|pickle)$")
STRICT_LIBRARIES = {"scikit-learn": "scikit-learn", "xgboost": "xgboost"}      # a different version can break the file
SOFT_LIBRARIES = {"pandas": "pandas", "numpy": "numpy"}                           # a different version is only a warning

Check = namedtuple("Check", "name ok detail fatal")


class ModelUnavailableError(RuntimeError):
    """The model is not ready, so no result can be produced."""


class ExplanationUnavailable(RuntimeError):
    """This result cannot be explained (the model is not XGBoost, or the contributions do not add up)."""


class ModelInputError(ValueError):
    """The answers offered to the model are incomplete or outside what it accepts."""


def _minor(version):
    match = re.match(r"(\d+)\.(\d+)", version or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


# xgboost ships as two interchangeable wheels: the full "xgboost" and the smaller CPU-only "xgboost-cpu" (used on
# hosts with a size limit, such as serverless). Both import as `xgboost` and share the same version line, so either
# one satisfies the model's recorded xgboost version. The installed-version check must therefore look under BOTH
# distribution names, or a perfectly good xgboost-cpu install would be reported as "not installed".
_DISTRIBUTION_ALIASES = {"xgboost": ("xgboost", "xgboost-cpu")}


def _installed_version(dist):
    """The installed version of a distribution (trying known alternate names), or None if none is installed."""
    import importlib.metadata as md
    for name in _DISTRIBUTION_ALIASES.get(dist, (dist,)):
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            continue
    return None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _plain(value):
    """A category as plain Python (numpy numbers become int/float; whole floats become int) so it can be compared."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _diff(expected, found):
    missing, extra = sorted(map(str, expected - found)), sorted(map(str, found - expected))
    parts = []
    if missing:
        parts.append("the model does not know: " + ", ".join(missing))
    if extra:
        parts.append("the model also expects: " + ", ".join(extra))
    return "; ".join(parts)


def _install_hint_for(meta):
    versions = meta.get("library_versions", {}) if isinstance(meta, dict) else {}
    wanted = [f"{name}=={versions[name]}" for name in ("scikit-learn", "xgboost", "pandas", "numpy") if name in versions]
    return ("Install the versions the model was saved with:  pip install " + " ".join(wanted + ["joblib"])) if wanted else \
           "Install the machine-learning libraries listed in requirements.txt."


class ModelService:
    def __init__(self, model_dir, catalog):
        self.model_dir = model_dir
        self.catalog = catalog
        self.checks = []
        self.ready = False
        self.reason = "The model has not been loaded."
        self.metadata = {}
        self._pipeline = None
        self._estimator = None
        self._transform = None
        self._calibrator = None
        self._high_index = None
        self._importance = {}
        self.can_explain = False

    # ------------------------------------------------------------------ loading and verification
    def load(self):
        """Run every check. Afterwards `ready` says whether screening may be used, `checks` shows the whole report."""
        self.checks, self.ready, self._pipeline = [], False, None
        try:
            self._verify()
        except _Stop:
            pass
        except Exception as error:                                        # a bug or a strange file must never crash the app
            self.checks.append(Check("Unexpected problem while checking the model", False, f"{type(error).__name__}: {error}", True))
        failed = next((c for c in self.checks if not c.ok and c.fatal), None)
        self.ready = failed is None and self._pipeline is not None
        self.reason = None if self.ready else f"{failed.name}: {failed.detail}" if failed else "The model could not be checked."
        return self.ready

    def _add(self, name, ok, detail="", fatal=True):
        self.checks.append(Check(name, ok, detail, fatal))
        if not ok and fatal:
            raise _Stop()

    def _verify(self):
        meta_path = os.path.join(self.model_dir, METADATA_FILE)
        if not os.path.exists(meta_path):
            self._add("Model description found", False, f"{METADATA_FILE} is missing from {self.model_dir}. No model has been installed yet (see ml/README.md).")
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
            assert isinstance(meta, dict)
        except (OSError, ValueError, AssertionError) as error:
            self._add("Model description readable", False, f"{METADATA_FILE} is not valid JSON ({error}).")
        self._add("Model description found and readable", True, METADATA_FILE)

        problems = self._metadata_problems(meta)
        self._add("Model description complete and sensible", not problems, "; ".join(problems) or "all fields present")
        self.metadata = meta
        features = meta["features"]

        artifact_path = os.path.join(self.model_dir, meta["artifact_file"])
        self._add("Model file found", os.path.isfile(artifact_path), f"{meta['artifact_file']} is missing from {self.model_dir}.")
        actual = _sha256(artifact_path)
        self._add("Model file is exactly the one recorded (SHA-256)", actual == meta["artifact_sha256"].lower(),
                  "the file has changed since the metadata was written, or it is a different file.")

        self._check_libraries(meta)
        try:
            import joblib
            import numpy  # noqa: F401
            import pandas  # noqa: F401
        except ImportError as error:
            self._add("Machine-learning libraries installed", False, f"{error}. {self._install_hint(meta)}")
        try:
            obj = joblib.load(artifact_path)
        except Exception as error:
            self._add("Model file can be loaded", False, f"{type(error).__name__}: {error}. {self._install_hint(meta)}")
        pipeline = obj["pipeline"] if isinstance(obj, dict) and "pipeline" in obj else obj
        self._add("Model file holds a pipeline that gives probabilities", hasattr(pipeline, "predict_proba"),
                  "expected a fitted pipeline (or a dict with a 'pipeline' key) that has predict_proba.")
        self._transform, self._estimator, self._calibrator = _decompose(pipeline)
        self._check_classes(meta, pipeline)
        self._check_features(meta, pipeline)
        self._check_answers_match(pipeline)
        self._pipeline = pipeline
        self._check_it_runs(meta)
        self._check_importance(self._transform, self._estimator, features)
        self._check_explanations()

    def _metadata_problems(self, meta):
        problems = []
        problems += [f"'{key}' is missing" for key in REQUIRED_METADATA_KEYS if key not in meta]
        if problems:
            return problems
        if meta["schema_version"] != SCHEMA_VERSION:
            problems.append(f"schema_version must be {SCHEMA_VERSION}")
        if not isinstance(meta["artifact_file"], str) or not ARTIFACT_NAME.match(meta["artifact_file"]):
            problems.append("artifact_file must be a plain file name ending in .joblib or .pkl (no folders)")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(meta["artifact_sha256"])):
            problems.append("artifact_sha256 must be 64 hexadecimal characters")
        for key in ("model_name", "model_version", "threshold_method"):
            if not isinstance(meta[key], str) or not meta[key].strip():
                problems.append(f"{key} must be text")
        threshold = meta["threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold < 1:
            problems.append("threshold must be a number above 0 and below 1 (a probability of the high-risk class)")
        if meta["stage"] != "preliminary":
            problems.append("stage must be 'preliminary' (this program only runs the preliminary screening)")
        features = meta["features"]
        if not isinstance(features, list) or not features or not all(isinstance(f, str) for f in features) or len(set(features)) != len(features):
            problems.append("features must be a list of different names")
        if not isinstance(meta["library_versions"], dict):
            problems.append("library_versions must be an object")
        return problems

    def _install_hint(self, meta):
        return _install_hint_for(meta)

    def _check_libraries(self, meta):
        versions = meta["library_versions"]
        for key, dist in STRICT_LIBRARIES.items():
            if key == "scikit-learn" and key not in versions:
                self._add("Library versions recorded", False, "library_versions must include scikit-learn.")
            if key not in versions:
                continue
            installed = _installed_version(dist)
            if installed is None:
                self._add(f"{key} installed", False, f"{key} {versions[key]} is needed but not installed. {self._install_hint(meta)}")
                continue
            same = _minor(installed) == _minor(versions[key]) and _minor(installed) is not None
            self._add(f"{key} version matches the model file", same,
                      f"the model was saved with {versions[key]} but {installed} is installed. {self._install_hint(meta)}")
        for key, dist in SOFT_LIBRARIES.items():
            if key in versions:
                try:
                    installed = importlib.metadata.version(dist)
                except importlib.metadata.PackageNotFoundError:
                    installed = None
                self._add(f"{key} version", installed is not None and _minor(installed) == _minor(versions[key]),
                          f"saved with {versions[key]}, installed {installed}. This is only a warning.", fatal=False)

    def _check_classes(self, meta, pipeline):
        # Read from the OUTER object: predict() indexes pipeline.predict_proba()'s own columns, calibrated or not.
        classes = getattr(pipeline, "classes_", None)
        self._add("Model reports its two classes", classes is not None and len(classes) == 2, "the model must have exactly two classes.")
        labels = [_plain(c) for c in classes]
        high = _plain(meta["high_risk_class"])
        self._add("The high-risk class is one of the model's classes", high in labels,
                  f"metadata says the high-risk class is {high!r} but the model's classes are {labels}.")
        self._high_index = labels.index(high)          # found by LABEL, never assumed to be column 1

    def _check_features(self, meta, pipeline):
        features, wanted = meta["features"], contract.feature_names(self.catalog)
        self._add("Model inputs are exactly the screening questions", set(features) == set(wanted),
                  _diff(set(wanted), set(features)) or "")
        names_in = getattr(pipeline, "feature_names_in_", None)
        self._add("Model was trained with column names", names_in is not None,
                  "the pipeline has no feature_names_in_, so the order of its inputs cannot be proven. Train it on a pandas DataFrame.")
        self._add("Input order in the metadata is the model's own order", [str(n) for n in names_in] == features,
                  f"the model expects {list(names_in)[:6]}... but the metadata lists {features[:6]}...")

    def _check_answers_match(self, pipeline):
        """Every answer the form can send must be one the model was trained on (the pipeline would otherwise guess)."""
        known = _categories_by_input(pipeline)
        self._add("The model's answer categories can be read", known is not None,
                  "the pipeline's encoders could not be inspected, so the accepted answers cannot be proven.")
        for question in self.catalog["questions"]:
            name, kind = question["name"], question["kind"]
            allowed = contract.model_values(question)
            if name in known:
                self._add(f"{name}: the model treats it as a category", allowed is not None,
                          f"the model treats {name} as categories but the screening asks it as a number.")
                self._add(f"{name}: answers match the model's categories", known[name] == allowed,
                          _diff(allowed, known[name]))
            elif kind == "choice":
                self._add(f"{name}: answers can be checked", False,
                          f"the model has no category list for {name}, so the answers the form offers cannot be proven.")

    def _check_it_runs(self, meta):
        try:
            self.metadata = meta
            result = self.predict(contract.reference_row(self.catalog), _checking=True)
            ok, detail = 0 <= result["probability"] <= 1, ""
        except Exception as error:
            ok, detail = False, f"{type(error).__name__}: {error}"
        self._add("The model runs and returns a probability", ok, detail)

    def _check_importance(self, transform, estimator, features):
        try:
            self._importance = _importance_by_input(transform, estimator, features)
            ok, detail = sum(self._importance.values()) > 0, "every input maps to the model's feature importance"
        except Exception as error:
            ok, detail = False, f"{type(error).__name__}: {error}"
        self._add("Every input can be traced to the model's feature importance", ok, detail)

    def _check_explanations(self):
        """Not required for screening, so a failure is only a warning: the result page then says no explanation is available."""
        try:
            self.explain(contract.reference_row(self.catalog), _checking=True)
            ok, detail = True, "the contributions add up to the probability the model gives"
        except Exception as error:
            ok, detail = False, f"a single result cannot be explained ({type(error).__name__}: {error}). Screening still works; the result page will say no explanation is available."
        self.can_explain = ok
        self._add("Each result can be explained (contributions add up to the model's probability)", ok, detail, fatal=False)

    # ------------------------------------------------------------------ using the model
    @property
    def version(self):
        return self.metadata.get("model_version")

    @property
    def threshold(self):
        return float(self.metadata["threshold"])

    def predict(self, values, _checking=False):
        """
        The model's answer for ONE person: {"probability", "classification", "threshold", "model_version", "assessment_type"}.
        Raises ModelInputError if the answers are incomplete or outside what the model accepts, and ModelUnavailableError
        if the model is not ready. It does not repair, fill in or clamp anything.
        """
        if not self.ready and not _checking:
            raise ModelUnavailableError(self.reason)
        features = self.metadata["features"]
        values = contract.to_model_values(self.catalog, values)
        self._check_row(values, features)
        frame = self._frame(values, features)
        probabilities = self._pipeline.predict_proba(frame)
        probability = float(probabilities[0][self._high_index])
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ModelUnavailableError("the model returned a value that is not a probability")
        return {
            "probability": probability,
            "classification": "high" if probability >= self.threshold else "low",
            "threshold": self.threshold,
            "model_version": self.version,
            "assessment_type": self.metadata["stage"],
        }

    @staticmethod
    def _frame(values, features):
        """One person as a one-row table, in the model's own column order. Words are kept as text (object)."""
        import pandas
        frame = pandas.DataFrame({name: [values[name]] for name in features})
        for name in features:
            if isinstance(values[name], str):
                frame[name] = frame[name].astype(object)
        return frame

    def _check_row(self, values, features):
        if set(values) != set(features):
            raise ModelInputError("The answers do not match the model's inputs: " + (_diff(set(features), set(values)) or "different names"))
        for name in features:
            question, value = contract.question_for(self.catalog, name), values[name]
            kind, allowed = question["kind"], contract.model_values(question)
            if value is None or (isinstance(value, float) and not math.isfinite(value)):
                raise ModelInputError(f"{name} is empty")
            if allowed is not None:
                if isinstance(value, bool) or value not in allowed:
                    raise ModelInputError(f"{name}: '{value}' is not an answer the model knows")
            elif kind == "derived":
                if value not in (0, 1) or isinstance(value, bool):
                    raise ModelInputError(f"{name} must be 0 or 1")
            else:
                low, high = contract.valid_range(question)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                    raise ModelInputError(f"{name}: {value!r} is outside the realistic range ({low:g} to {high:g})")

    def explain(self, values, _checking=False):
        """
        How much each question moved THIS person's estimate, compared with an average person in the model's training data:
          {"probability": the model's probability for this person,
           "effects": [{"name", "label", "effect"}, ...]}  strongest first; effect > 0 raised the estimate, effect < 0 lowered it
        (effect is in log-odds, so only its sign and its size relative to the others mean anything to a reader).
        Raises ExplanationUnavailable if it cannot be done, or if the contributions do not add up to the probability the model gives.

        Works whether the saved pipeline is a bare XGBoost pipeline or a CalibratedClassifierCV(isotonic, ensemble=False)
        wrapping one (see _decompose): XGBoost's TreeSHAP contributions are always for its OWN, uncalibrated probability.
        When the model is calibrated, that raw probability is passed through the SAME fitted isotonic curve the
        pipeline itself uses before the contributions are allowed to explain anything, so the honesty check below
        ("do the contributions add up to the probability the model gives?") is against the real, calibrated number
        shown to the person, never the pre-calibration one.
        """
        if not self.ready and not _checking:
            raise ModelUnavailableError(self.reason)
        transform, estimator, calibrator = self._transform, self._estimator, self._calibrator
        if not hasattr(estimator, "get_booster"):
            raise ExplanationUnavailable("only an XGBoost model can explain a single result")
        if transform is None:
            raise ExplanationUnavailable("the pipeline has no preprocessing step to map back to the questions")
        raw_classes = getattr(estimator, "classes_", None)
        if calibrator is not None:
            outer_classes = [_plain(c) for c in getattr(self._pipeline, "classes_", [])]
            if raw_classes is None or [_plain(c) for c in raw_classes] != outer_classes:
                raise ExplanationUnavailable("the calibrated model's own classes do not line up with its wrapper's classes")
        features = self.metadata["features"]
        values = contract.to_model_values(self.catalog, values)
        self._check_row(values, features)
        frame = self._frame(values, features)
        try:
            import numpy
            import xgboost
            encoded = transform.transform(frame)
            if hasattr(encoded, "toarray"):
                encoded = encoded.toarray()
            encoded = numpy.asarray(encoded, dtype=float)
            raw = numpy.asarray(estimator.get_booster().predict(xgboost.DMatrix(encoded), pred_contribs=True), dtype=float)
        except ImportError as error:
            raise ExplanationUnavailable(f"xgboost could not be imported ({error})") from error
        if raw.shape != (1, encoded.shape[1] + 1):
            raise ExplanationUnavailable(f"the contributions have an unexpected shape {raw.shape}")

        # XGBoost's contributions are for its OWN positive class, estimator.classes_[1]. When the model is calibrated,
        # estimator.classes_[1] is the same class as self._pipeline.classes_[1] (just verified above), so this is also
        # the class the isotonic curve was fitted to move towards. Turn everything towards the HIGH-risk class.
        sign = 1.0 if self._high_index == 1 else -1.0
        margin = max(min(float(raw[0].sum()), 30.0), -30.0)                 # contributions + bias = the log-odds of estimator.classes_[1]
        positive = 1.0 / (1.0 + math.exp(-margin))                          # estimator's OWN probability of its classes_[1]
        if calibrator is not None:
            try:
                positive = float(calibrator.predict(numpy.array([positive]))[0])    # the same curve predict_proba() itself applies
            except Exception as error:
                raise ExplanationUnavailable(f"could not apply the model's calibration curve ({type(error).__name__}: {error})") from error
        from_contributions = positive if self._high_index == 1 else 1.0 - positive
        given = float(self._pipeline.predict_proba(frame)[0][self._high_index])
        if abs(from_contributions - given) > 1e-4:
            raise ExplanationUnavailable(f"the contributions add up to {from_contributions:.6f} but the model gives {given:.6f}")

        totals = dict.fromkeys(features, 0.0)
        for owner, value in zip(_owners(transform, features), raw[0][:-1]):
            totals[owner] += sign * float(value)                          # every encoded column is added to ITS question
        effects = [{"name": name, "label": contract.question_for(self.catalog, name)["short"], "effect": value}
                   for name, value in totals.items()]
        effects.sort(key=lambda item: (-abs(item["effect"]), item["name"]))
        return {"probability": given, "effects": effects}

    def high_risk_probabilities(self, frame):
        """The high-risk probability for every row of a DataFrame that has the model's columns. Used by verify_model.py."""
        if not self.ready:
            raise ModelUnavailableError(self.reason)
        return self._pipeline.predict_proba(frame[self.metadata["features"]])[:, self._high_index]

    def factors(self, limit=5):
        """
        The inputs that carry the most weight in the model overall, strongest first:
        [{"name", "label", "share" (0-100, strongest = 100), "percent" (of the total)}].
        These describe the MODEL, not the reason for one person's result.
        """
        if not self.ready:
            return []
        total, top = sum(self._importance.values()), max(self._importance.values())
        ranked = sorted(self._importance.items(), key=lambda item: (-item[1], item[0]))[:limit]
        return [{"name": name, "label": contract.question_for(self.catalog, name)["short"],
                 "share": round(100 * value / top), "percent": round(100 * value / total, 1)} for name, value in ranked]


class _Stop(Exception):
    """Stops checking at the first fatal problem."""


def _categories_by_input(pipeline):
    """{input name: set of accepted categories} for every input the pipeline encodes as categories; None if unreadable."""
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline

    transform, _, _ = _decompose(pipeline)
    if transform is not None:
        pipeline = transform

    def encoders(transformer):
        if hasattr(transformer, "categories_"):
            yield transformer
        elif isinstance(transformer, Pipeline):
            for _, step in transformer.steps:
                yield from encoders(step)

    steps = pipeline.steps if isinstance(pipeline, Pipeline) else []
    table = next((s for _, s in steps if isinstance(s, ColumnTransformer)), pipeline if isinstance(pipeline, ColumnTransformer) else None)
    if table is None or not hasattr(table, "transformers_"):
        return None
    found = {}
    for _, transformer, columns in table.transformers_:
        if isinstance(transformer, str):
            continue
        for encoder in encoders(transformer):
            names = list(columns)
            if not all(isinstance(n, str) for n in names):
                return None
            for name, categories in zip(names, encoder.categories_):
                found[name] = {_plain(c) for c in categories}
    return found


def _decompose(pipeline):
    """
    Breaks the object saved by the notebook down into (transform, estimator, calibrator):
      transform    the fitted preprocessing step(s) alone (has .transform()/.get_feature_names_out()), or None
                   if the saved object is not a multi-step Pipeline (nothing to slice off)
      estimator    the actual fitted classifier (feature_importances_, classes_, and - for XGBoost - get_booster())
      calibrator   the fitted isotonic curve that turns estimator's own predict_proba into the saved object's
                   predict_proba, or None when the saved object is not a calibrated pipeline

    Two shapes are understood:
      - a plain Pipeline[... -> classifier]  (calibrator is always None)
      - CalibratedClassifierCV(method="isotonic", ensemble=False) wrapping a Pipeline[... -> classifier]
        (ensemble=False is required: it is the only case with exactly one inner estimator and one calibration
        curve, so there is exactly one honest way to explain a single result. ensemble=True, or any method other
        than isotonic, is treated as "not decomposable": estimator falls back to the object itself, which has no
        get_booster(), so explain() correctly refuses with 'only an XGBoost model can explain a single result'.)
    """
    from sklearn.calibration import CalibratedClassifierCV

    calibrator = None
    inner = pipeline
    if isinstance(pipeline, CalibratedClassifierCV):
        fitted = getattr(pipeline, "calibrated_classifiers_", None)
        if fitted and len(fitted) == 1 and pipeline.method == "isotonic":
            calibrator = fitted[0].calibrators[0]
            inner = fitted[0].estimator
        else:
            return None, pipeline, None

    steps = getattr(inner, "steps", None)
    if steps and len(steps) > 1:
        return inner[:-1], inner.steps[-1][1], calibrator
    return None, inner, calibrator


def _owners(transform, features):
    """
    For every encoded column of the preprocessing step, the question it belongs to (Country_India -> Country;
    a SimpleImputer(add_indicator=True) column, missingindicator_Sodium -> Sodium, is owned the same way).
    """
    names = list(transform.get_feature_names_out()) if transform is not None else list(features)
    owners = []
    for encoded in names:
        base = encoded.split("__", 1)[1] if "__" in encoded else encoded
        if base.startswith("missingindicator_"):
            base = base[len("missingindicator_"):]
        matches = [f for f in features if base == f or base.startswith(f + "_")]
        if not matches:
            raise ValueError(f"encoded column '{encoded}' does not belong to any input")
        owners.append(max(matches, key=len))                    # 'Diabetes_Medication_x' belongs to Diabetes_Medication, not Diabetes
    return owners


def _importance_by_input(transform, estimator, features):
    """Add up the importance of every encoded column that belongs to one input (Country_India, Country_UK -> Country)."""
    importances = getattr(estimator, "feature_importances_", None)
    if importances is None:
        raise ValueError("the final model has no feature_importances_")
    owners = _owners(transform, features)
    if len(owners) != len(importances):
        raise ValueError(f"the model has {len(importances)} importances but {len(owners)} encoded columns")
    totals = dict.fromkeys(features, 0.0)
    for owner, importance in zip(owners, importances):
        totals[owner] += float(importance)
    unused = [f for f in features if f not in set(owners)]
    if unused:
        raise ValueError("the model does not use: " + ", ".join(unused))
    return totals
