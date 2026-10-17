"""
Checks for services/model_service_stage2.py: loading, checking, and running the Stage 2 (Enhanced Screening) model.
Uses a stand-in model (tests/model_fixtures.build_stage2_stand_in), never the real, provided nephron_model.zip
artifact - the same reasoning as tests/test_model_service.py: this proves the PLUMBING is correct, not any
particular model's real-world accuracy. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

import model_fixtures  # noqa: E402
from services import lab_contract  # noqa: E402
from services.model_service_stage2 import STAGE1_LIKE_FIELDS, Stage2ModelService  # noqa: E402
from services.model_service import ExplanationUnavailable, ModelInputError, ModelUnavailableError  # noqa: E402

try:
    import sklearn  # noqa: F401
    LIBRARIES_AVAILABLE = True
except ImportError:
    LIBRARIES_AVAILABLE = False

NEEDS_ML = unittest.skipUnless(LIBRARIES_AVAILABLE, "needs scikit-learn, pandas, numpy and joblib (see requirements.txt)")


@NEEDS_ML
class ServiceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        cls.catalog = lab_contract.load_lab_catalog()
        cls.good = model_fixtures.build_stage2_stand_in(os.path.join(cls.root, "good"), cls.catalog)

    def service(self, directory):
        svc = Stage2ModelService(directory)
        svc.load()
        return svc

    def full_row(self, **changes):
        row = dict(self.good.metadata["reference_row"])
        row["Serum_Creatinine"] = 1.1
        row.update(changes)
        return row


class LoadingTests(ServiceCase):
    def test_a_good_model_is_ready_with_no_fatal_failures(self):
        service = self.service(self.good.directory)
        self.assertTrue(service.ready, [c for c in service.checks if not c.ok])
        self.assertTrue(all(c.ok for c in service.checks if c.fatal))

    def test_the_stage_must_say_enhanced(self):
        broken = model_fixtures.StandIn.__new__(model_fixtures.StandIn)  # not used; edit metadata file directly instead
        import json
        directory = os.path.join(self.root, "wrong-stage")
        model_fixtures.build_stage2_stand_in(directory, self.catalog)
        meta_path = os.path.join(directory, "model_metadata.json")
        with open(meta_path) as handle:
            meta = json.load(handle)
        meta["stage"] = "preliminary"
        with open(meta_path, "w") as handle:
            json.dump(meta, handle)
        service = self.service(directory)
        self.assertFalse(service.ready)
        self.assertIn("enhanced", service.reason)

    def test_a_missing_model_directory_is_refused_not_crashed(self):
        service = self.service(os.path.join(self.root, "does-not-exist"))
        self.assertFalse(service.ready)
        self.assertIn("has not been installed", service.reason)

    def test_features_must_be_exactly_the_27_stage1_fields_plus_lab_catalog_plus_egfr(self):
        import json
        directory = os.path.join(self.root, "wrong-features")
        model_fixtures.build_stage2_stand_in(directory, self.catalog)
        meta_path = os.path.join(directory, "model_metadata.json")
        with open(meta_path) as handle:
            meta = json.load(handle)
        meta["features"] = meta["features"][:-1]  # drop one
        with open(meta_path, "w") as handle:
            json.dump(meta, handle)
        service = self.service(directory)
        self.assertFalse(service.ready)
        self.assertIn("27 Stage 1 answers", service.reason)

    def test_a_tampered_file_is_refused_by_its_checksum(self):
        directory = os.path.join(self.root, "tampered")
        stand_in = model_fixtures.build_stage2_stand_in(directory, self.catalog)
        with open(stand_in.artifact_path, "ab") as handle:
            handle.write(b"\\x00")
        service = self.service(directory)
        self.assertFalse(service.ready)
        self.assertIn("SHA-256", service.reason)


class PredictTests(ServiceCase):
    def test_only_creatinine_given_the_rest_missing_still_predicts(self):
        service = self.service(self.good.directory)
        result = service.predict(self.full_row())
        self.assertIn(result["classification"], ("low", "high"))
        self.assertTrue(0 <= result["probability"] <= 1)
        self.assertEqual(result["assessment_type"], "enhanced")

    def test_worse_kidney_numbers_and_more_disease_push_the_estimate_up(self):
        service = self.service(self.good.directory)
        sicker = service.predict(self.full_row(Serum_Creatinine=3.8, Age=78, Diabetes=1, Hypertension=1))
        healthier = service.predict(self.full_row(Serum_Creatinine=0.7, Age=24, Diabetes=0, Hypertension=0))
        self.assertGreater(sicker["probability"], healthier["probability"])

    def test_giving_more_optional_lab_values_does_not_break_anything(self):
        service = self.service(self.good.directory)
        rich = self.full_row(Sodium=140, Potassium=4.0, Hemoglobin=14.0, HbA1c=5.4, Total_Cholesterol=180)
        result = service.predict(rich)
        self.assertTrue(0 <= result["probability"] <= 1)

    def test_serum_creatinine_missing_is_refused(self):
        service = self.service(self.good.directory)
        with self.assertRaisesRegex(ModelInputError, "Serum_Creatinine"):
            service.predict(self.full_row(Serum_Creatinine=None))

    def test_a_missing_stage1_like_field_is_refused_by_name(self):
        service = self.service(self.good.directory)
        row = self.full_row()
        del row["Hypertension"]
        with self.assertRaisesRegex(ModelInputError, "Hypertension"):
            service.predict(row)

    def test_every_stage1_like_field_is_required_except_alcohol_which_has_no_none_option_here(self):
        service = self.service(self.good.directory)
        for name in STAGE1_LIKE_FIELDS:
            if name == "Alcohol_Consumption":
                continue                                          # its Stage 1 "None" is translated to missing, not refused
            row = self.full_row()
            row[name] = None
            with self.assertRaises(ModelInputError, msg=name):
                service.predict(row)

    def test_an_out_of_range_lab_value_is_refused_not_clamped(self):
        service = self.service(self.good.directory)
        with self.assertRaisesRegex(ModelInputError, "Sodium"):
            service.predict(self.full_row(Sodium=9999))
        with self.assertRaisesRegex(ModelInputError, "Serum_Creatinine"):
            service.predict(self.full_row(Serum_Creatinine=-1))

    def test_alcohol_none_stage1s_does_not_drink_is_translated_to_missing_not_refused(self):
        service = self.service(self.good.directory)
        row = self.full_row(Alcohol_Consumption="None")           # Stage 1's literal answer; this model has never seen it
        result = service.predict(row)                             # must not raise: translated to missing, not rejected
        self.assertTrue(0 <= result["probability"] <= 1)

    def test_egfr_cannot_be_supplied_directly_it_is_always_computed(self):
        service = self.service(self.good.directory)
        given_egfr = service.predict(self.full_row(Serum_Creatinine=2.0))
        # even if a caller tried to sneak in a different eGFR, _check_row recomputes it from creatinine/age/sex
        sneaky = dict(self.full_row(Serum_Creatinine=2.0))
        sneaky["eGFR"] = 999
        self.assertEqual(service.predict(sneaky)["probability"], given_egfr["probability"])

    def test_the_model_cannot_be_used_before_it_is_ready(self):
        service = Stage2ModelService(os.path.join(self.root, "not-loaded-yet"))
        with self.assertRaises(ModelUnavailableError):
            service.predict(self.full_row())


class ExplainTests(ServiceCase):
    def setUp(self):
        patcher = model_fixtures.fake_xgboost()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)
        self.explainer = self.service(self.good.directory)

    def test_can_explain_when_xgboost_is_available(self):
        self.assertTrue(self.explainer.can_explain, [c for c in self.explainer.checks if "explained" in c.name])

    def test_the_explained_probability_matches_predict_exactly(self):
        row = self.full_row(Serum_Creatinine=3.2, Age=70, Diabetes=1)
        predicted = self.explainer.predict(row)
        explained = self.explainer.explain(row)
        self.assertAlmostEqual(explained["probability"], predicted["probability"], places=9)

    def test_every_one_of_the_48_inputs_gets_exactly_one_effect(self):
        result = self.explainer.explain(self.full_row())
        names = [e["name"] for e in result["effects"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(self.good.metadata["features"]))

    def test_a_missing_xgboost_only_switches_the_explanation_off(self):
        with mock.patch.dict(sys.modules, {"xgboost": None}):
            service = self.service(self.good.directory)
            self.assertTrue(service.ready)
            self.assertFalse(service.can_explain)
            with self.assertRaises(ExplanationUnavailable):
                service.explain(self.full_row())


class FactorsTests(ServiceCase):
    def test_factors_are_ranked_and_labelled_for_both_kinds_of_input(self):
        service = self.service(self.good.directory)
        factors = service.factors(limit=5)
        self.assertEqual(len(factors), 5)
        percents = [f["percent"] for f in factors]
        self.assertEqual(percents, sorted(percents, reverse=True))
        for factor in factors:
            self.assertTrue(factor["label"])                     # every factor, lab or Stage-1-like, has a real label

    def test_a_field_whose_catalog_label_differs_from_its_raw_name_uses_the_label(self):
        service = self.service(self.good.directory)
        row = self.full_row(Hypertension=1)
        result = service.explain(row) if False else None  # explain needs xgboost; use factors() instead, which does not
        from services.model_service_stage2 import _stage2_label
        self.assertEqual(_stage2_label("Hypertension"), "High blood pressure")
        self.assertEqual(_stage2_label("Serum_Creatinine"), "Serum creatinine")


class Stage2DescriberTests(unittest.TestCase):
    def setUp(self):
        from services.model_service_stage2 import stage2_describer
        self.describe = stage2_describer(lab_contract.load_lab_catalog())
        self.inputs = {"Sex": "Male", "Age": 70, "Diabetes": 1, "Serum_Creatinine": 3.2, "Sodium": 140.0}

    def test_a_stage1_like_field_is_described_from_stage_1s_own_catalog(self):
        self.assertEqual(self.describe("Diabetes", self.inputs), ("Diabetes", "Yes", "Yes"))

    def test_a_lab_field_is_described_from_the_lab_catalog(self):
        label, answer, brief = self.describe("Serum_Creatinine", self.inputs)
        self.assertEqual((label, answer, brief), ("Serum creatinine", "3.2 mg/dL", "3.2 mg/dL"))

    def test_egfr_is_computed_from_creatinine_age_and_sex_never_read_directly(self):
        label, answer, brief = self.describe("eGFR", self.inputs)
        self.assertEqual(label, "eGFR")
        self.assertIn("mL/min/1.73m", answer)
        self.assertEqual(answer, brief)

    def test_egfr_is_none_when_creatinine_was_not_given(self):
        self.assertIsNone(self.describe("eGFR", {"Sex": "Male", "Age": 70}))

    def test_a_lab_field_that_was_not_given_is_none_not_guessed(self):
        self.assertIsNone(self.describe("Potassium", self.inputs))

    def test_an_unrecognised_name_is_none(self):
        self.assertIsNone(self.describe("Not_A_Real_Field", self.inputs))


if __name__ == "__main__":
    unittest.main()
