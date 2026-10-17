"""
model_service_stage2.py - loads, checks very strictly, and runs the Stage 2 (Enhanced Screening) model. Mirrors
services/model_service.py's rigor and reuses its pipeline-introspection helpers (_decompose, _owners,
_importance_by_input all work off a plain pipeline and a plain feature list, with no Stage 1 catalog dependency),
but Stage 2's inputs are shaped differently, so its own checks and prediction logic live here:

  - 27 of its 48 inputs are the SAME questions Stage 1 already asked. Enhanced Screening is an EXTENSION of a
    person's most recent Preliminary assessment: those 27 answers are pulled from that assessment's saved inputs,
    never re-asked, and are trusted as already valid (screening_contract already validated them once).
  - 20 are laboratory values (ml/lab_catalog.json). Only Serum_Creatinine is required; every other lab value may be
    missing (a real lab report rarely has all of them), and the saved pipeline was trained to tolerate that (its own
    SimpleImputer fills a gap the same way it did during training - see ml/model_stage2/README.md). A value that IS
    given is still range-checked; nothing is silently accepted, clamped, or invented.
  - 1 (eGFR) is always DERIVED (services/egfr.py, the CKD-EPI 2021 equation), never asked for and never missing
    when Serum_Creatinine is present.

Everything else - the SHA-256 and library-version checks, the calibration-aware explain(), the honest refusal to
guess - works exactly like Stage 1's ModelService.
"""
import json
import math
import os

from services import lab_contract
from services import screening_contract as contract
from services.egfr import estimate_gfr
from services.model_service import (Check, ExplanationUnavailable, ModelInputError, ModelUnavailableError,
                                    REQUIRED_METADATA_KEYS, SCHEMA_VERSION, _Stop, _categories_by_input, _decompose,
                                    _diff, _importance_by_input, _install_hint_for, _owners, _plain, _sha256)

STAGE1_LIKE_FIELDS = ("Country", "Sex", "Ethnicity", "Age", "BMI", "Smoking_Status", "Alcohol_Consumption",
                     "Physical_Activity_Level", "Exercise_Hours_Per_Week", "Water_Intake_L", "Fast_Food_Frequency_Per_Week",
                     "Sleep_Duration_Hours", "Diabetes", "Cardiovascular_Disease", "Hyperlipidemia", "Recurrent_UTI",
                     "Family_History_CKD", "Hypertension", "Heart_Failure", "Kidney_Stones", "Autoimmune_Disease",
                     "ACE_Inhibitor", "Diabetes_Medication", "Diuretic", "ARB", "Statin", "NSAID_Usage")
BINARY_FIELDS = tuple(name for name in STAGE1_LIKE_FIELDS if name not in
                     ("Country", "Sex", "Ethnicity", "Age", "BMI", "Smoking_Status", "Alcohol_Consumption",
                      "Physical_Activity_Level", "Exercise_Hours_Per_Week", "Water_Intake_L", "Fast_Food_Frequency_Per_Week",
                      "Sleep_Duration_Hours"))

# Stage 1's Alcohol_Consumption has a third answer, "None" (does not drink), that this model has never seen (its own
# training data recorded only Moderate/Heavy, with a blank kept as its own "Not_Reported" category - see
# ml/model_stage2/README.md). "None" is translated to a genuine missing value here, for this one field only, and the
# model's own trained imputer fills it in exactly the way it was trained to for a blank answer. This is the ONE
# Stage-1-like field allowed to be missing; the other 26 always come from a real, completed Preliminary assessment.
STAGE1_VOCABULARY_GAPS = {"Alcohol_Consumption": {"None": None},
                          "Country": {"Philippines": "Other"}}     # a country the model knows only as Other (see feature_catalog.json)
# Only a field whose translation is "missing" may legitimately be absent (Alcohol "None") - a translated Country is
# still required. Listing every translated field here would quietly let a missing Country through.
STAGE1_MAY_BE_MISSING = {name for name, gaps in STAGE1_VOCABULARY_GAPS.items() if None in gaps.values()}


class Stage2ModelService:
    def __init__(self, model_dir, lab_catalog=None):
        self.model_dir = model_dir
        self.lab_catalog = lab_catalog or lab_contract.load_lab_catalog()
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
        self.checks, self.ready, self._pipeline = [], False, None
        try:
            self._verify()
        except _Stop:
            pass
        except Exception as error:
            self.checks.append(Check("Unexpected problem while checking the Stage 2 model", False, f"{type(error).__name__}: {error}", True))
        failed = next((c for c in self.checks if not c.ok and c.fatal), None)
        self.ready = failed is None and self._pipeline is not None
        self.reason = None if self.ready else f"{failed.name}: {failed.detail}" if failed else "The Stage 2 model could not be checked."
        return self.ready

    def _add(self, name, ok, detail="", fatal=True):
        self.checks.append(Check(name, ok, detail, fatal))
        if not ok and fatal:
            raise _Stop()

    def _verify(self):
        meta_path = os.path.join(self.model_dir, "model_metadata.json")
        if not os.path.exists(meta_path):
            self._add("Model description found", False, f"model_metadata.json is missing from {self.model_dir}. Enhanced Screening has not been installed yet.")
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
            assert isinstance(meta, dict)
        except (OSError, ValueError, AssertionError) as error:
            self._add("Model description readable", False, f"model_metadata.json is not valid JSON ({error}).")
        self._add("Model description found and readable", True, "model_metadata.json")

        problems = self._metadata_problems(meta)
        self._add("Model description complete and sensible", not problems, "; ".join(problems) or "all fields present")
        self.metadata = meta

        artifact_path = os.path.join(self.model_dir, meta["artifact_file"])
        self._add("Model file found", os.path.exists(artifact_path), artifact_path)
        self._add("Model file is exactly the one recorded (SHA-256)", _sha256(artifact_path) == meta["artifact_sha256"],
                  "the file on disk does not match the checksum in model_metadata.json. It was swapped or damaged after export.")
        self._check_libraries(meta)

        import joblib
        try:
            obj = joblib.load(artifact_path)
        except Exception as error:
            self._add("Model file can be loaded", False, f"{type(error).__name__}: {error}. {_install_hint_for(meta)}")
        pipeline = obj["pipeline"] if isinstance(obj, dict) and "pipeline" in obj else obj
        self._add("Model file holds a pipeline that gives probabilities", hasattr(pipeline, "predict_proba"),
                  "expected a fitted pipeline (or a dict with a 'pipeline' key) that has predict_proba.")
        self._transform, self._estimator, self._calibrator = _decompose(pipeline)
        self._check_classes(meta, pipeline)
        self._check_features(meta, pipeline)
        self._check_answers_match(meta, pipeline)
        self._pipeline = pipeline
        self._check_it_runs(meta)
        self._check_importance(self._transform, self._estimator, meta["features"])
        self._check_explanations()

    def _metadata_problems(self, meta):
        problems = [f"'{key}' is missing" for key in REQUIRED_METADATA_KEYS if key not in meta]
        if problems:
            return problems
        if meta["schema_version"] != SCHEMA_VERSION:
            problems.append(f"schema_version must be {SCHEMA_VERSION}")
        if not re_hex64(meta["artifact_sha256"]):
            problems.append("artifact_sha256 must be 64 hexadecimal characters")
        threshold = meta["threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold < 1:
            problems.append("threshold must be a number above 0 and below 1")
        if meta["stage"] != "enhanced":
            problems.append("stage must be 'enhanced' (this service only runs Enhanced Screening)")
        features = meta["features"]
        if not isinstance(features, list) or not features or len(set(features)) != len(features):
            problems.append("features must be a list of different names")
        elif set(features) != set(STAGE1_LIKE_FIELDS) | {f["name"] for f in self.lab_catalog["fields"]} | {"eGFR"}:
            problems.append("features must be exactly the 27 Stage 1 answers, the lab_catalog fields, and eGFR")
        return problems

    def _check_libraries(self, meta):
        from services.model_service import SOFT_LIBRARIES, STRICT_LIBRARIES, _installed_version, _minor
        versions = meta["library_versions"]
        for key, dist in STRICT_LIBRARIES.items():
            if key not in versions:
                continue
            installed = _installed_version(dist)
            if installed is None:
                self._add(f"{key} installed", False, f"{key} {versions[key]} is needed but not installed. {_install_hint_for(meta)}")
                continue
            self._add(f"{key} version matches the model file", _minor(installed) == _minor(versions[key]) and _minor(installed) is not None,
                      f"the model was saved with {versions[key]} but {installed} is installed. {_install_hint_for(meta)}")
        for key, dist in SOFT_LIBRARIES.items():
            if key not in versions:
                continue
            installed = _installed_version(dist)
            self._add(f"{key} version", installed is not None and _minor(installed) == _minor(versions[key]),
                      f"saved with {versions[key]}, installed {installed}. This is only a warning.", fatal=False)

    def _check_classes(self, meta, pipeline):
        classes = getattr(pipeline, "classes_", None)
        self._add("Model reports its two classes", classes is not None and len(classes) == 2, "the model must have exactly two classes.")
        labels = [_plain(c) for c in classes]
        high = _plain(meta["high_risk_class"])
        self._add("The high-risk class is one of the model's classes", high in labels, f"metadata says {high!r} but the model's classes are {labels}.")
        self._high_index = labels.index(high)

    def _check_features(self, meta, pipeline):
        names_in = getattr(pipeline, "feature_names_in_", None)
        self._add("Model was trained with column names", names_in is not None, "the pipeline has no feature_names_in_.")
        self._add("Input order in the metadata is the model's own order", [str(n) for n in names_in] == meta["features"],
                  f"the model expects {list(names_in)[:6]}... but the metadata lists {meta['features'][:6]}...")

    def _check_answers_match(self, meta, pipeline):
        known = _categories_by_input(pipeline)
        self._add("The model's answer categories can be read", known is not None, "the pipeline's encoders could not be inspected.")
        for name, allowed in meta.get("categorical_answers", {}).items():
            if name in (known or {}):
                self._add(f"{name}: the model treats it as a category", True, "")
                self._add(f"{name}: answers match the model's categories", known[name] == set(allowed), _diff(set(allowed), known[name]))

    def _check_it_runs(self, meta):
        try:
            self.metadata = meta
            result = self.predict(meta["reference_row"], _checking=True)
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
        try:
            self.explain(self.metadata["reference_row"], _checking=True)
            ok, detail = True, "the contributions add up to the probability the model gives"
        except Exception as error:
            ok, detail = False, f"a single result cannot be explained ({type(error).__name__}: {error}). Enhanced Screening still works."
        self.can_explain = ok
        self._add("Each result can be explained (contributions add up to the model's probability)", ok, detail, fatal=False)

    # ------------------------------------------------------------------ using the model
    @property
    def version(self):
        return self.metadata.get("model_version")

    @property
    def threshold(self):
        return self.metadata.get("threshold")

    def factors(self, limit=5):
        ranked = sorted(self._importance.items(), key=lambda item: -item[1])
        total = sum(v for _, v in self._importance.items()) or 1
        return [{"name": name, "label": _stage2_label(name), "percent": round(100 * value / total, 1)} for name, value in ranked[:limit]]

    def predict(self, row, _checking=False):
        """
        row: the 27 Stage 1 answers (from the person's latest Preliminary assessment) plus whichever lab values were
        given (validated by lab_contract.validate_lab_values), WITHOUT eGFR - it is computed here, the only place
        that is allowed to. Missing optional lab values are simply absent from `row`; they are never guessed here
        and are left for the saved pipeline's own trained imputer to fill in, exactly as it was trained to.
        """
        if not self.ready and not _checking:
            raise ModelUnavailableError(self.reason)
        features = self.metadata["features"]
        complete = self._check_row(row, features)
        frame = self._frame(complete, features)
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

    def _check_row(self, row, features):
        """
        Returns a complete {feature: value} dict (value is None for a legitimately-missing optional lab or for
        Alcohol_Consumption's "None", see STAGE1_VOCABULARY_GAPS), after checking: every OTHER Stage-1-like field is
        present (they come from a completed Preliminary assessment, so a gap there is a real bug, not a person's
        choice); Serum_Creatinine is present; eGFR is computed from it; every lab field is either absent (fine) or a
        number in its catalog range (checked again here, even though lab_contract already checked it once, so this
        method is trustworthy on its own).
        """
        missing_stage1 = [name for name in STAGE1_LIKE_FIELDS
                          if row.get(name) is None and name not in STAGE1_MAY_BE_MISSING]
        if missing_stage1:
            raise ModelInputError("Missing from the Preliminary assessment this is extending: " + ", ".join(missing_stage1))
        if row.get("Serum_Creatinine") is None:
            raise ModelInputError("Serum_Creatinine is required for Enhanced Screening.")

        complete = {name: row[name] for name in STAGE1_LIKE_FIELDS}
        for name, gaps in STAGE1_VOCABULARY_GAPS.items():
            complete[name] = gaps.get(complete[name], complete[name])
        lab_fields = {f["name"]: f for f in self.lab_catalog["fields"]}
        for name, field in lab_fields.items():
            value = row.get(name)
            if value is None:
                complete[name] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not field["min"] <= value <= field["max"]:
                raise ModelInputError(f"{name}: {value!r} is outside the range the model was built for ({field['min']:g} to {field['max']:g})")
            complete[name] = float(value)
        complete["eGFR"] = estimate_gfr(complete["Serum_Creatinine"], complete["Age"], complete["Sex"])

        if set(complete) != set(features):
            raise ModelInputError("The answers do not match the model's inputs: " + (_diff(set(features), set(complete)) or "different names"))
        return complete

    @staticmethod
    def _frame(values, features):
        import numpy
        import pandas
        frame = pandas.DataFrame({name: [values[name] if values[name] is not None else numpy.nan] for name in features})
        for name in features:
            if isinstance(values[name], str):
                frame[name] = frame[name].astype(object)
        return frame

    def explain(self, row, _checking=False):
        """Same contract as ModelService.explain() (see its docstring): TreeSHAP through the calibration curve when present."""
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
        complete = self._check_row(row, features)
        frame = self._frame(complete, features)
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

        sign = 1.0 if self._high_index == 1 else -1.0
        margin = max(min(float(raw[0].sum()), 30.0), -30.0)
        positive = 1.0 / (1.0 + math.exp(-margin))
        if calibrator is not None:
            try:
                positive = float(calibrator.predict(numpy.array([positive]))[0])
            except Exception as error:
                raise ExplanationUnavailable(f"could not apply the model's calibration curve ({type(error).__name__}: {error})") from error
        from_contributions = positive if self._high_index == 1 else 1.0 - positive
        given = float(self._pipeline.predict_proba(frame)[0][self._high_index])
        if abs(from_contributions - given) > 1e-4:
            raise ExplanationUnavailable(f"the contributions add up to {from_contributions:.6f} but the model gives {given:.6f}")

        totals = dict.fromkeys(features, 0.0)
        for owner, value in zip(_owners(transform, features), raw[0][:-1]):
            totals[owner] += sign * float(value)
        effects = [{"name": name, "label": _stage2_label(name), "effect": value} for name, value in totals.items()]
        effects.sort(key=lambda item: (-abs(item["effect"]), item["name"]))
        return {"probability": given, "effects": effects}


def stage2_describer(lab_catalog=None):
    """
    A describe(name, inputs) function for services/explanations.py, for Enhanced Screening's mixed inputs: the 27
    Stage 1 answers (looked up in Stage 1's own catalog), the lab_catalog fields, and eGFR (always derived, so it
    is described from the Serum_Creatinine, Age and Sex actually saved with the result, never guessed on its own).
    `inputs` is the row saved with the assessment: the same 27 answers plus whichever lab values were given.
    """
    lab_catalog = lab_catalog or lab_contract.load_lab_catalog()
    screening_catalog = contract.load_catalog()

    def describe(name, inputs):
        if name == "eGFR":
            if "Serum_Creatinine" not in inputs:
                return None
            value = estimate_gfr(inputs["Serum_Creatinine"], inputs["Age"], inputs["Sex"])
            text = f"{value:g} mL/min/1.73m\u00b2"
            return "eGFR", text, text
        if name in STAGE1_LIKE_FIELDS:
            question = contract.question_for(screening_catalog, name)
            answer = contract.answer_text(question, inputs)
            if answer is None:
                return None
            return question["short"], answer, contract.answer_text(question, inputs, brief=True)
        if name not in inputs:
            return None
        field = lab_contract.field_for(lab_catalog, name)
        text = lab_contract.answer_text(field, inputs[name])
        return field["short"], text, text
    return describe


def re_hex64(value):
    import re
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value)))


def _stage2_label(name):
    """A short label for a Stage 2 input: the Stage 1 question's own label when it is one, else its lab_catalog label."""
    if name in STAGE1_LIKE_FIELDS:
        try:
            return contract.question_for(contract.load_catalog(), name)["short"]
        except StopIteration:
            pass
    if name == "eGFR":
        return "eGFR"
    catalog = lab_contract.load_lab_catalog()
    try:
        return lab_contract.field_for(catalog, name)["short"]
    except StopIteration:
        return name
