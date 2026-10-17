"""
verify_model.py - checks a saved model against the screening questions, and tells you plainly whether Nephron will accept it.

    python verify_model.py                       check the model in ml/model (or MODEL_DIR from .env)
    python verify_model.py --model-dir PATH      check the model in another folder
    python verify_model.py --validation-csv FILE --target COLUMN
                                                 also (1) recompute the threshold from data the model did NOT train on and
                                                 compare it with the one in model_metadata.json, and (2) check that the
                                                 WEBSITE's way of asking the model (one person at a time, after its strict
                                                 checks) gives exactly the same probabilities as the pipeline used directly

It runs exactly the checks the website runs when it starts (services/model_service.py), so if this says PASS the website
will offer screening, and if it says FAIL the website will say screening is unavailable and this tells you why.
It never trains or changes anything.
"""
import argparse
import os
import sys

from config import Config
from services import screening_contract
from services.model_service import ModelService


def main():
    parser = argparse.ArgumentParser(description="Check the saved Nephron model.")
    parser.add_argument("--model-dir", default=Config.MODEL_DIR)
    parser.add_argument("--validation-csv", help="held-out data (the questions' columns plus the target) to recompute the threshold from")
    parser.add_argument("--target", help="the target column in the validation CSV, for example Diagnosis or CKD")
    args = parser.parse_args()

    catalog = screening_contract.load_catalog()
    print(f"Checking the model in: {os.path.abspath(args.model_dir)}")
    print(f"Against the {len(screening_contract.feature_names(catalog))} screening questions in ml/feature_catalog.json\n")
    service = ModelService(args.model_dir, catalog)
    service.load()

    for check in service.checks:
        label = "PASS" if check.ok else ("FAIL" if check.fatal else "WARN")
        print(f"  [{label}] {check.name}")
        if not check.ok:
            print(f"         {check.detail}")

    if not service.ready:
        print(f"\nNOT ACCEPTED. Screening will say it is unavailable.\nReason: {service.reason}")
        return 1

    meta = service.metadata
    print(f"\nACCEPTED: {meta['model_name']}, version {service.version}")
    print(f"  High-risk class: {meta['high_risk_class']!r}   Threshold: {service.threshold:.6f} ({service.threshold * 100:.2f}%) on the probability of that class")
    print(f"  Rule: a probability at or above the threshold is High Preliminary Risk, below it is Low Preliminary Risk")
    print(f"  Threshold method: {meta['threshold_method']}")
    print("  Strongest factors overall (model-wide, only a check): " + ", ".join(f"{f['label']} ({f['percent']}%)" for f in service.factors()))
    print("  Explaining one person's result ('What affected your result most'): "
          + ("available" if service.can_explain else "NOT available. Screening still works, and the result page says no explanation is available. See the [WARN] line above."))

    if args.validation_csv:
        return _check_threshold(service, args.validation_csv, args.target)
    print("\nTip: add --validation-csv FILE --target COLUMN to prove the threshold belongs to THIS model.")
    return 0


def _check_threshold(service, path, target):
    if not target:
        print("\n--validation-csv needs --target COLUMN")
        return 2
    import numpy as np
    import pandas as pd
    from sklearn.metrics import roc_auc_score, roc_curve

    # 'None' is a real answer (for example alcohol), so it must NOT be read as a missing value.
    frame = pd.read_csv(path, keep_default_na=False, na_values=[""])
    missing = [c for c in service.metadata["features"] + [target] if c not in frame.columns]
    if missing:
        print("\nThe validation file lacks these columns: " + ", ".join(missing))
        return 2
    high = service.metadata["high_risk_class"]
    y = (frame[target] == high).astype(int)
    if y.nunique() < 2:
        print(f"\nThe target column '{target}' has no rows equal to {high!r}, or only those. Check --target and high_risk_class.")
        return 2
    scores = service.high_risk_probabilities(frame)
    fpr, tpr, thresholds = roc_curve(y, scores)
    best = int(np.argmax(tpr - fpr))
    recomputed = float(thresholds[best])
    chosen = service.threshold
    at_chosen = scores >= chosen
    sensitivity = float((at_chosen & (y == 1)).sum() / (y == 1).sum())
    specificity = float((~at_chosen & (y == 0)).sum() / (y == 0).sum())
    print(f"\nThreshold check on {len(frame)} rows from {os.path.basename(path)}")
    print(f"  ROC-AUC: {roc_auc_score(y, scores):.4f}")
    print(f"  Youden's J threshold, recomputed from this model: {recomputed:.6f}")
    print(f"  Threshold in model_metadata.json:                {chosen:.6f}")
    print(f"  At the metadata threshold: sensitivity {sensitivity:.3f}, specificity {specificity:.3f}, Youden's J {sensitivity + specificity - 1:.3f} (best possible here: {tpr[best] - fpr[best]:.3f})")
    if abs(recomputed - chosen) <= 0.02 or (sensitivity + specificity - 1) >= (tpr[best] - fpr[best]) - 0.005:
        print("  RESULT: the threshold is consistent with this model.")
        return _check_website_path(service, frame)
    print("  RESULT: the threshold does NOT look like this model's. It may belong to another model (for example the Random Forest). Re-run the export cell.")
    return 1


def _check_website_path(service, frame, rows=500):
    """
    The website asks the model for ONE person at a time, after checking the answers. Here the same rows are asked
    both ways: through service.predict() (the website's path) and through the pipeline directly (the notebook's path).
    The probabilities must be identical, and so must the High/Low result.
    Rows that the website's form could never send (for example a water intake of 4.03 litres when the form stops at 4)
    are refused by the website by design; they are counted and left out.
    """
    import numpy as np
    from services.model_service import ModelInputError

    features = service.metadata["features"]
    sample = frame.sample(min(rows, len(frame)), random_state=0).reset_index(drop=True)
    direct = service.high_risk_probabilities(sample)                      # the pipeline used directly, all rows at once
    compared, refused, worst, class_differences = 0, {}, 0.0, 0
    for index in range(len(sample)):
        values = {name: (sample.at[index, name].item() if hasattr(sample.at[index, name], "item") else sample.at[index, name]) for name in features}
        try:
            answer = service.predict(values)                              # the website's path
        except ModelInputError as error:
            reason = str(error).split(":")[0]
            refused[reason] = refused.get(reason, 0) + 1
            continue
        compared += 1
        worst = max(worst, abs(answer["probability"] - float(direct[index])))
        class_differences += (answer["classification"] == "high") != (float(direct[index]) >= service.threshold)
    print(f"\nWebsite path against the pipeline used directly ({len(sample)} rows drawn at random)")
    print(f"  Compared: {compared} rows   Refused by the website's own checks (not answers the form can send): {sum(refused.values())} {dict(refused) if refused else ''}")
    print(f"  Largest difference in probability: {worst:.2e}   Different High/Low results: {class_differences}")
    if compared == 0:
        print("  RESULT: no row could be compared, so nothing is proven. Check the validation file.")
        return 1
    if worst > 1e-9 or class_differences:
        print("  RESULT: the website gives DIFFERENT answers from the pipeline. Do not use this model until this is understood.")
        return 1
    print("  RESULT: the website gives exactly the same answers as the pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
