# The saved model: what Nephron needs, and how to make it

This file is about the **Stage 1 (preliminary)** model. For **Stage 2 (Enhanced Screening)** - a provided artifact,
not trained by this project, with its own dataset and threshold rule - see `ml/model_stage2/README.md` instead.

Nephron **never trains a model**. It loads one file that you make in the notebook, checks it very strictly, and only then offers
screening. Until a model passes every check the dashboard says "Screening is not available yet", nothing is analysed and nothing is
saved. There is no built-in or placeholder model.

```
ml/
  feature_catalog.json            the 31 screening questions. The form, the website's checks, the notebook and the model are all compared with this file.
  notebooks/
    CKD_Stage1_Modeling.ipynb     trains Random Forest and XGBoost on CKD_400k.csv and saves the XGBoost model (RUN THIS)
  model/
    model_metadata.json           written by the notebook: describes the model
    final_model.joblib            written by the notebook: the fitted pipeline
  validation_holdout.csv          written by the notebook: data the model never trained on (used only to check the threshold)
```

## The steps (Windows)
1. **Libraries.** In the environment you will run Jupyter in, you need `scikit-learn` (1.2 or newer), `xgboost`, `pandas`, `numpy`, `joblib`, `matplotlib`.
   If scikit-learn is 1.6 or newer, xgboost must be **2.1.4 or newer** (the notebook stops with a clear message if not): `pip install -U xgboost`.
2. **Run the notebook.** Open `ml/notebooks/CKD_Stage1_Modeling.ipynb`. In the **Settings** cell check `PROJECT_DIR`
   (`D:\4ADA\NEPHRON_DEVELOPMENT\SYSTEM_DEV`). It looks for `CKD_400k.csv` near the notebook and the project; if it cannot find it, set `DATA_PATH`.
   Run **Kernel > Restart and Run All**. To try it quickly first, set `SAMPLE_ROWS_FOR_A_QUICK_TRIAL = 50000`, then run it again in full.
3. **Use the same versions in the Flask project.** A saved model only loads reliably with the versions it was saved with. They are printed at the top of the
   notebook and saved in `model_metadata.json` (`library_versions`). Install exactly those in the environment that runs the website
   (`requirements.txt` lists the names). `verify_model.py` prints the exact `pip install` command if they differ.
4. **Check it.** In a terminal in `SYSTEM_DEV`:
   ```
   python verify_model.py
   python verify_model.py --validation-csv ml\validation_holdout.csv --target CKD
   ```
   Every line must say PASS and the last message must be ACCEPTED / consistent. The second command also proves that the threshold belongs to this model, and that
   the **website's own way of asking the model** (one person at a time, after its strict checks) gives exactly the same probabilities as the pipeline used directly.
5. **Restart the website.** If the checks pass, **Start Assessment** opens. The reason for any failure is also written to `logs/nephron.log`.

## What the notebook does (CRISP-DM)
Business understanding, data understanding, data preparation, modeling, evaluation, deployment. In short:
- Reads the 31 predictors from `feature_catalog.json` (not typed in the notebook) and **stops** if the dataset disagrees with the form
  (a different set of answers, a different range, a missing column). Three (SugaryDrinksAddedSugar, UltraProcessedFoodFrequency,
  SaturatedFatDairyIntake) were added after `ml/DATASET_AUDIT_CKD_400k.md` found a plausible, consistent direction for each; blank answers
  for the first two are recoded the same way blank Alcohol_Consumption already was (see the notebook's "Three assumptions" section).
- Uses no laboratory value and no `Frailty_Index`, and audits the excluded columns.
- Splits 70% train, 15% validation, 15% test. The winning model (XGBoost) is then **isotonic-calibrated**
  (`CalibratedClassifierCV(method="isotonic", cv=5, ensemble=False)`), fitted on out-of-fold predictions of the training set only, so
  its predicted probability better matches the observed CKD rate. The **validation** set then picks the threshold (Youden's J, on the
  calibrated probability) for the very calibrated model that is saved. The **test** set is looked at once.
- Trains Random Forest and XGBoost only. XGBoost is saved (the production model); Random Forest is the comparison. If Random Forest is
  clearly better the notebook says so; that is a decision for the team.
- Has **no imputer** and uses `OneHotEncoder(handle_unknown="error")`: the pipeline refuses an answer it has not seen and never fills a missing one.
- Reports ROC-AUC, PR-AUC, sensitivity, specificity, PPV, NPV, a calibration table, factors, and ROC-AUC by sex, age band, ethnicity and country.

## Facts about CKD_400k.csv you should know (and may be asked about)
| Fact | What it means |
|---|---|
| **The data is synthetic** | A questionnaire predicting CKD very well is a property of how the data was made, not evidence about real patients. |
| **About 49% of the rows have CKD** | The predicted probability is relative to a population like this one, not a person's absolute risk. Nephron calls it "Predicted Risk Probability" and never a diagnosis. |
| **Blank Alcohol_Consumption = does not drink** | In this file 36% of the rows are blank; in the earlier dataset the same group was the text `None`. The notebook recodes blank to `None` and prints the count. Confirm this with whoever made the dataset. |
| **`Country` carries no signal** | The CKD rate is the same in every country, and there is no Philippines category. A person in the Philippines chooses "Other". Removing the question is an option for the team (it would be changed in `feature_catalog.json` and the model retrained). |
| **Other columns exist** (symptoms, diet, exposures, and two unusual ones) | They are not part of the 31 Stage 1 predictors and are not used. **Read `ml/DATASET_AUDIT_CKD_400k.md`**: it classifies all 92 columns with the measurement behind each verdict. Several of them are duplicates, constant, filled-in, or point the wrong way medically, so they must not simply be added. Adding any of them is a team decision that changes the form and needs a retrain. |

## The model file and the metadata (what the website checks)
`model_metadata.json` holds: `schema_version`, `artifact_file`, `artifact_sha256`, `model_name`, `model_version`, `high_risk_class`, `threshold`,
`threshold_method`, `stage` ("preliminary"), `features` (the model's input names, in its own order) and `library_versions`.
The website proves that the file is the one recorded (SHA-256) and was saved with the installed versions; that its inputs are exactly the questions;
that every answer the form can send is one the model was trained on; that its classes and threshold are sound; that it really runs; and that every input
maps to its feature importance. The saved object is `CalibratedClassifierCV(isotonic, ensemble=False)` wrapping `Pipeline[ColumnTransformer -> XGBoost]`,
not a bare pipeline - the website (`services/model_service.py`) unwraps this the same way the notebook's own export cell does, both for these checks
and for explaining a single result. The rule everywhere: **probability of the high-risk class >= threshold means High Preliminary Risk.**

## Explaining one person's result
The result page shows two cards, "What raised your estimate" and "What lowered your estimate": how much each of the person's own answers raised or lowered the estimate compared with an
average person in the training data (up to five in each card, one shared scale for the bars). This uses XGBoost's built-in TreeSHAP contributions (`Booster.predict(..., pred_contribs=True)`), so **the model does not
need to be retrained** and no extra library is needed. It is worked out again, each time a result is opened, from the answers saved with it.

It is shown only when all of these are true, so a wrong explanation can never appear:
- the final model in the pipeline is an XGBoost model, and `xgboost` can be imported by the website;
- the contributions add up to exactly the probability the model gives (`verify_model.py` checks this, on the line "Each result can be explained");
- the result was made by the model that is running now (same `model_version`), and the probability worked out again equals the one that was saved.

If one of these fails, screening still works and the result page says "No explanation for this result". The model-wide importance (`Strongest factors overall`
in `verify_model.py`) is only a developer's check and is not shown to people.

## Only load models you made
A saved model file is a Python pickle. Loading one runs code, so only ever put a file you created yourself in `ml/model`.
The SHA-256 in the metadata makes the website refuse a file that was swapped or damaged after it was exported.
`ml/validation_holdout.csv` is a data file: do not put it in a public repository (it is in `.gitignore`).

## If you train somewhere else
Any other notebook works if it produces the same two files. It must save a fitted scikit-learn `Pipeline` (optionally wrapped in
`CalibratedClassifierCV(isotonic, ensemble=False)`, as the reference notebook does) trained on a pandas DataFrame with exactly the 31 catalog
inputs (categories exactly as in the catalog, XGBoost as the last classifier step), and a `model_metadata.json` with the fields above, with
the threshold computed from that saved model on data it did not train on. The export cell of `CKD_Stage1_Modeling.ipynb` (section 7) is the reference.
