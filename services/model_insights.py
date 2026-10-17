"""
model_insights.py - what the administrator's Model page shows about each installed model.

  - metrics:    computed from REAL predictions on a labelled dataset by model_report.py, and saved next to the
                model as model_metrics.json. Nothing here is estimated or typed in: if that file has not been
                made yet, the page says so and shows how to make it.
  - importance: how much each screening input weighs in the model OVERALL, read from the loaded model itself
                (its feature_importances_, mapped back from encoded columns to the questions people answer).
  - facts:      what model_metadata.json records - version, threshold and how it was chosen, training data,
                library versions, and any warning the model's author attached.
"""
import json
import os
from datetime import datetime, timezone

METRICS_FILE = "model_metrics.json"
ROC_POINTS = 60
SCORE_BINS = 20            # the score-distribution histogram: 0-5%, 5-10%, ... 95-100%
TRADEOFF_STEPS = 50        # the threshold trade-off curve: sensitivity and specificity at 0%, 2%, ... 100%


def compute_metrics(y_true, scores, threshold, source_name):
    """Every figure the page shows, from labels (1 = high risk) and the model's high-risk probabilities."""
    import numpy as np
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score, roc_curve

    y = np.asarray(y_true).astype(int)
    p = np.asarray(scores, dtype=float)
    predicted = p >= threshold
    tp = int((predicted & (y == 1)).sum()); fn = int((~predicted & (y == 1)).sum())
    fp = int((predicted & (y == 0)).sum()); tn = int((~predicted & (y == 0)).sum())

    def ratio(a, b):
        return round(a / b, 4) if b else None

    sensitivity, precision = ratio(tp, tp + fn), ratio(tp, tp + fp)
    fpr, tpr, _ = roc_curve(y, p)
    keep = np.unique(np.linspace(0, len(fpr) - 1, num=min(ROC_POINTS, len(fpr))).round().astype(int))
    return {
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": source_name, "rows": int(len(y)), "positives": int(y.sum()),
        "prevalence": ratio(int(y.sum()), len(y)), "threshold": float(threshold),
        "roc_auc": round(float(roc_auc_score(y, p)), 4), "pr_auc": round(float(average_precision_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "accuracy": ratio(tp + tn, len(y)), "sensitivity": sensitivity, "specificity": ratio(tn, tn + fp),
        "precision": precision, "npv": ratio(tn, tn + fn),
        "f1": round(2 * precision * sensitivity / (precision + sensitivity), 4) if precision and sensitivity else 0.0,
        "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
        "roc": [[round(float(fpr[i]), 4), round(float(tpr[i]), 4)] for i in keep],
        "distribution": score_distribution(y, p),
        "tradeoff": threshold_tradeoff(y, p),
    }


def score_distribution(y_true, scores, bins=SCORE_BINS):
    """How the model's probabilities are spread for people WITH and WITHOUT the condition: counts per score bin
    (the last bin includes 100%). Shows how cleanly the model separates the two groups, and where the threshold falls."""
    import numpy as np
    y, p = np.asarray(y_true).astype(int), np.clip(np.asarray(scores, dtype=float), 0, 1)
    edges = np.linspace(0, 1, bins + 1)
    positive, _ = np.histogram(p[y == 1], bins=edges)
    negative, _ = np.histogram(p[y == 0], bins=edges)
    return {"edges": [round(float(e), 4) for e in edges], "positive": [int(n) for n in positive], "negative": [int(n) for n in negative]}


def threshold_tradeoff(y_true, scores, steps=TRADEOFF_STEPS):
    """[[threshold, sensitivity, specificity], ...] for evenly spaced thresholds from 0 to 1 - what moving the
    threshold would gain on one side and cost on the other."""
    import numpy as np
    y, p = np.asarray(y_true).astype(int), np.asarray(scores, dtype=float)
    positives, negatives = int((y == 1).sum()), int((y == 0).sum())
    rows = []
    for t in np.linspace(0, 1, steps + 1):
        flagged = p >= t
        sensitivity = float((flagged & (y == 1)).sum() / positives) if positives else 0.0
        specificity = float((~flagged & (y == 0)).sum() / negatives) if negatives else 0.0
        rows.append([round(float(t), 4), round(sensitivity, 4), round(specificity, 4)])
    return rows


def save_metrics(model_dir, metrics):
    with open(os.path.join(model_dir, METRICS_FILE), "w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)


def load_metrics(model_dir):
    """The saved metrics, or None if model_report.py has not been run for this model (or the file is unreadable)."""
    path = os.path.join(model_dir or "", METRICS_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            metrics = json.load(handle)
    except (OSError, ValueError):
        return None
    return metrics if isinstance(metrics, dict) and "roc_auc" in metrics else None


def roc_polyline(metrics, size=200):
    """The saved ROC points as an SVG polyline (x = false positive rate, y = true positive rate)."""
    if not metrics or not metrics.get("roc"):
        return ""
    return " ".join(f"{fpr * size:.1f},{(1 - tpr) * size:.1f}" for fpr, tpr in metrics["roc"])


def importance(service, labels):
    """[{"name", "label", "percent" (of the total), "share" (0-100, strongest = 100)}], strongest first, for every
    input - read from the loaded model. [] when the model is not ready or exposes no importances."""
    if service is None or not getattr(service, "ready", False):
        return []
    weights = getattr(service, "_importance", None)
    if not weights:
        try:
            from services.model_service import _decompose, _importance_by_input
            transform, estimator, _ = _decompose(service._pipeline)
            weights = _importance_by_input(transform, estimator, service.metadata["features"])
        except Exception:
            return []
    total = sum(weights.values()) or 1
    top = max(weights.values()) or 1
    ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    return [{"name": name, "label": labels.get(name, name.replace("_", " ")), "percent": round(100 * value / total, 1),
             "share": round(100 * value / top)} for name, value in ranked if value > 0]


def facts(service):
    """The model card from model_metadata.json, in the order an administrator reads it."""
    meta = getattr(service, "metadata", None) or {}
    if not meta:
        return []
    rows = [("Algorithm", meta.get("model_name")), ("Version", meta.get("model_version")),
            ("Inputs", f"{len(meta.get('features', []))} questions and values" if meta.get("features") else None),
            ("Decision threshold", f"{meta['threshold'] * 100:.2f}% probability of high risk" if isinstance(meta.get("threshold"), (int, float)) else None),
            ("How the threshold was chosen", meta.get("threshold_method")),
            ("Trained on", meta.get("trained_on")), ("Where the model came from", meta.get("source")),
            ("What the probability means", meta.get("output_semantics")),
            ("Libraries", ", ".join(f"{k} {v}" for k, v in (meta.get("library_versions") or {}).items()) or None),
            ("Test ROC-AUC recorded by its author", f"{meta['test_roc_auc']:.4f}" if isinstance(meta.get("test_roc_auc"), (int, float)) else None)]
    return [(label, value) for label, value in rows if value]
