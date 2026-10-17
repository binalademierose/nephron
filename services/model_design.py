"""
model_design.py - how each installed model turns answers into a result.

Everything here is READ from what is installed - the loaded pipeline object, model_metadata.json, and the
model_metrics.json that model_report.py measured on labelled data. Nothing is typed in or estimated: a part that
cannot be read (an older metrics file, a model that is not ready) is reported as missing, never filled in.

  pipeline_steps()   the saved pipeline, step by step, in plain words (fill blanks, encode answers, XGBoost with
                     N trees, isotonic calibration, the threshold rule)
  input_groups()     where each model's inputs come from, with how much of the model's weight each group carries
  histogram() / tradeoff_lines()
                     SVG-ready geometry for the charts on the How-the-models-work page
"""
# Chart frame sizes (SVG user units); the templates draw inside these.
HIST_W, HIST_H = 400, 160
TRADE_W, TRADE_H = 400, 180


# ------------------------------------------------------------------ the pipeline, in plain words
def _class_name(obj):
    return type(obj).__name__


def _imputer_words(imputer):
    strategy = getattr(imputer, "strategy", None)
    words = {"median": "a blank number is filled with the typical (median) value",
             "mean": "a blank number is filled with the average value",
             "most_frequent": "a blank answer is filled with the most common answer",
             "constant": f"a blank answer becomes its own answer, \"{getattr(imputer, 'fill_value', '')}\""}.get(strategy, "blanks are filled in")
    if getattr(imputer, "add_indicator", False):
        words += ", and the model is also told the value was blank"
    return words


def _transformer_words(transformer):
    """One sentence for one preprocessing transformer (or a small chain of them)."""
    if transformer in ("drop", None):
        return None
    if transformer == "passthrough":
        return "used exactly as given"
    steps = getattr(transformer, "steps", None)
    if steps:
        parts = [_transformer_words(step) for _, step in steps]
        return "; then ".join(part for part in parts if part)
    name = _class_name(transformer)
    if name == "SimpleImputer":
        return _imputer_words(transformer)
    if name == "OneHotEncoder":
        return "each answer becomes its own yes/no column (one-hot encoding)"
    if name == "Binarizer":
        threshold = getattr(transformer, "threshold", None)
        return f"turned into yes/no at {threshold:g}" if isinstance(threshold, (int, float)) else "turned into yes/no"
    if name in ("StandardScaler", "MinMaxScaler", "RobustScaler"):
        return "numbers are put on one common scale"
    if name == "OrdinalEncoder":
        return "each answer is given a number"
    return name


def _columns_count(columns):
    try:
        return len(columns)
    except TypeError:
        return None


def _prepare_step(column_transformer):
    items = []
    fitted = getattr(column_transformer, "transformers_", None) or getattr(column_transformer, "transformers", [])
    for name, transformer, columns in fitted:
        if name == "remainder" and transformer == "drop":
            continue
        words = _transformer_words(transformer)
        if not words:
            continue
        count = _columns_count(columns)
        label = name.replace("_", " ")
        items.append({"label": label[:1].upper() + label[1:], "count": count, "words": words})
    return {"kind": "prepare", "icon": "layers", "title": "Prepare the answers",
            "detail": "Before the model sees anything, every answer is turned into numbers the same way it was in training.",
            "items": items}


MODEL_PARAMS = (("n_estimators", "decision trees"), ("max_depth", "levels deep at most"), ("learning_rate", "learning rate"),
                ("subsample", "of the rows used per tree"), ("colsample_bytree", "of the inputs used per tree"),
                ("min_child_weight", "minimum child weight"), ("reg_lambda", "L2 regularisation"))


def _model_step(estimator):
    name = _class_name(estimator)
    params = {}
    try:
        params = estimator.get_params()
    except Exception:
        pass
    items = []
    for key, words in MODEL_PARAMS:
        value = params.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            shown = f"{value:g}" if isinstance(value, float) else str(value)
            if key in ("subsample", "colsample_bytree") and isinstance(value, float):
                shown = f"{value * 100:.0f}%"
            items.append({"label": key, "count": None, "words": f"{shown} {words}"})
    plain = {"XGBClassifier": "XGBoost: many small decision trees, each one correcting the mistakes of those before it",
             "RandomForestClassifier": "Random forest: many decision trees that vote",
             "GradientBoostingClassifier": "Gradient boosting: small decision trees, each correcting the ones before it",
             "LogisticRegression": "Logistic regression: one weighted sum of the inputs"}.get(name, name)
    trees = params.get("n_estimators")
    title = f"{'XGBoost' if name == 'XGBClassifier' else name} model" + (f" - {trees} trees" if isinstance(trees, int) else "")
    return {"kind": "model", "icon": "gauge", "title": title, "detail": plain + ".", "items": items}


def _calibration_step(wrapper):
    method = getattr(wrapper, "method", "isotonic")
    return {"kind": "calibrate", "icon": "trending-up", "title": "Calibrate the probability",
            "detail": f"The trees' raw score is adjusted ({method} calibration) so that, for example, 30% means about 30 in "
                      "100 such people had the condition in the data it learned from.", "items": []}


def _walk(obj, steps):
    """Append the steps of a saved object, outermost wrapper last (a calibration wrapper comes after its model)."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.compose import ColumnTransformer
    if isinstance(obj, CalibratedClassifierCV):
        fitted = getattr(obj, "calibrated_classifiers_", None)
        inner = fitted[0].estimator if fitted else getattr(obj, "estimator", None)
        if inner is not None:
            _walk(inner, steps)
        steps.append(_calibration_step(obj))
        return
    pipeline_steps = getattr(obj, "steps", None)
    if pipeline_steps:
        for _, step in pipeline_steps:
            _walk(step, steps)
        return
    if isinstance(obj, ColumnTransformer):
        steps.append(_prepare_step(obj))
        return
    if hasattr(obj, "predict_proba"):
        steps.append(_model_step(obj))
        return
    words = _transformer_words(obj)
    if words:
        steps.append({"kind": "prepare", "icon": "layers", "title": "Prepare the answers", "detail": words[:1].upper() + words[1:] + ".", "items": []})


def pipeline_steps(service, inputs_title, inputs_detail):
    """[{kind, icon, title, detail, items}] from the answers to the result, or [] when the model is not ready."""
    if service is None or not getattr(service, "ready", False) or getattr(service, "_pipeline", None) is None:
        return []
    meta = service.metadata or {}
    steps = [{"kind": "inputs", "icon": "clipboard-list", "title": inputs_title, "detail": inputs_detail, "items": []}]
    try:
        _walk(service._pipeline, steps)
    except Exception:              # an object this page cannot read: say so rather than guess
        steps.append({"kind": "model", "icon": "gauge", "title": _class_name(service._pipeline),
                      "detail": "This saved model could not be broken into its steps here.", "items": []})
    threshold = meta.get("threshold")
    if isinstance(threshold, (int, float)):
        steps.append({"kind": "threshold", "icon": "alert-triangle", "title": f"Compare with the {threshold * 100:.2f}% threshold",
                      "detail": f"At or above it: higher risk. Below it: lower risk. Chosen by: {meta.get('threshold_method', 'not recorded')}.",
                      "items": []})
    steps.append({"kind": "result", "icon": "check-circle", "title": "The result shown to the person",
                  "detail": "The risk level, the probability, and (when the model can explain it) what affected it most.", "items": []})
    return steps


# ------------------------------------------------------------------ where the inputs come from
def input_groups(features, importance, groups):
    """groups: [(label, names), ...] in display order. Returns [{label, count, names, weight, share}] - weight is
    the share of the model's overall importance carried by that group (from importance(), which sums to ~100)."""
    weights = {row["name"]: row["percent"] for row in importance}
    taken, rows = set(), []
    for label, names in groups:
        members = [name for name in features if name in set(names) and name not in taken]
        taken |= set(members)
        if members:
            rows.append({"label": label, "count": len(members), "names": members,
                         "weight": round(sum(weights.get(name, 0) for name in members), 1)})
    rest = [name for name in features if name not in taken]
    if rest:
        rows.append({"label": "Other inputs", "count": len(rest), "names": rest, "weight": round(sum(weights.get(n, 0) for n in rest), 1)})
    top = max((row["weight"] for row in rows), default=0) or 1
    for row in rows:
        row["share"] = round(row["weight"] / top * 100)
    return rows


# ------------------------------------------------------------------ chart geometry
def histogram(metrics, width=HIST_W, height=HIST_H):
    """Bars for the score distribution, as a SHARE of each group (so a small group is not dwarfed by a big one).
    None when the metrics file predates the distribution (re-run model_report.py)."""
    dist = (metrics or {}).get("distribution")
    if not dist:
        return None
    edges, pos, neg = dist["edges"], dist["positive"], dist["negative"]
    pos_total, neg_total = sum(pos) or 1, sum(neg) or 1
    pos_share = [n / pos_total for n in pos]
    neg_share = [n / neg_total for n in neg]
    peak = max(pos_share + neg_share) or 1
    slot = width / len(pos)
    bar = max(slot / 2 - 1.5, 1)              # two bars per bin, a 1px gap between them and between bins
    bins = []
    for i in range(len(pos)):
        x = i * slot
        h_neg, h_pos = neg_share[i] / peak * height, pos_share[i] / peak * height
        bins.append({"range": f"{edges[i] * 100:.0f}-{edges[i + 1] * 100:.0f}%",
                     "neg": {"x": round(x + 1, 2), "y": round(height - h_neg, 2), "w": round(bar, 2), "h": round(h_neg, 2),
                             "count": neg[i], "share": round(neg_share[i] * 100, 1)},
                     "pos": {"x": round(x + 1 + bar + 1, 2), "y": round(height - h_pos, 2), "w": round(bar, 2), "h": round(h_pos, 2),
                             "count": pos[i], "share": round(pos_share[i] * 100, 1)}})
    threshold = metrics.get("threshold")
    return {"bins": bins, "width": width, "height": height, "peak_percent": round(peak * 100),
            "threshold_x": round(threshold * width, 2) if isinstance(threshold, (int, float)) else None,
            "positives": sum(pos), "negatives": sum(neg)}


def tradeoff_lines(metrics, width=TRADE_W, height=TRADE_H):
    """Sensitivity and specificity as the threshold moves from 0 to 100%, with the chosen threshold marked."""
    rows = (metrics or {}).get("tradeoff")
    if not rows:
        return None

    def line(index):
        return " ".join(f"{row[0] * width:.1f},{(1 - row[index]) * height:.1f}" for row in rows)
    threshold = metrics.get("threshold")
    return {"sensitivity": line(1), "specificity": line(2), "width": width, "height": height,
            "threshold_x": round(threshold * width, 2) if isinstance(threshold, (int, float)) else None,
            "at_threshold": {"sensitivity": metrics.get("sensitivity"), "specificity": metrics.get("specificity")},
            "rows": rows[::5]}
