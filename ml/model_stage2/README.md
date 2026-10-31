# The Stage 2 (Enhanced Risk Screening) model

This model is trained by the project's own notebook, `ml/notebooks/CKD_Stage2_Modeling.ipynb`, on **CKD_400k.csv** - the same
dataset as the Stage 1 model (`ml/model/`). It replaces an earlier Stage 2 model that had been trained on a different dataset
(CKD_RiskAssessment_Synthetic.csv). Only the dataset changed: the 48 inputs, the preprocessing, the model-selection rule and the
threshold rule are the same, so the website needed no code change.

## What is the same as Stage 1, and what is different

| | Stage 1 (`ml/model/`) | Stage 2 (here) |
|---|---|---|
| Trained on | CKD_400k.csv (400,000 rows) | CKD_400k.csv (400,000 rows) |
| Trained by | `ml/notebooks/CKD_Stage1_Modeling.ipynb` | `ml/notebooks/CKD_Stage2_Modeling.ipynb` |
| Split | 70% train / 15% validation / 15% test (random_state 42) | the same split: the same 60,000 test rows; trains on the other 340,000 |
| Inputs | 31 questions, all required | 27 of the Stage 1 questions + blood pressure + 18 lab values + eGFR = 48; only serum creatinine is a required lab value |
| Missing values | none allowed (answers are required) | median imputation + missing-value indicators for the lab values that have blanks; blank alcohol = Not_Reported |
| Threshold rule | Youden's J on the calibrated validation probabilities | highest calibrated threshold with pooled out-of-fold sensitivity >= 0.98 |

The two models are separate assessment types (`preliminary` and `enhanced`) with their own thresholds; the Stage 2 result is a
confirmation-level estimate built on a person's preliminary screening.

## Why the threshold rule is different, on purpose

Stage 1 screens from questions alone, and Youden's J balances catching true cases against false alarms. Stage 2 uses eGFR, serum
creatinine and urine ACR, which are close to how CKD is defined; at that point missing a true case is the worse mistake, so the
threshold is the highest one that still keeps sensitivity at or above 98% on out-of-fold predictions of the training rows.

## eGFR is calculated, never asked

`services/egfr.py` calculates eGFR with the CKD-EPI 2021 (race-free) equation from serum creatinine, age and sex. The notebook
verifies that the dataset's eGFR column is exactly that value on every row.

## The "near-circular" warning

eGFR, serum creatinine and urine ACR are part of the clinical definition of CKD. In CKD_400k.csv the plain rule
`eGFR < 60 or UACR > 300` agrees with the CKD label on about 99% of rows, so near-perfect scores are expected and are not evidence
of predictive power. The notebook reports the plain rule and a block-by-block (tier) analysis next to the model, and the website
calls the Enhanced Screening result a confirmation-level estimate.

## Alcohol_Consumption

Stage 1 asks None / Moderate / Heavy. In CKD_400k.csv people who do not drink are blank; the Stage 2 pipeline keeps a blank as its
own category, Not_Reported. `services/model_service_stage2.py` (`STAGE1_VOCABULARY_GAPS`) therefore passes a Stage 1 answer of
"None" as a blank, which the saved pipeline turns into Not_Reported - the same category it was trained on for non-drinkers.

## Verifying it

```
python verify_model_stage2.py
python model_report.py --stage 2 --csv ml\stage2_sealed_test.csv --target CKD
```
The first runs every check the website runs at start-up; the second writes `model_metrics.json` for the administrator's Model page.
