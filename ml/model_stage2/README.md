# The Stage 2 (Enhanced Screening) model

Unlike `ml/model/` (Stage 1), this model was **not trained by this project's own notebook**. It is the Stage 2
artifact from `nephron_model.zip`, provided ready-made and used as-is, by decision. `final_model_stage2.pkl` and
`model_metadata.json` here are copied from that package (`model/final_model_stage2.pkl` and an adaptation of
`model/model_card_stage2.json` + `model/feature_schema_stage2.json` into the same metadata shape `ml/model/`
uses), so `services/model_service_stage2.py` can check it exactly as strictly as Stage 1's model is checked.

## What is different from Stage 1, and why

| | Stage 1 (`ml/model/`) | Stage 2 (here) |
|---|---|---|
| Trained on | `CKD_400k.csv` (400,000 rows, 49.3% CKD) | `CKD_RiskAssessment_Synthetic.csv` (200,000 rows, a different, older dataset) |
| Trained by | This project's own notebook (`ml/notebooks/CKD_Stage1_Modeling.ipynb`) | Provided ready-made in `nephron_model.zip` |
| Threshold method | Youden's J, on the calibrated probability | Highest threshold with pooled out-of-fold **sensitivity ≥ 0.98** (a deliberately different, recall-first rule - explained below) |
| Inputs | 31 questions, all required | 47 questions (27 of them the same as Stage 1's) plus eGFR, only Serum_Creatinine required |

Because the two models were trained on different data, **their probabilities are not on the same scale** and should
never be shown side by side as if they were. Nephron never does this: they are two separate assessment types
(`assessment_type = "preliminary"` and `"enhanced"`), with their own labels ("Preliminary Risk" / "Enhanced
Screening") and their own thresholds.

## Why the threshold rule is different, on purpose

Stage 1 screens someone who has answered only lifestyle and history questions - there is real uncertainty, and
Youden's J (the threshold that best balances catching true cases against false alarms) is the right general-purpose
choice. Stage 2 uses eGFR, serum creatinine and urine ACR, which are very close to how CKD is *defined* in this
data (see the "near-circular" note below) - at this point, missing a true case is a worse mistake than a false
alarm, so the model's own author chose the highest threshold that still keeps **sensitivity at or above 98%** on
held-out data, rather than the balance Youden's J would pick. This project keeps that choice rather than silently
overriding it with Youden's J, and says so plainly here instead of hiding the difference.

## eGFR is calculated, never asked

Nephron never asks a person for their eGFR. `services/egfr.py` calculates it with the CKD-EPI 2021 (race-free)
equation from serum creatinine, age and sex - the same way a real lab report calculates it - every time it is
needed. A person only needs to give (or have OCR read) their serum creatinine.

## The "near-circular" warning

eGFR, serum creatinine and urine ACR are very close to the clinical *definition* of CKD, not just risk factors for
it, so a model built on them scores close to a lookup table (ROC-AUC ≈ 0.998 on held-out data in the original
package's own evaluation). This is expected and was already acknowledged by whoever built the model
(`model_metadata.json`'s own `"near_circular_warning"` and `"output_semantics"` fields, carried over from the
original package). Nephron's own wording follows this: the Enhanced Screening result page calls itself a
**confirmation-level estimate, not independent evidence on its own**, and links back to the preliminary screening
it extends, rather than presenting it as a fresh, independent risk prediction.

## Vocabulary gap: Alcohol_Consumption

Stage 1's Alcohol_Consumption has three answers: None, Moderate, Heavy. This Stage 2 model was trained on data
with only Moderate and Heavy, with a blank kept as its own "Not_Reported" category. A person whose Stage 1 answer
was "None" therefore has no matching category here. `services/model_service_stage2.py`
(`STAGE1_VOCABULARY_GAPS`) translates "None" into a genuine missing value for this one field only, and the saved
pipeline's own trained imputer fills it in exactly the way it was trained to for a blank answer - it is never
guessed at, mapped to a specific word, or refused.

## Verifying it

There is no `verify_model.py`-equivalent command-line script for Stage 2 yet (see the project's open items). To
check it programmatically:

```python
from services import lab_contract
from services.model_service_stage2 import Stage2ModelService

service = Stage2ModelService("ml/model_stage2")
print(service.load(), service.reason)
for check in service.checks:
    print("PASS" if check.ok else ("WARN" if not check.fatal else "FAIL"), check.name, "-", check.detail)
```

Every check `services/model_service.py`'s checks perform for Stage 1 (SHA-256, library versions, classes, input
order, answer categories, that it actually runs, that every input maps to a feature importance, that a single
result can be explained) is performed the same way here.

## If you retrain this model yourselves later

Should the team ever decide to train a Stage 2 model on `CKD_400k.csv` instead of using this provided one (matching
Stage 1's own dataset, so both stages are drawn from the same population), it would need: the same 27 Stage 1
questions, the 20 fields in `ml/lab_catalog.json`, eGFR computed the same way, a `SimpleImputer` (or similar) so
optional lab values can genuinely be left blank the way this one allows, and a `model_metadata.json` in this same
shape with `"stage": "enhanced"`.
