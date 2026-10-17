"""
Checks the training notebook (ml/notebooks/CKD_Stage1_Modeling.ipynb) WITHOUT running it.

Running it needs XGBoost and a few minutes, so these are quick static checks that keep the notebook and the website in step:
the notebook must be valid, it must write every field the website requires, it must read the same questions the form asks, and it
must keep the safeguards that stop the pipeline from guessing. Run everything with:   python -m unittest discover -s tests -v
"""
import ast
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

from services import model_service  # noqa: E402

NOTEBOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "notebooks", "CKD_Stage1_Modeling.ipynb")


class NotebookContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(NOTEBOOK, encoding="utf-8") as handle:
            cls.notebook = json.load(handle)
        cls.code_cells = ["".join(c["source"]) for c in cls.notebook["cells"] if c["cell_type"] == "code"]
        cls.code = "\n".join(cls.code_cells)
        cls.text = "\n".join("".join(c["source"]) for c in cls.notebook["cells"])

    def test_it_is_a_valid_notebook(self):
        # Running the notebook in Jupyter saves its output and execution counts into the file. That is fine and useful
        # (it is the evidence for the panel), so only the structure is checked here.
        self.assertEqual(self.notebook["nbformat"], 4)
        self.assertGreater(len(self.code_cells), 15)
        for cell in self.notebook["cells"]:
            self.assertIn(cell["cell_type"], ("code", "markdown"))

    def test_every_code_cell_is_valid_python_and_uses_no_notebook_magic(self):
        for index, source in enumerate(self.code_cells):
            ast.parse(source, filename=f"cell {index}")
            self.assertFalse(re.search(r"^\s*[%!]", source, re.M), f"cell {index} uses a notebook magic or shell command")

    def test_it_writes_every_field_the_website_requires(self):
        for key in model_service.REQUIRED_METADATA_KEYS:
            self.assertIn(f'"{key}"', self.code, f"the notebook never writes '{key}' into model_metadata.json")
        self.assertIn('"stage": "preliminary"', self.code)
        self.assertIn('"schema_version": 1', self.code)

    def test_it_writes_where_the_website_looks_and_under_the_names_the_website_expects(self):
        self.assertIn('MODEL_DIR = PROJECT_DIR / "ml" / "model"', self.code)
        self.assertIn(model_service.METADATA_FILE, self.code)
        self.assertRegex(self.code, r'FILE_NAME = "[A-Za-z0-9._-]+\.(joblib|pkl|pickle)"')
        self.assertIn("joblib.dump(", self.code)

    def test_the_questions_come_from_the_catalog_and_the_notebook_stops_if_the_data_disagrees(self):
        self.assertIn("feature_catalog.json", self.code)
        self.assertIn('FEATURES = [q["name"] for q in QUESTIONS]', self.code)
        self.assertIn("The catalog and the dataset disagree", self.code)
        self.assertIn("(raw[\"BMI\"] >= 30)", self.code)                          # Obesity is derived from the BMI, as the form does

    def test_the_safeguards_against_guessing_are_present(self):
        self.assertIn('handle_unknown="error"', self.code)                       # an unseen answer is refused by the pipeline itself
        self.assertNotIn("SimpleImputer", self.code)                             # a missing answer is never filled in
        self.assertNotIn("handle_unknown=\"ignore\"", self.code)
        self.assertIn("keep_default_na=False", self.code)                        # the word None is a real answer
        self.assertIn('recode_blank("Alcohol_Consumption", "does not drink", "None")', self.code)  # blank alcohol is made explicit, not guessed
        self.assertIn('recode_blank("SugaryDrinksAddedSugar", "no sugar-sweetened drinks", "None")', self.code)
        self.assertIn('recode_blank("UltraProcessedFoodFrequency", "never eats ultra-processed food", "Never")', self.code)
        self.assertIn("classes.index(HIGH_RISK_CLASS)", self.code)               # the high-risk column is found by label

    def test_the_threshold_is_computed_from_the_saved_model_on_data_it_did_not_train_on(self):
        self.assertIn("youden(y_val, p_high_val)", self.code)
        self.assertIn("high_probability(xgb_final, X_val)", self.code)
        self.assertNotRegex(self.code, r"joblib\.dump\((rf_final|rf_pipeline)")  # only the XGBoost model is ever saved
        self.assertIn('assert type(model).__name__ == "XGBClassifier"', self.code)

    def test_it_uses_only_the_two_agreed_algorithms_and_no_laboratory_value_or_frailty(self):
        self.assertIn("RandomForestClassifier", self.code)
        self.assertIn("XGBClassifier", self.code)
        for other in ("LogisticRegression", "SVC(", "KNeighbors", "LGBM", "CatBoost", "MLPClassifier"):
            self.assertNotIn(other, self.code)
        self.assertIn("assert not (set(FEATURES) & banned)", self.code)
        for lab in ("eGFR", "Serum_Creatinine", "Frailty_Index"):
            self.assertIn(f'"{lab}"', self.code)                                 # named in the exclusion audit
        self.assertNotIn("FEATURES = [", self.code.replace('FEATURES = [q["name"] for q in QUESTIONS]', ""))

    def test_the_saved_model_is_isotonic_calibrated_and_the_threshold_uses_the_calibrated_probability(self):
        self.assertIn('CalibratedClassifierCV(clone(xgb_pipeline)', self.code)
        self.assertIn('method="isotonic"', self.code)
        self.assertIn("ensemble=False", self.code)
        self.assertIn("xgb_calibrated.fit(X_train, y_train)", self.code)
        self.assertIn("joblib.dump(xgb_calibrated, artifact_path)", self.code)
        self.assertNotIn("joblib.dump(xgb_final, artifact_path)", self.code)        # the uncalibrated pipeline is never the saved one
        self.assertIn("high_probability(xgb_calibrated, X_val)", self.code)         # the threshold is Youden's J on the CALIBRATED probability
        self.assertIn('"calibration": {"method": "isotonic"', self.code)
        # the saved model_name still names the family (XGBoost), the calibration wrapper is recorded separately
        self.assertIn('"model_name": "XGBoost"', self.code)

    def test_the_test_set_is_kept_apart_from_the_threshold_and_the_search(self):
        self.assertIn("X_test", self.code)
        self.assertNotRegex(self.code, r"youden\(y_test")                        # the threshold is never chosen on the test set
        self.assertNotRegex(self.code, r"\.fit\(X_test|\.fit\(X_val")            # nothing is trained on validation or test rows

    def test_the_checks_look_at_the_whole_file_and_a_quick_trial_is_labelled_so_it_cannot_pass_for_the_real_model(self):
        load_cell = next(c for c in self.code_cells if "pd.read_csv(" in c)
        self.assertNotIn("SAMPLE_ROWS_FOR_A_QUICK_TRIAL", load_cell)              # the catalog-vs-data check must not see a sample
        split_cell = next(c for c in self.code_cells if "train_test_split(X, y" in c)
        self.assertIn("SAMPLE_ROWS_FOR_A_QUICK_TRIAL", split_cell)
        self.assertIn("-QUICKTRIAL", self.code)
        self.assertIn('"quick_trial"', self.code)

    def test_the_notebook_tells_the_reader_the_honest_limits_of_the_data(self):
        for phrase in ("synthetic", "about half", "Country", "blank"):
            self.assertIn(phrase, self.text)

    def test_the_settings_point_to_the_students_project_and_the_new_dataset(self):
        self.assertIn(r'D:\4ADA\NEPHRON_DEVELOPMENT\SYSTEM_DEV', self.code)
        self.assertIn("CKD_400k.csv", self.code)


if __name__ == "__main__":
    unittest.main()
