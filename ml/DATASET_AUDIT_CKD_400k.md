# CKD_400k.csv: column-by-column audit

400,000 rows, 92 columns, 49.3% with CKD. This audit looks at **every** column (not only the Stage 1 questions) and says, with the
measurement behind it, whether each one may be used in Stage 1 (preliminary screening, no laboratory), belongs to Stage 2
(laboratory), or must not be used. **The verdicts are recommendations. The team decides.** Anything marked "ADD" changes the form and needs the model
to be trained again.

## The short version
| Verdict | Columns |
|---|---|
| Stage 1: in use (31 questions, plus Height and Weight to work out the BMI) | 33 |
| Stage 1: recommended to ADD, needs your decision | 2 |
| Do NOT use | 26 |
| Stage 2 (laboratory / clinical) | 23 |
| Outcome, leakage or identifier | 8 |

## What was found (all measured on the 400,000 rows)
1. **The data is not one clean table.** 63,717 rows (15.9%) hold the *same* value in all five of DietQuality, FatigueLevels, NauseaVomiting, MuscleCramps and Itching
   (a placeholder), and among the 202,948 healthy rows those five columns have only 41,420 different combinations. Those rows also differ from the others in other columns
   (for example FruitVegetableIntake has no "Low" or "Very Low" in them). Ask whoever made the file how it was built.
2. **Several added columns point the wrong way.** A previous acute kidney injury goes with a *lower* CKD rate (0.439 vs 0.540), heavy-metal exposure with a much lower one (0.212 vs 0.659), and occupational
   chemicals with a lower one too. The result page has a card called "What lowered your estimate": these columns would put a real risk factor in it.
3. **Columns that look like factors are really consequences of the disease.** ClinicianImposedFluidRestriction (0.964 when 1) and Annual_Checkups (the CKD rate rises with every check-up).
4. **Adding the questionable columns makes the score look better by learning the artefacts.** ROC-AUC (gradient boosting, 200,000-row sample): the 28 original questions 0.964; plus the three
   wrong-direction columns 0.979; plus the five placeholder columns 0.993; plus fluid restriction and check-ups 0.980. A higher number here is a warning, not a gain.
5. **Some Stage 1 questions carry no signal in this data** (AUC 0.50): Country, Ethnicity, Water_Intake_L, Sleep_Duration_Hours and NSAID_Usage. The model learns nothing from them. Country also
   has no Philippines.
6. **Duplicates and dead columns.** FamilyHistoryKidneyDisease is identical to Family_History_CKD. Number_of_Medications is (about) the sum of six medicine answers already asked.
   Four columns are 0 in every row. Two unusual columns ("Gluta drip", "Gender Affirming Hormone Theraphy(hormonal pills)") have no relation to CKD and are sensitive.
7. **eGFR alone predicts CKD with AUC 0.996.** It is essentially the definition of CKD here. A model that uses eGFR (or serum creatinine, 0.897) diagnoses; it does not screen.

## What I recommend
* **Keep the 28 original Stage 1 questions** (the team's decision), and tell the panel that five of them carry no signal in this data.
* **Added three** (team decision): SugaryDrinksAddedSugar, UltraProcessedFoodFrequency and SaturatedFatDairyIntake, on 2026-09-24. Blank
  SugaryDrinksAddedSugar (10.7% of rows) was recoded to "None"; blank UltraProcessedFoodFrequency (2.3%) was recoded to "Never" - the same
  kind of assumption already made for Alcohol_Consumption. SaturatedFatDairyIntake has no blanks. The Stage 1 model must be re-trained
  (`ml/notebooks/CKD_Stage1_Modeling.ipynb`) for these to take effect; the form and `ml/feature_catalog.json` already ask for them.
* **Still only recommended, not added:** FamilyHistoryDiabetes and Edema (+0.013 ROC-AUC together with the three above, 0.964 to 0.976,
  measured; +0.008 without Edema; a small gain). Their direction is plausible and they are not duplicates. Before adding either, ask the
  data owner what a blank means for FamilyHistoryDiabetes (there is none for Edema).
* **Do not add anything from "Do NOT use".**
* **Stage 2:** decide the policy on eGFR and creatinine before Phase 6 (my advice: do not use them as predictors), and remember that a blank laboratory value means "not tested", not zero.

## How it was measured
* "Alone AUC": the ROC-AUC of that one column used by itself against CKD (a word column is replaced by the CKD rate of each of its answers), folded so it is never below 0.5.
  It says how much a column tells about CKD on its own. It does not say the column is safe or right.
* CKD rates are the share of rows with CKD for each answer. A blank is its own group.
* The gains in item 4 come from a gradient-boosting model trained on 70% of a 200,000-row sample and tested on the other 30%.

## Every column


### 1. Stage 1: in use (33)

| Column | Type | Blank | Alone AUC | Why |
|---|---|---|---|---|
| `Age` | int64 | 0 | 0.856 | One of the 28 Stage 1 questions. |
| `Sex` | str | 0 | 0.547 | One of the 28 Stage 1 questions. |
| `Ethnicity` | str | 0 | 0.502 | No signal here (AUC 0.502). Kept by decision. |
| `Country` | str | 0 | 0.501 | No signal here: the CKD rate is 49.1% to 49.5% in every country, and there is no Philippines. Kept by decision. |
| `Height_cm` | float | 0 | 0.541 | Asked on the form only to work out the BMI (BMI = weight / height squared in 100% of the rows). |
| `Weight_kg` | float | 0 | 0.624 | Asked on the form only to work out the BMI (BMI = weight / height squared in 100% of the rows). |
| `BMI` | float | 0 | 0.665 | One of the 28 Stage 1 questions. |
| `Smoking_Status` | str | 0 | 0.552 | One of the 28 Stage 1 questions. |
| `Alcohol_Consumption` | str | 145,279 | 0.511 | Blank = does not drink (an assumption to confirm). The direction is unusual: heavier drinking goes with a slightly LOWER CKD rate (0.471 vs 0.504); a small effect. |
| `Physical_Activity_Level` | str | 0 | 0.585 | One of the 28 Stage 1 questions. |
| `Exercise_Hours_Per_Week` | float | 0 | 0.585 | One of the 28 Stage 1 questions. |
| `Water_Intake_L` | float | 0 | 0.500 | No signal here (AUC 0.500; the CKD rate is 49% in every quarter). Kept by decision. |
| `Fast_Food_Frequency_Per_Week` | int64 | 0 | 0.530 | Weak but the right direction (CKD rate 0.465 in the lowest quarter, 0.532 in the highest). |
| `Sleep_Duration_Hours` | float | 0 | 0.501 | No signal here (AUC 0.501). Kept by decision. |
| `Diabetes` | int64 | 0 | 0.695 | One of the 28 Stage 1 questions. |
| `Hypertension` | int64 | 0 | 0.766 | One of the 28 Stage 1 questions. |
| `Cardiovascular_Disease` | int64 | 0 | 0.608 | One of the 28 Stage 1 questions. |
| `Heart_Failure` | int64 | 0 | 0.519 | One of the 28 Stage 1 questions. |
| `Hyperlipidemia` | int64 | 0 | 0.596 | One of the 28 Stage 1 questions. |
| `Kidney_Stones` | int64 | 0 | 0.550 | One of the 28 Stage 1 questions. |
| `Recurrent_UTI` | int64 | 0 | 0.520 | One of the 28 Stage 1 questions. |
| `Autoimmune_Disease` | int64 | 0 | 0.512 | One of the 28 Stage 1 questions. |
| `Family_History_CKD` | int64 | 0 | 0.515 | One of the 28 Stage 1 questions. |
| `Obesity` | int64 | 0 | 0.617 | Worked out from the BMI (BMI >= 30 in 100% of the rows). Not asked. |
| `ACE_Inhibitor` | int64 | 0 | 0.732 | A marker of the disease it treats (CKD rate 0.731 with vs 0.267 without), not a cause. The result page will show it as raising the estimate. |
| `ARB` | int64 | 0 | 0.553 | A marker of the disease it treats, like the ACE inhibitor. |
| `Diabetes_Medication` | int64 | 0 | 0.618 | A marker of diabetes and related disease. |
| `Statin` | int64 | 0 | 0.601 | A marker of heart-disease risk. |
| `Diuretic` | int64 | 0 | 0.560 | A marker of heart or blood-pressure disease. |
| `NSAID_Usage` | int64 | 0 | 0.500 | No signal here (CKD rate 49.3% with and 49.2% without). Kept by decision. |
| `UltraProcessedFoodFrequency` | str | 9,029 | 0.599 | Added to the form (team decision, 2026-09-24). Blank (2.3% of rows) recoded to 'Never', the same kind of assumption already made for Alcohol_Consumption. |
| `SugaryDrinksAddedSugar` | str | 42,844 | 0.671 | Added to the form (team decision, 2026-09-24). Blank (10.7% of rows) recoded to 'None', the same kind of assumption already made for Alcohol_Consumption. |
| `SaturatedFatDairyIntake` | str | 0 | 0.652 | Added to the form (team decision, 2026-09-24). No blanks in this column. |

### 2. Stage 1: recommended to ADD (needs your decision and a retrain) (2)

| Column | Type | Blank | Alone AUC | Why |
|---|---|---|---|---|
| `FamilyHistoryDiabetes` | int64 | 0 | 0.617 | Plausible direction (CKD rate 0.595 with vs 0.356 without). A real risk factor and easy to answer. |
| `Edema` | int64 | 0 | 0.679 | Plausible direction and rises with the stage (0.43 healthy to 0.96 in stage 5). It is a symptom of the disease, so it is downstream of it: acceptable only if the team wants symptoms in screening. |

### 3. Do NOT use (26)

| Column | Type | Blank | Alone AUC | Why |
|---|---|---|---|---|
| `Daily_Steps` | int64 | 0 | 0.585 | Tied to Physical_Activity_Level (average steps: Sedentary 2,751, Light 5,496, Moderate 8,496, Active 12,973), so it adds almost nothing. Optional at most. |
| `Sodium_Intake_mg` | int64 | 0 | 0.531 | Exact milligrams of sodium or grams of protein per kilogram cannot be answered reliably by a person without a food diary. (Protein also has a non-monotonic pattern.) |
| `Stress_Level` | str | 0 | 0.503 | No signal (AUC 0.503 and 0.519). |
| `Number_of_Medications` | int64 | 0 | 0.779 | A count that equals the sum of the six medicine answers in 79.6% of the rows (correlation 0.94). It is derived from questions already asked; using it as well would count the medicines twice. |
| `Annual_Checkups` | int64 | 0 | 0.628 | The CKD rate RISES with every check-up (0: 0.351 up to 5: 0.795), the reverse of prevention: sick people get more check-ups. |
| `DietQuality` | float | 0 | 0.675 | 63,717 rows (15.9%) hold the SAME placeholder value in all five columns, and among the 202,948 healthy rows there are only 41,420 different combinations of the five. The patterns are medically implausible (Itching is higher in healthy people, 4.22, than in CKD, 2.47; Fatigue falls to 1.17 in stage 5). Adding them would raise the AUC to 0.993 by learning these artefacts. |
| `FamilyHistoryKidneyDisease` | int64 | 0 | 0.515 | Identical to Family_History_CKD in 100% of the rows. A duplicate, not a new factor. |
| `FamilyHistoryHypertension` | int64 | 0 | 0.550 | The direction is the opposite of what is expected (0.439 with vs 0.540 without), and its numbers match PreviousAcuteKidneyInjury's. |
| `PreviousAcuteKidneyInjury` | int64 | 0 | 0.551 | The direction is the OPPOSITE of medical knowledge: CKD rate 0.439 with a previous kidney injury vs 0.540 without. The 'What lowered your estimate' card would tell a person that a past kidney injury lowered their estimate. |
| `FatigueLevels` | float | 0 | 0.694 | 63,717 rows (15.9%) hold the SAME placeholder value in all five columns, and among the 202,948 healthy rows there are only 41,420 different combinations of the five. The patterns are medically implausible (Itching is higher in healthy people, 4.22, than in CKD, 2.47; Fatigue falls to 1.17 in stage 5). Adding them would raise the AUC to 0.993 by learning these artefacts. |
| `NauseaVomiting` | float | 0 | 0.583 | 63,717 rows (15.9%) hold the SAME placeholder value in all five columns, and among the 202,948 healthy rows there are only 41,420 different combinations of the five. The patterns are medically implausible (Itching is higher in healthy people, 4.22, than in CKD, 2.47; Fatigue falls to 1.17 in stage 5). Adding them would raise the AUC to 0.993 by learning these artefacts. |
| `MuscleCramps` | float | 0 | 0.718 | 63,717 rows (15.9%) hold the SAME placeholder value in all five columns, and among the 202,948 healthy rows there are only 41,420 different combinations of the five. The patterns are medically implausible (Itching is higher in healthy people, 4.22, than in CKD, 2.47; Fatigue falls to 1.17 in stage 5). Adding them would raise the AUC to 0.993 by learning these artefacts. |
| `Itching` | float | 0 | 0.625 | 63,717 rows (15.9%) hold the SAME placeholder value in all five columns, and among the 202,948 healthy rows there are only 41,420 different combinations of the five. The patterns are medically implausible (Itching is higher in healthy people, 4.22, than in CKD, 2.47; Fatigue falls to 1.17 in stage 5). Adding them would raise the AUC to 0.993 by learning these artefacts. |
| `HeavyMetalsExposure` | int64 | 0 | 0.709 | The direction is the opposite of medical knowledge: CKD rate 0.212 with exposure vs 0.659 without, and exposure FALLS as the stage rises (0.58 healthy to 0.04 in stage 5). |
| `OccupationalExposureChemicals` | int64 | 0 | 0.552 | The direction is the opposite of medical knowledge (0.437 with exposure vs 0.541 without). |
| `FruitVegetableIntake` | str | 0 | 0.596 | U-shaped: 'Moderate' has the lowest CKD rate and 'Very High' a high one (0.610 and 0.634). Not a believable dose-response; needs the data owner's definition. |
| `ClinicianImposedFluidRestriction` | int64 | 0 | 0.545 | A consequence of known kidney or heart disease (CKD rate 0.964 when 1), so it detects people who are already under care. |
| `ProteinIntake_g_per_kg_day` | float | 0 | 0.550 | Exact milligrams of sodium or grams of protein per kilogram cannot be answered reliably by a person without a food diary. (Protein also has a non-monotonic pattern.) |
| `FibreWholegrainIntake` | str | 0 | 0.591 | U-shaped: 'Moderate' has the lowest CKD rate and 'Very High' a high one (0.610 and 0.634). Not a believable dose-response; needs the data owner's definition. |
| `CaffeineTeaCoffeeIntake` | str | 0 | 0.519 | No signal (AUC 0.503 and 0.519). |
| `PolycysticKidneyDisease` | int64 | 0 | 0.500 | The value is 0 in all 400,000 rows. A model cannot learn from a column that never changes, and asking about it would be meaningless. |
| `StructuralKidneyAbnormality` | int64 | 0 | 0.500 | The value is 0 in all 400,000 rows. A model cannot learn from a column that never changes, and asking about it would be meaningless. |
| `ProlongedUrinaryObstruction` | int64 | 0 | 0.500 | The value is 0 in all 400,000 rows. A model cannot learn from a column that never changes, and asking about it would be meaningless. |
| `LiverDisease` | int64 | 0 | 0.500 | The value is 0 in all 400,000 rows. A model cannot learn from a column that never changes, and asking about it would be meaningless. |
| `Gluta drip` | int64 | 0 | 0.500 | No relation to CKD (rate 0.49 for every value 0 to 3), the meaning of 0 to 3 is not given, and it is sensitive personal information. |
| `Gender Affirming Hormone Theraphy(hormonal pills)` | int64 | 0 | 0.500 | No relation to CKD (rate 0.49 for every value), the meaning of 0 to 3 is not given, the name has a typo, and it is sensitive personal information. It must not be asked. |

### 4. Stage 2 (laboratory / clinical) (23)

| Column | Type | Blank | Alone AUC | Why |
|---|---|---|---|---|
| `Systolic_BP` | int64 | 0 | 0.832 | Measured with a device. Strong (AUC 0.832 and 0.799). Could be a home reading; the team must decide if a home reading is acceptable in Stage 1. |
| `Diastolic_BP` | int64 | 0 | 0.799 | Measured with a device. Strong (AUC 0.832 and 0.799). Could be a home reading; the team must decide if a home reading is acceptable in Stage 1. |
| `Blood_Pressure_Category` | str | 0 | 0.811 | Worked out from the two readings above. Not independent of them. |
| `Serum_Creatinine` | float | 0 | 0.897 | A blood test. AUC 0.897 alone. Together with eGFR it is how kidney function is measured, so a model that uses it diagnoses more than it screens. |
| `eGFR` | float | 0 | 0.996 | AUC 0.996 alone: it is essentially the definition of CKD in this data. A model with eGFR is not a risk screening. The team must decide whether it may be used at all; my advice is no. |
| `Blood_Urea_Nitrogen` | float | 0 | 0.694 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Albumin` | float | 0 | 0.617 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Urine_ACR` | float | 52,805 | 0.827 | Urine tests used to diagnose and stage kidney damage (AUC 0.827, 0.788, 0.771). 13.2% are blank, which means 'not tested', not zero. Albuminuria_Category is derived from Urine_ACR. |
| `Albuminuria_Category` | str | 52,805 | 0.788 | Urine tests used to diagnose and stage kidney damage (AUC 0.827, 0.788, 0.771). 13.2% are blank, which means 'not tested', not zero. Albuminuria_Category is derived from Urine_ACR. |
| `Urine_Protein` | float | 52,805 | 0.771 | Urine tests used to diagnose and stage kidney damage (AUC 0.827, 0.788, 0.771). 13.2% are blank, which means 'not tested', not zero. Albuminuria_Category is derived from Urine_ACR. |
| `HbA1c` | float | 70,751 | 0.669 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Fasting_Glucose` | float | 24,640 | 0.674 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Hemoglobin` | float | 0 | 0.640 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Sodium` | float | 0 | 0.501 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Potassium` | float | 0 | 0.673 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Calcium` | float | 16,167 | 0.565 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Phosphorus` | float | 115,170 | 0.606 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Uric_Acid` | float | 0 | 0.608 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Total_Cholesterol` | int64 | 0 | 0.629 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `HDL` | float | 11,691 | 0.542 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `LDL` | float | 12,097 | 0.615 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `Triglycerides` | int64 | 0 | 0.648 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |
| `CRP` | float | 16,816 | 0.811 | A laboratory value, so Stage 2 (Enhanced Screening) after the person uploads a result. Blanks are 'not tested': Phosphorus 28.8%, HbA1c 17.7%, Fasting_Glucose 6.2%, CRP 4.2%, Calcium 4.0%, LDL 3.0%, HDL 2.9%. |

### 5. Outcome, leakage or identifier (8)

| Column | Type | Blank | Alone AUC | Why |
|---|---|---|---|---|
| `Patient_ID` | int64 | 0 |  | An identifier. It carries no information about the person. |
| `Frailty_Index` | float | 0 | 0.967 | Removed by the team's earlier decision. It also predicts CKD very strongly (AUC 0.967 and 0.839). |
| `Frailty_Category` | str | 0 | 0.839 | Removed by the team's earlier decision. It also predicts CKD very strongly (AUC 0.967 and 0.839). |
| `CKD` | int64 | 0 |  | The target itself (1 = CKD). 49.3% of the rows are 1. |
| `CKD_Stage` | str | 0 | 1.000 | The stage of the target. It predicts CKD perfectly (AUC 1.000), so it is the answer, not a predictor. |
| `Kidney_Failure_Risk` | str | 0 | 0.593 | Consequences of kidney disease. Hospitalization_Risk alone predicts CKD with AUC 0.978. |
| `Dialysis_Required` | int64 | 0 | 0.504 | Consequences of kidney disease. Hospitalization_Risk alone predicts CKD with AUC 0.978. |
| `Hospitalization_Risk` | str | 0 | 0.978 | Consequences of kidney disease. Hospitalization_Risk alone predicts CKD with AUC 0.978. |
