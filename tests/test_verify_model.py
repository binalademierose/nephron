"""
Checks for verify_model.py, the command a person runs to find out whether Nephron will accept their saved model.
It uses the stand-in model of tests/model_fixtures.py (not Nephron's model). Needs scikit-learn, pandas, numpy and joblib.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_fixtures  # noqa: E402

from services import screening_contract  # noqa: E402

NEEDS_ML = unittest.skipUnless(model_fixtures.libraries_available(), "needs scikit-learn, pandas, numpy and joblib (see requirements.txt)")


def run(*arguments):
    import verify_model
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["verify_model.py", *arguments]), contextlib.redirect_stdout(out):
        code = verify_model.main()
    return code, out.getvalue()


@NEEDS_ML
class VerifyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        import pandas as pd
        cls.catalog = screening_contract.load_catalog()
        cls.root = tempfile.mkdtemp()
        cls.good = model_fixtures.build_stand_in(os.path.join(cls.root, "good"), cls.catalog)
        rng = np.random.default_rng(99)
        data = model_fixtures.random_answers(cls.catalog, rng, 1500)
        frame = pd.DataFrame(data)
        score = 0.04 * (frame["Age"] - 50) + 0.9 * frame["Diabetes"] + 0.8 * frame["Hypertension"] + 0.6 * frame["Family_History_CKD"] + 0.03 * (frame["BMI"] - 27) - 0.9
        frame["Diagnosis"] = (rng.random(len(frame)) < 1 / (1 + np.exp(-score))).astype(int)
        cls.csv = os.path.join(cls.root, "held_out.csv")
        frame.to_csv(cls.csv, index=False)            # writes the text None for a person who does not drink

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @staticmethod
    def read_meta(folder):
        with open(os.path.join(folder, "model_metadata.json"), encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def write_meta(folder, meta):
        with open(os.path.join(folder, "model_metadata.json"), "w", encoding="utf-8") as handle:
            json.dump(meta, handle)

    def copy(self):
        target = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)
        shutil.copytree(self.good.directory, target, dirs_exist_ok=True)
        return target

    def test_a_good_model_is_accepted_and_the_report_says_so(self):
        code, text = run("--model-dir", self.good.directory)
        self.assertEqual(code, 0)
        self.assertIn("ACCEPTED", text)
        self.assertIn("Rule: a probability at or above the threshold is High Preliminary Risk", text)
        self.assertNotIn("[FAIL]", text)

    def test_no_model_is_reported_as_not_accepted(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        code, text = run("--model-dir", empty)
        self.assertEqual(code, 1)
        self.assertIn("NOT ACCEPTED", text)
        self.assertIn("No model has been installed", text)

    def test_the_report_explains_a_mismatch_in_plain_words(self):
        folder = self.copy()
        meta = self.read_meta(folder)
        meta["library_versions"]["scikit-learn"] = "0.0.1"
        self.write_meta(folder, meta)
        code, text = run("--model-dir", folder)
        self.assertEqual(code, 1)
        self.assertIn("pip install", text)

    def test_the_threshold_of_this_model_is_confirmed_on_held_out_data(self):
        code, text = run("--model-dir", self.good.directory, "--validation-csv", self.csv, "--target", "Diagnosis")
        self.assertEqual(code, 0, text)
        self.assertIn("consistent with this model", text)
        self.assertIn("ROC-AUC", text)

    def test_the_websites_way_of_asking_the_model_gives_the_same_answers_as_the_pipeline(self):
        code, text = run("--model-dir", self.good.directory, "--validation-csv", self.csv, "--target", "Diagnosis")
        self.assertEqual(code, 0, text)
        self.assertIn("Website path against the pipeline used directly", text)
        self.assertIn("exactly the same answers as the pipeline", text)
        self.assertRegex(text, r"Compared: [1-9]\d* rows")

    def test_a_difference_between_the_websites_path_and_the_pipeline_is_caught(self):
        from services.model_service import ModelService
        real = ModelService.predict

        def wrong(self, values, _checking=False):
            answer = real(self, values, _checking=_checking)
            return dict(answer, probability=1 - answer["probability"])       # a website that reads the wrong probability column

        with mock.patch.object(ModelService, "predict", wrong):
            code, text = run("--model-dir", self.good.directory, "--validation-csv", self.csv, "--target", "Diagnosis")
        self.assertEqual(code, 1, text)
        self.assertIn("DIFFERENT answers", text)

    def test_rows_the_form_could_never_send_are_counted_and_left_out_not_hidden(self):
        import pandas as pd
        frame = pd.read_csv(self.csv, keep_default_na=False)
        frame.loc[:40, "Water_Intake_L"] = 40.3                                   # above the form's realistic limit of 10
        path = os.path.join(self.root, "over_limit.csv")
        frame.to_csv(path, index=False)
        code, text = run("--model-dir", self.good.directory, "--validation-csv", path, "--target", "Diagnosis")
        self.assertEqual(code, 0, text)
        self.assertRegex(text, r"Refused by the website's own checks \(not answers the form can send\): [1-9]\d*")

    def test_a_threshold_that_belongs_to_another_model_is_caught(self):
        # This is the exact mistake of the earlier notebook: another model's threshold saved beside this model.
        folder = self.copy()
        meta = self.read_meta(folder)
        meta["threshold"] = 0.05 if meta["threshold"] > 0.3 else 0.95
        self.write_meta(folder, meta)
        code, text = run("--model-dir", folder, "--validation-csv", self.csv, "--target", "Diagnosis")
        self.assertEqual(code, 1, text)
        self.assertIn("does NOT look like this model's", text)

    def test_the_word_none_in_the_data_is_a_real_answer_and_not_a_missing_value(self):
        import pandas as pd
        with open(self.csv, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertIn(",None,", raw)                                              # the file really contains the text None
        code, text = run("--model-dir", self.good.directory, "--validation-csv", self.csv, "--target", "Diagnosis")
        self.assertEqual(code, 0, text)
        self.assertEqual(int(pd.read_csv(self.csv)["Alcohol_Consumption"].isna().sum()) > 0, True)     # pandas' default WOULD have lost them

    def test_a_validation_file_with_missing_columns_or_no_positive_rows_is_reported(self):
        import pandas as pd
        frame = pd.read_csv(self.csv, keep_default_na=False).drop(columns=["Age"])
        path = os.path.join(self.root, "no_age.csv")
        frame.to_csv(path, index=False)
        code, text = run("--model-dir", self.good.directory, "--validation-csv", path, "--target", "Diagnosis")
        self.assertEqual((code, "lacks these columns: Age" in text), (2, True))
        code, text = run("--model-dir", self.good.directory, "--validation-csv", self.csv)
        self.assertEqual(code, 2)                                                  # --target is required
        code, text = run("--model-dir", self.good.directory, "--validation-csv", self.csv, "--target", "Country")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
