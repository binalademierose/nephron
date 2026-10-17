"""
model_report.py - measure an installed model on a LABELLED dataset and save the results for the administrator's
Model page (/admin/model). Run it on the machine that has the model and the data:

    python model_report.py --stage 1 --csv path/to/test_set.csv --target CKD
    python model_report.py --stage 2 --csv path/to/test_set.csv --target CKD

Use HELD-OUT data (rows the model was not trained on): metrics on training rows only show how well the model
remembers them. The figures are written to model_metrics.json in that model's folder; nothing is uploaded anywhere.
"""
import argparse
import os
import sys

from config import Config
from services import lab_contract, model_insights, screening_contract
from services.model_service import ModelService
from services.model_service_stage2 import Stage2ModelService


def main(argv=None):
    parser = argparse.ArgumentParser(description="Measure a Nephron model on labelled data and save the metrics.")
    parser.add_argument("--stage", choices=("1", "2"), required=True, help="1 = Preliminary Screening, 2 = Enhanced Screening")
    parser.add_argument("--csv", required=True, help="labelled data: the model's input columns plus the target column")
    parser.add_argument("--target", required=True, help="the target column, for example CKD or Diagnosis")
    parser.add_argument("--model-dir", help="the model folder (defaults to the app's own setting for that stage)")
    args = parser.parse_args(argv)

    import pandas as pd

    if args.stage == "1":
        folder = args.model_dir or Config.MODEL_DIR
        service = ModelService(folder, screening_contract.load_catalog())
    else:
        folder = args.model_dir or Config.MODEL_STAGE2_DIR
        service = Stage2ModelService(folder, lab_contract.load_lab_catalog())
    service.load()
    if not service.ready:
        print(f"The model in {os.path.abspath(folder)} is not ready: {service.reason}")
        return 1

    frame = pd.read_csv(args.csv, keep_default_na=False, na_values=[""])   # "None" is a real answer, not a blank
    features = service.metadata["features"]
    missing = [column for column in features + [args.target] if column not in frame.columns]
    if missing:
        print("The CSV lacks these columns: " + ", ".join(missing))
        return 2
    high = service.metadata["high_risk_class"]
    y = (frame[args.target].astype(str) == str(high)).astype(int)
    if y.nunique() < 2:
        print(f"The target column '{args.target}' needs both high-risk ({high!r}) and other rows.")
        return 2

    if args.stage == "1":
        scores = service.high_risk_probabilities(frame)
    else:
        scores = service._pipeline.predict_proba(frame[features])[:, service._high_index]
    metrics = model_insights.compute_metrics(y, scores, service.threshold, os.path.basename(args.csv))
    model_insights.save_metrics(folder, metrics)
    print(f"Measured {metrics['rows']} rows: ROC-AUC {metrics['roc_auc']}, accuracy {metrics['accuracy']}, "
          f"sensitivity {metrics['sensitivity']}, specificity {metrics['specificity']}")
    print(f"Saved to {os.path.join(os.path.abspath(folder), model_insights.METRICS_FILE)} - the administrator's Model page now shows it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
