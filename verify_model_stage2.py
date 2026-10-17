"""
verify_model_stage2.py - checks the saved Stage 2 (Enhanced Screening) model and tells you plainly whether Nephron
will accept it.

    python verify_model_stage2.py                  check the model in ml/model_stage2 (or MODEL_STAGE2_DIR from .env)
    python verify_model_stage2.py --model-dir PATH check the model in another folder

It runs exactly the checks the website runs when it starts (services/model_service_stage2.py), so if this says PASS
the website will offer Enhanced Screening, and if it says FAIL the website will say Enhanced Screening is
unavailable and this tells you why. It never trains or changes anything.

Unlike verify_model.py (Stage 1), there is no --validation-csv option here: this model's threshold was not chosen
by Youden's J, so there is no single formula to recompute it by (see ml/model_stage2/README.md). What this DOES
check is that the website's own way of asking the model (one person at a time, through Stage2ModelService, after
its strict checks) gives exactly the same probability as the saved pipeline asked directly - the same website-path
proof verify_model.py makes for Stage 1.
"""
import argparse
import os
import sys

from config import Config
from services import lab_contract
from services.model_service_stage2 import STAGE1_LIKE_FIELDS, Stage2ModelService


def main():
    parser = argparse.ArgumentParser(description="Check the saved Nephron Stage 2 (Enhanced Screening) model.")
    parser.add_argument("--model-dir", default=Config.MODEL_STAGE2_DIR)
    args = parser.parse_args()

    catalog = lab_contract.load_lab_catalog()
    service = Stage2ModelService(args.model_dir, catalog)
    ready = service.load()

    print(f"Checking the Stage 2 model in: {args.model_dir}")
    print(f"Against the 27 Stage 1 answers it reuses, the {len(catalog['fields'])} lab fields in ml/lab_catalog.json, and eGFR\n")
    for check in service.checks:
        label = "PASS" if check.ok else ("WARN" if not check.fatal else "FAIL")
        print(f"  [{label}] {check.name}")
        if not check.ok:
            print(f"         {check.detail}")

    print()
    if not ready:
        print(f"NOT ACCEPTED: {service.reason}")
        return 1

    meta = service.metadata
    print(f"ACCEPTED: {meta['model_name']}, version {meta['model_version']}")
    print(f"  High-risk class: {meta['high_risk_class']}   Threshold: {meta['threshold']:.6f} ({meta['threshold'] * 100:.2f}%) "
          f"on the probability of that class")
    print("  Rule: a probability at or above the threshold is High Enhanced Screening, below it is Low Enhanced Screening")
    print(f"  Threshold method: {meta['threshold_method']}")
    print("  Strongest factors overall (model-wide, only a check): " + ", ".join(f"{f['label']} ({f['percent']}%)" for f in service.factors()))
    if service.can_explain:
        print("  Explaining one person's result ('What raised/lowered your estimate'): available")
    else:
        print("  Explaining one person's result: NOT available. Enhanced Screening still works. See the [WARN] line above.")

    return _check_website_path(service)


def _check_website_path(service, rows=200):
    """The website asks the model for ONE person at a time, after its own checks. Prove that gives exactly the
    same probabilities as the saved pipeline asked directly, on a handful of made-up but plausible people."""
    import random

    from services.model_service import ModelInputError

    catalog = service.lab_catalog
    rng = random.Random(20260101)
    worst, mismatches, compared = 0.0, 0, 0
    for _ in range(rows):
        row = {name: (rng.uniform(1.0, 95.0) if name in ("Age",) else rng.choice([0, 1])) for name in STAGE1_LIKE_FIELDS}
        row["Country"], row["Sex"] = rng.choice(["USA", "UK", "India", "Canada", "Australia", "Other"]), rng.choice(["Female", "Male"])
        row["Ethnicity"] = rng.choice(["Asian", "Black", "Hispanic", "Other", "White"])
        row["Smoking_Status"] = rng.choice(["Never", "Former", "Current"])
        row["Alcohol_Consumption"] = rng.choice(["None", "Moderate", "Heavy"])
        row["Physical_Activity_Level"] = rng.choice(["Sedentary", "Light", "Moderate", "Active"])
        row["Age"] = round(rng.uniform(18, 95), 1)
        row["BMI"] = round(rng.uniform(16, 45), 1)
        for name in ("Exercise_Hours_Per_Week", "Water_Intake_L", "Fast_Food_Frequency_Per_Week", "Sleep_Duration_Hours"):
            row[name] = round(rng.uniform(0, 10), 1)
        creatinine = round(rng.uniform(0.4, 6.0), 2)
        row["Serum_Creatinine"] = creatinine
        for field in catalog["fields"]:
            if field["name"] != "Serum_Creatinine" and rng.random() < 0.5:
                row[field["name"]] = round(rng.uniform(field["min"], field["max"]), 1)

        try:
            answer = service.predict(row)
            complete = service._check_row(row, service.metadata["features"])       # the same, fully-filled row predict() used
        except ModelInputError:
            continue
        compared += 1
        frame = service._frame(complete, service.metadata["features"])
        direct = float(service._pipeline.predict_proba(frame)[0][service._high_index])
        worst = max(worst, abs(answer["probability"] - direct))
        if (answer["classification"] == "high") != (direct >= service.threshold):
            mismatches += 1

    print(f"\nWebsite path against the pipeline used directly ({rows} made-up people)")
    print(f"  Compared: {compared}   Largest difference in probability: {worst:.2e}   Different High/Low results: {mismatches}")
    if compared == 0:
        print("  RESULT: no row could be compared, so nothing is proven.")
        return 1
    if worst > 1e-9 or mismatches:
        print("  RESULT: the website gives DIFFERENT answers from the pipeline. Do not use this model until this is understood.")
        return 1
    print("  RESULT: the website gives exactly the same answers as the pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
