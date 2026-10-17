"""
model_fixtures.py - builds a small STAND-IN model so the model service can be tested.

THIS IS NOT NEPHRON'S MODEL. It is a tiny scikit-learn pipeline trained on random answers, made only to check that
the loading, verification and prediction code works (and refuses what it should refuse). It is written to a temporary
folder by a test and thrown away. Nothing in the application ever calls this file.

It copies the shape of the real pipeline in the project's notebook: a ColumnTransformer (median imputer for numbers,
most-frequent imputer + OneHotEncoder(handle_unknown="ignore", drop="first") for categories) followed by a classifier
called "model". XGBoost is not needed here: the service only uses predict_proba, classes_ and feature_importances_,
which every scikit-learn-compatible classifier has.
"""
import hashlib
import importlib.metadata
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def libraries_available():
    try:
        import joblib, numpy, pandas, sklearn  # noqa: F401
        return True
    except ImportError:
        return False


try:
    from sklearn.base import BaseEstimator, ClassifierMixin
except ImportError:                                  # scikit-learn is optional; the tests that need it are skipped without it
    BaseEstimator = ClassifierMixin = object


class AdditiveClassifier(ClassifierMixin, BaseEstimator):
    """
    A TEST-ONLY classifier whose effects are exactly known: the log-odds of classes_[1] = bias + sum(weight * column).
    Because it is additive, each column's contribution for one person is exactly weight * (value - column mean), and the
    contributions plus the base value add up to the log-odds. It offers the same get_booster().predict(..., pred_contribs=True)
    that XGBoost offers, so the code that explains a single result can be tested with known right answers.
    """

    @staticmethod
    def _dense(X):
        import numpy as np
        return np.asarray(X.toarray() if hasattr(X, "toarray") else X, dtype=float)

    def fit(self, X, y):
        import numpy as np
        X, y = self._dense(X), np.asarray(y)
        self.classes_ = np.unique(y)
        positive = y == self.classes_[1]
        scale = X.std(axis=0) + 1e-9
        self.weights_ = 0.6 * (X[positive].mean(axis=0) - X[~positive].mean(axis=0)) / scale ** 2
        self.means_ = X.mean(axis=0)
        prevalence = float(np.clip(positive.mean(), 0.05, 0.95))
        self.bias_ = float(np.log(prevalence / (1 - prevalence)) - self.means_ @ self.weights_)
        importance = np.abs(self.weights_ * scale)
        self.feature_importances_ = importance / importance.sum()
        return self

    def _margin(self, X):
        return self._dense(X) @ self.weights_ + self.bias_

    def predict_proba(self, X):
        import numpy as np
        positive = 1 / (1 + np.exp(-self._margin(X)))
        return np.column_stack([1 - positive, positive])

    def predict(self, X):
        return self.classes_[(self._margin(X) > 0).astype(int)]

    def get_booster(self):
        return FakeBooster(self)


class FakeBooster:
    offset = 0.0            # a test sets this to break the "contributions add up" rule

    def __init__(self, model):
        self.model = model

    def predict(self, dmatrix, pred_contribs=False):
        import numpy as np
        assert pred_contribs, "the fake booster only knows pred_contribs"
        data = dmatrix.data
        contributions = self.model.weights_ * (data - self.model.means_)
        base = (self.model.bias_ + self.model.means_ @ self.model.weights_ + self.offset) * np.ones((len(data), 1))
        return np.hstack([contributions, base])


class FakeDMatrix:
    def __init__(self, data):
        import numpy as np
        self.data = np.asarray(data, dtype=float)


_ABSENT = object()


def _swap_xgboost(replacement):
    """
    Put `replacement` in sys.modules["xgboost"] while a test runs, and put back exactly what was there before.
    Only that ONE key is touched. (mock.patch.dict(sys.modules, ...) would also throw away every module imported while it was
    active, which later breaks pickling of scikit-learn models.)
    """
    import contextlib

    @contextlib.contextmanager
    def manager():
        previous = sys.modules.get("xgboost", _ABSENT)
        sys.modules["xgboost"] = replacement
        try:
            yield
        finally:
            if previous is _ABSENT:
                sys.modules.pop("xgboost", None)
            else:
                sys.modules["xgboost"] = previous
    return manager()


def fake_xgboost():
    """A context manager that puts a fake `xgboost` module (only DMatrix) in place while a test runs."""
    import types
    module = types.ModuleType("xgboost")
    module.DMatrix = FakeDMatrix
    return _swap_xgboost(module)


def no_xgboost():
    """A context manager under which `import xgboost` fails, as if the library were not installed."""
    return _swap_xgboost(None)


def build_stage2_stand_in(directory, lab_catalog, *, artifact_name="final_model_stage2.pkl"):
    """
    A tiny CalibratedClassifierCV(isotonic, ensemble=False)-wrapped stand-in for the Stage 2 model: 27 Stage-1-like
    inputs + the 20 ml/lab_catalog.json fields + eGFR = 48 columns, an XGBoost-shaped classifier (so explain() can be
    tested the same way as Stage 1's), and a SimpleImputer so it tolerates the missing optional lab values Stage 2
    is built to expect. Returns a StandIn(directory, pipeline, metadata, artifact_path).
    """
    import joblib
    import numpy as np
    import pandas as pd
    import sklearn
    from pathlib import Path
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder
    from services.model_service_stage2 import STAGE1_LIKE_FIELDS

    rng = np.random.default_rng(3)
    rows = 4000
    categorical = {"Country": ["Australia", "Canada", "India", "Other", "UK", "USA"], "Sex": ["Female", "Male"],
                  "Ethnicity": ["Asian", "Black", "Hispanic", "Other", "White"], "Smoking_Status": ["Current", "Former", "Never"],
                  "Alcohol_Consumption": ["Heavy", "Moderate"], "Physical_Activity_Level": ["Active", "Light", "Moderate", "Sedentary"]}
    binary = [f for f in STAGE1_LIKE_FIELDS if f not in categorical and f not in ("Age", "BMI", "Exercise_Hours_Per_Week",
             "Water_Intake_L", "Fast_Food_Frequency_Per_Week", "Sleep_Duration_Hours")]
    numeric_stage1 = {"Age": (18, 95), "BMI": (15, 55), "Exercise_Hours_Per_Week": (0, 20), "Water_Intake_L": (0.3, 5),
                      "Fast_Food_Frequency_Per_Week": (0, 14), "Sleep_Duration_Hours": (3, 11)}
    lab_fields = {f["name"]: (f["min"], f["max"], f["required"]) for f in lab_catalog["fields"]}

    data = {}
    for name, options in categorical.items():
        data[name] = rng.choice(options, rows)
    for name in binary:
        data[name] = rng.integers(0, 2, rows)
    for name, (low, high) in numeric_stage1.items():
        data[name] = rng.uniform(low, high, rows)
    for name, (low, high, required) in lab_fields.items():
        values = rng.uniform(low, high, rows)
        if not required:
            values[rng.random(rows) < 0.3] = np.nan          # about 30% missing, like a real lab report
        data[name] = values
    creatinine = np.clip(data["Serum_Creatinine"], 0.2, None)
    data["eGFR"] = 142 * np.minimum(creatinine / 0.9, 1) ** -0.302 * np.maximum(creatinine / 0.9, 1) ** -1.2 * 0.9938 ** data["Age"]
    frame = pd.DataFrame(data)
    score = (0.55 * (creatinine - 1.0) + 0.006 * (100 - data["eGFR"]) + 0.25 * data["Diabetes"] + 0.2 * data["Hypertension"]
            + 0.004 * (data["Age"] - 50) - 1.1)
    target = (rng.random(rows) < 1 / (1 + np.exp(-score))).astype(int)

    cat_cols = list(categorical)
    num_cols = [c for c in frame.columns if c not in cat_cols]
    preprocess = ColumnTransformer([
        ("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("encode", OneHotEncoder(handle_unknown="error"))]), cat_cols),
        ("numeric", SimpleImputer(strategy="median", add_indicator=True), num_cols),
    ])
    inner = Pipeline([("preprocess", preprocess), ("model", AdditiveClassifier())])
    top = CalibratedClassifierCV(inner, method="isotonic", cv=3, ensemble=False)
    top.fit(frame, target)

    classes = list(top.classes_)
    p_high = top.predict_proba(frame)[:, classes.index(1)]
    threshold = float(np.clip(np.quantile(p_high, 0.85), 0.05, 0.95))   # an arbitrary but plausible-shaped cutoff for a stand-in

    os.makedirs(directory, exist_ok=True)
    artifact_path = os.path.join(directory, artifact_name)
    joblib.dump(top, artifact_path)
    reference_row = {name: (frame[name].mode()[0] if name in cat_cols else float(frame[name].median())) for name in frame.columns if name != "eGFR"}
    metadata = {
        "schema_version": 1, "artifact_file": artifact_name, "artifact_sha256": _sha256_of(artifact_path),
        "model_name": "XGBoost", "model_version": "stand-in-stage2-test-1", "high_risk_class": 1, "threshold": threshold,
        "threshold_method": "stand-in, not a real threshold rule", "stage": "enhanced", "features": list(frame.columns),
        "library_versions": {"scikit-learn": sklearn.__version__},
        "categorical_answers": categorical, "reference_row": reference_row,
    }
    (Path(directory) / "model_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return StandIn(directory, top, metadata, artifact_path)


def _sha256_of(path):
    import hashlib
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class StandIn:
    def __init__(self, directory, pipeline, metadata, artifact_path):
        self.directory, self.pipeline, self.metadata, self.artifact_path = directory, pipeline, metadata, artifact_path

    def write_metadata(self):
        with open(os.path.join(self.directory, "model_metadata.json"), "w", encoding="utf-8") as handle:
            json.dump(self.metadata, handle, indent=2)

    def rehash(self):
        with open(self.artifact_path, "rb") as handle:
            self.metadata["artifact_sha256"] = hashlib.sha256(handle.read()).hexdigest()
        self.write_metadata()


def random_answers(catalog, rng, rows):
    """Valid random answers for `rows` people, as {input: [values]}."""
    data = {}
    for question in catalog["questions"]:
        name, kind = question["name"], question["kind"]
        if kind == "choice":
            options = sorted({o.get("model_value", o["value"]) for o in question["options"]})   # what the MODEL is trained on (Philippines -> Other)
            data[name] = [options[i] for i in rng.integers(0, len(options), rows)]
        elif kind == "yesno":
            data[name] = [int(v) for v in rng.integers(0, 2, rows)]
        elif kind == "number":
            low, high = question["min"], question["max"]
            if question.get("integer"):
                data[name] = [int(v) for v in rng.integers(low, high + 1, rows)]
            else:
                data[name] = [round(float(v), 1) for v in rng.uniform(low, high, rows)]
        elif kind == "bmi":
            data[name] = [round(float(v), 1) for v in rng.uniform(16, 50, rows)]
    for question in catalog["questions"]:
        if question["kind"] == "derived":
            data[question["name"]] = [1 if b >= question["value"] else 0 for b in data[question["of"]]]
    return data


def build_stand_in(directory, catalog, *, labels=(0, 1), feature_order=None, artifact_as_dict=False, country_options=None,
                   use_numpy=False, artifact_name="final_model.joblib", drop_column=None, estimator="gradient", calibrated=False):
    """
    Train a stand-in, save it with joblib and write model_metadata.json into `directory`.
      labels          the class labels: ("low", "high") makes scikit-learn order them ['high', 'low'], so the
                      high-risk class is column 0, which proves the service finds it by label.
      feature_order   the column order used for training (default: the catalog order reversed, so it differs).
      country_options train with only these Country values (to test a mismatch with the form).
      use_numpy       train on a bare array (no column names).
      drop_column     leave one input out of the model (to test a mismatch with the form).
      estimator       "gradient" (default: cannot explain a single result) or "additive" (exactly known effects, see AdditiveClassifier).
      calibrated      wrap the whole fitted Pipeline in CalibratedClassifierCV(isotonic, ensemble=False), matching the
                      real project's "CalibratedClassifierCV wrapping Pipeline[ColumnTransformer -> classifier]" shape.
                      Pass the string "ensemble" instead of True to build the (unsupported, ensemble=True) variant,
                      for testing that ModelService correctly refuses to explain a single result from it.
    """
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import roc_curve
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder

    rng = np.random.default_rng(0)
    rows = 12000                                   # generous enough that the one-hot columns of all 31 questions do not overfit
    data = random_answers(catalog, rng, rows)
    if country_options:
        data["Country"] = [country_options[i % len(country_options)] for i in range(rows)]
    names = feature_order or list(reversed([q["name"] for q in catalog["questions"]]))
    if drop_column:
        names = [n for n in names if n != drop_column]
    frame = pd.DataFrame({n: data[n] for n in names})
    score = 0.04 * (np.array(data["Age"]) - 50) + 0.9 * np.array(data["Diabetes"]) + 0.8 * np.array(data["Hypertension"]) \
        + 0.6 * np.array(data["Family_History_CKD"]) + 0.03 * (np.array(data["BMI"]) - 27) - 0.9
    high = (rng.random(rows) < 1 / (1 + np.exp(-score))).astype(int)
    low_label, high_label = labels
    target = np.where(high == 1, high_label, low_label)

    kinds = {q["name"]: q["kind"] for q in catalog["questions"]}
    categorical = [n for n in names if kinds[n] == "choice"]
    numeric = [n for n in names if kinds[n] != "choice"]
    preprocess = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median"), numeric),
        ("categorical", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                                  ("encoder", OneHotEncoder(handle_unknown="ignore", drop="first"))]), categorical),
    ])
    final = AdditiveClassifier() if estimator == "additive" else GradientBoostingClassifier(n_estimators=150, max_depth=2, random_state=0)
    pipeline = Pipeline([("preprocess", preprocess), ("model", final)])
    if use_numpy:
        pipeline = Pipeline([("model", GradientBoostingClassifier(n_estimators=10, max_depth=2, random_state=0))])
        top = pipeline
        top.fit(frame.select_dtypes("number").to_numpy(), target)
    elif calibrated:
        from sklearn.calibration import CalibratedClassifierCV
        top = CalibratedClassifierCV(pipeline, method="isotonic", cv=3, ensemble=(calibrated == "ensemble"))
        top.fit(frame, target)
    else:
        top = pipeline
        top.fit(frame, target)

    classes = list(top.classes_)
    p_high = top.predict_proba(frame if not use_numpy else frame.select_dtypes("number").to_numpy())[:, classes.index(high_label)]
    fpr, tpr, thresholds = roc_curve(high, p_high)                    # Youden's J on the probability of the HIGH-risk class
    best = float(thresholds[int(np.argmax(tpr - fpr))])
    threshold = best if 0 < best < 1 else 0.5

    os.makedirs(directory, exist_ok=True)
    artifact_path = os.path.join(directory, artifact_name)
    joblib.dump({"pipeline": top, "note": "stand-in"} if artifact_as_dict else top, artifact_path)
    with open(artifact_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    versions = {"python": sys.version.split()[0]}
    for label, dist in (("scikit-learn", "scikit-learn"), ("pandas", "pandas"), ("numpy", "numpy")):
        versions[label] = importlib.metadata.version(dist)
    metadata = {
        "schema_version": 1, "artifact_file": artifact_name, "artifact_sha256": digest,
        "model_name": "Stand-in model (tests only)", "model_version": "stand-in-test-1",
        "high_risk_class": high_label, "threshold": threshold,
        "threshold_method": ("Youden's J on the calibrated probability of the high-risk class (stand-in data)" if calibrated
                             else "Youden's J on the probability of the high-risk class (stand-in data)"),
        "stage": "preliminary", "features": names if not use_numpy else names, "library_versions": versions,
    }
    stand_in = StandIn(directory, top, metadata, artifact_path)
    stand_in.write_metadata()
    return stand_in
