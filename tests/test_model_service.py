"""
Checks for services/model_service.py: the strict verification of the saved model, prediction, and feature importance.

They use a STAND-IN model built by tests/model_fixtures.py (a small scikit-learn pipeline trained on random answers).
It is not Nephron's model. It has the same shape, so these tests prove that the loading and the checks work, and that
the service REFUSES a model (or an answer) it should refuse. They need scikit-learn, pandas, numpy and joblib;
without them these tests are skipped and say so.
"""
import copy
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_fixtures  # noqa: E402

from services import model_service, screening_contract as contract  # noqa: E402
from services.model_service import ExplanationUnavailable, ModelInputError, ModelService, ModelUnavailableError  # noqa: E402

NEEDS_ML = unittest.skipUnless(model_fixtures.libraries_available(), "needs scikit-learn, pandas, numpy and joblib (see requirements.txt)")


@NEEDS_ML
class ServiceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = contract.load_catalog()
        cls.root = tempfile.mkdtemp()
        cls.base = model_fixtures.build_stand_in(os.path.join(cls.root, "base"), cls.catalog)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def folder(self):
        """A private copy of the good model folder that a test may damage."""
        target = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)
        shutil.copytree(self.base.directory, target, dirs_exist_ok=True)
        return target

    def read_meta(self, folder):
        with open(os.path.join(folder, "model_metadata.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def write_meta(self, folder, meta):
        with open(os.path.join(folder, "model_metadata.json"), "w", encoding="utf-8") as handle:
            json.dump(meta, handle)

    def service(self, folder, catalog=None):
        service = ModelService(folder, catalog or self.catalog)
        service.load()
        return service

    def assertRefused(self, service, *words):
        self.assertFalse(service.ready, "the model should have been refused")
        for word in words:
            self.assertIn(word, service.reason)
        with self.assertRaises(ModelUnavailableError):
            service.predict(contract.reference_row(self.catalog))
        self.assertEqual(service.factors(), [])


class HappyPathTests(ServiceCase):
    def test_a_good_model_is_accepted_after_every_check(self):
        service = self.service(self.base.directory)
        self.assertTrue(service.ready, service.reason)
        self.assertIsNone(service.reason)
        self.assertTrue(all(c.ok for c in service.checks if c.fatal))
        self.assertEqual(service.version, "stand-in-test-1")
        self.assertGreater(len(service.checks), 20)

    def test_the_result_is_exactly_what_the_pipeline_itself_gives(self):
        import numpy as np
        import pandas as pd
        service = self.service(self.base.directory)
        rows = model_fixtures.random_answers(self.catalog, np.random.default_rng(7), 30)
        features = service.metadata["features"]
        frame = pd.DataFrame({name: rows[name] for name in features})
        expected = self.base.pipeline.predict_proba(frame)[:, 1]
        for index in range(30):
            answer = service.predict({name: rows[name][index] for name in features})
            self.assertAlmostEqual(answer["probability"], float(expected[index]), places=12)
            self.assertEqual(answer["classification"], "high" if expected[index] >= service.threshold else "low")

    def test_the_high_risk_probability_is_found_by_class_label_not_by_position(self):
        import pandas as pd
        folder = os.path.join(self.root, "labels")
        stand_in = model_fixtures.build_stand_in(folder, self.catalog, labels=("low", "high"))
        self.assertEqual(list(stand_in.pipeline.steps[-1][1].classes_), ["high", "low"])       # 'high' is column 0
        service = self.service(folder)
        self.assertTrue(service.ready, service.reason)
        row = contract.reference_row(self.catalog)
        frame = pd.DataFrame({name: [row[name]] for name in service.metadata["features"]})
        for name in frame:
            if isinstance(row[name], str):
                frame[name] = frame[name].astype(object)
        self.assertAlmostEqual(service.predict(row)["probability"], float(stand_in.pipeline.predict_proba(frame)[0][0]), places=12)

    def test_the_threshold_comes_from_the_metadata_and_the_boundary_counts_as_high(self):
        folder = self.folder()
        probability = self.service(folder).predict(contract.reference_row(self.catalog))["probability"]
        meta = self.read_meta(folder)
        for threshold, expected in ((probability, "high"), (math.nextafter(probability, 1), "low"), (math.nextafter(probability, 0), "high")):
            meta["threshold"] = threshold
            self.write_meta(folder, meta)
            answer = self.service(folder).predict(contract.reference_row(self.catalog))
            self.assertEqual((answer["classification"], answer["threshold"]), (expected, threshold))

    def test_an_artifact_saved_as_a_dict_with_a_pipeline_key_is_accepted(self):
        folder = os.path.join(self.root, "dict")
        model_fixtures.build_stand_in(folder, self.catalog, artifact_as_dict=True, artifact_name="final_model.pkl")
        self.assertTrue(self.service(folder).ready)

    def test_a_different_input_order_than_the_catalog_is_fine_when_the_metadata_states_it(self):
        service = self.service(self.base.directory)
        self.assertNotEqual(service.metadata["features"], contract.feature_names(self.catalog))     # the fixture trains in reverse order
        self.assertTrue(service.ready)

    def test_the_metadata_can_be_read_back_for_the_result_page(self):
        service = self.service(self.base.directory)
        answer = service.predict(contract.reference_row(self.catalog))
        self.assertEqual((answer["model_version"], answer["assessment_type"]), ("stand-in-test-1", "preliminary"))
        self.assertTrue(0 <= answer["probability"] <= 1)


class FactorTests(ServiceCase):
    def test_factors_are_ranked_relative_to_the_strongest_and_use_the_form_words(self):
        service = self.service(self.base.directory)
        factors = service.factors(limit=28)
        self.assertEqual(len(factors), 28)
        self.assertEqual(factors[0]["share"], 100)
        self.assertEqual([f["share"] for f in factors], sorted((f["share"] for f in factors), reverse=True))
        self.assertAlmostEqual(sum(f["percent"] for f in factors), 100, delta=1.5)
        self.assertEqual(factors[0]["label"], contract.question_for(self.catalog, factors[0]["name"])["short"])
        self.assertEqual(len(service.factors()), 5)

    def test_encoded_columns_are_added_up_per_question_and_similar_names_are_not_mixed_up(self):
        service = self.service(self.base.directory)
        importance = service._importance
        self.assertEqual(set(importance), set(contract.feature_names(self.catalog)))
        self.assertIn("Diabetes", importance)
        self.assertIn("Diabetes_Medication", importance)
        # Compare with the raw importances: Country has 5 encoded columns, their sum is Country's importance.
        pipeline = self.base.pipeline
        names = list(pipeline[:-1].get_feature_names_out())
        raw = pipeline.steps[-1][1].feature_importances_
        country = sum(v for n, v in zip(names, raw) if n.startswith("categorical__Country_"))
        self.assertAlmostEqual(importance["Country"], country, places=12)
        medicine = sum(v for n, v in zip(names, raw) if n == "numeric__Diabetes_Medication")
        self.assertAlmostEqual(importance["Diabetes_Medication"], medicine, places=12)


class ExplainTests(ServiceCase):
    """
    Explaining ONE result. The additive stand-in has exactly known effects (weight * (value - column mean)), so the right
    answers are known. A fake xgboost.DMatrix stands in for the real one (which is not needed to test the logic).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.additive = model_fixtures.build_stand_in(os.path.join(cls.root, "additive"), cls.catalog, estimator="additive")
        cls.labelled = model_fixtures.build_stand_in(os.path.join(cls.root, "additive-labels"), cls.catalog, estimator="additive", labels=("low", "high"))

    def setUp(self):
        patcher = model_fixtures.fake_xgboost()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)
        model_fixtures.FakeBooster.offset = 0.0
        self.addCleanup(setattr, model_fixtures.FakeBooster, "offset", 0.0)
        self.explainer = self.service(self.additive.directory)
        self.row = dict(contract.reference_row(self.catalog), Age=78, Diabetes=1, Hypertension=1, Diabetes_Medication=0, Country="India",
                        Physical_Activity_Level="Active")

    def effects(self, result):
        return {e["name"]: e["effect"] for e in result["effects"]}

    def test_a_model_that_can_explain_says_so_and_still_screens(self):
        self.assertTrue(self.explainer.ready, self.explainer.reason)
        self.assertTrue(self.explainer.can_explain)
        check = next(c for c in self.explainer.checks if "explained" in c.name)
        self.assertTrue(check.ok)
        self.assertFalse(check.fatal)                                         # explaining is never needed to screen

    def test_every_question_gets_an_effect_strongest_first(self):
        result = self.explainer.explain(self.row)
        self.assertEqual(set(self.effects(result)), set(contract.feature_names(self.catalog)))
        sizes = [abs(e["effect"]) for e in result["effects"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(result["effects"][0]["label"], contract.question_for(self.catalog, result["effects"][0]["name"])["short"])

    def test_the_probability_is_the_one_the_model_gives_for_that_person(self):
        result = self.explainer.explain(self.row)
        self.assertAlmostEqual(result["probability"], self.explainer.predict(self.row)["probability"], places=9)

    def test_each_effect_is_exactly_what_the_model_computes_and_similar_names_are_not_mixed_up(self):
        import numpy as np
        pipeline = self.additive.pipeline
        estimator = pipeline.steps[-1][1]
        features = self.explainer.metadata["features"]
        frame = self.explainer._frame(self.row, features)
        encoded = np.asarray(pipeline[:-1].transform(frame), dtype=float)[0]
        names = list(pipeline[:-1].get_feature_names_out())
        exact = estimator.weights_ * (encoded - estimator.means_)                    # the true contribution of every encoded column
        result = self.effects(self.explainer.explain(self.row))
        column = lambda name: names.index(name)
        self.assertAlmostEqual(result["Age"], exact[column("numeric__Age")], places=9)
        self.assertAlmostEqual(result["Diabetes"], exact[column("numeric__Diabetes")], places=9)                 # not Diabetes_Medication
        self.assertAlmostEqual(result["Diabetes_Medication"], exact[column("numeric__Diabetes_Medication")], places=9)
        self.assertNotAlmostEqual(result["Diabetes"], result["Diabetes_Medication"], places=6)
        for question in ("Country", "Physical_Activity_Level"):                                                      # several columns, added together
            parts = [exact[i] for i, n in enumerate(names) if n.startswith(f"categorical__{question}_")]
            self.assertGreater(len(parts), 1)
            self.assertAlmostEqual(result[question], sum(parts), places=9)

    def test_an_older_person_is_pushed_up_and_a_younger_one_down_by_age(self):
        old = self.explainer.explain(dict(self.row, Age=88))
        young = self.explainer.explain(dict(self.row, Age=22))
        self.assertGreater(self.effects(old)["Age"], 0)
        self.assertLess(self.effects(young)["Age"], 0)
        self.assertGreater(old["probability"], young["probability"])

    def test_the_direction_is_towards_the_high_risk_class_even_when_it_is_the_first_class(self):
        # With labels low/high scikit-learn orders the classes ['high', 'low'], and XGBoost-style contributions are for the SECOND class.
        service = self.service(self.labelled.directory)
        self.assertTrue(service.can_explain, [c for c in service.checks if not c.ok])
        old = service.explain(dict(self.row, Age=88))
        young = service.explain(dict(self.row, Age=22))
        self.assertGreater(self.effects(old)["Age"], 0)                      # older raises the estimate of HIGH risk
        self.assertLess(self.effects(young)["Age"], 0)
        self.assertGreater(old["probability"], young["probability"])
        self.assertAlmostEqual(old["probability"], service.predict(dict(self.row, Age=88))["probability"], places=9)

    def test_contributions_that_do_not_add_up_are_refused_and_never_shown(self):
        model_fixtures.FakeBooster.offset = 0.5
        service = self.service(self.additive.directory)
        self.assertTrue(service.ready)                                       # screening still works
        self.assertFalse(service.can_explain)
        warning = next(c for c in service.checks if "explained" in c.name)
        self.assertFalse(warning.ok)
        self.assertFalse(warning.fatal)
        with self.assertRaisesRegex(ExplanationUnavailable, "add up"):
            service.explain(self.row)
        self.assertEqual(service.predict(self.row)["classification"] in ("high", "low"), True)

    def test_an_unexpected_shape_from_the_booster_is_refused(self):
        with mock.patch.object(model_fixtures.FakeBooster, "predict", return_value=__import__("numpy").zeros((1, 3))):
            with self.assertRaisesRegex(ExplanationUnavailable, "shape"):
                self.explainer.explain(self.row)

    def test_a_missing_xgboost_only_switches_the_explanation_off(self):
        with model_fixtures.no_xgboost():
            service = self.service(self.additive.directory)
            self.assertTrue(service.ready)
            self.assertFalse(service.can_explain)
            with self.assertRaises(ExplanationUnavailable):
                service.explain(self.row)

    def test_a_model_that_is_not_xgboost_screens_but_cannot_explain(self):
        service = self.service(self.base.directory)                          # the ordinary gradient-boosting stand-in
        self.assertTrue(service.ready)
        self.assertFalse(service.can_explain)
        with self.assertRaisesRegex(ExplanationUnavailable, "XGBoost"):
            service.explain(self.row)

    def test_it_refuses_answers_just_like_predict_does(self):
        for bad in ({k: v for k, v in self.row.items() if k != "Age"}, dict(self.row, Country="Atlantis"), dict(self.row, Age=200),
                    dict(self.row, Diabetes=None), dict(self.row, eGFR=45)):
            with self.assertRaises(ModelInputError):
                self.explainer.explain(bad)
        with self.assertRaises(ModelUnavailableError):
            self.service(tempfile.mkdtemp()).explain(self.row)

    def test_explaining_never_trains_anything(self):
        from sklearn.pipeline import Pipeline
        with mock.patch.object(model_fixtures.AdditiveClassifier, "fit", side_effect=AssertionError("trained!")), \
             mock.patch.object(Pipeline, "fit", side_effect=AssertionError("trained!")):
            self.explainer.explain(self.row)


class CalibratedModelTests(ServiceCase):
    """
    The real project's model is CalibratedClassifierCV(isotonic, ensemble=False) wrapping Pipeline[ColumnTransformer -> XGBoost]
    (see _decompose in model_service.py), not a bare Pipeline. Every check, predict(), and explain() must work the same
    way for this shape, and explain()'s honesty check must be against the CALIBRATED probability, not the raw one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calibrated = model_fixtures.build_stand_in(os.path.join(cls.root, "calibrated"), cls.catalog, estimator="additive", calibrated=True)
        cls.ensemble = model_fixtures.build_stand_in(os.path.join(cls.root, "calibrated-ensemble"), cls.catalog, estimator="additive", calibrated="ensemble")

    def setUp(self):
        patcher = model_fixtures.fake_xgboost()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)
        self.row = dict(contract.reference_row(self.catalog), Age=78, Diabetes=1, Hypertension=1)

    def test_a_calibrated_model_loads_and_every_check_passes(self):
        from services.model_service import _decompose
        service = self.service(self.calibrated.directory)
        self.assertTrue(service.ready, [c for c in service.checks if not c.ok])
        self.assertTrue(all(c.ok for c in service.checks))
        # and it really is calibrated, not accidentally unwrapped to something plain
        transform, estimator, calibrator = _decompose(service._pipeline)
        self.assertIsNotNone(calibrator)
        self.assertTrue(hasattr(estimator, "get_booster"))

    def test_predict_uses_the_calibrated_probability_not_the_raw_one(self):
        service = self.service(self.calibrated.directory)
        calibrated_answer = service.predict(self.row)
        transform, estimator, calibrator = __import__("services.model_service", fromlist=["_decompose"])._decompose(service._pipeline)
        frame = service._frame(self.row, service.metadata["features"])
        raw_probability = estimator.predict_proba(transform.transform(frame))[0, list(estimator.classes_).index(1) if 1 in estimator.classes_ else 1]
        # the two probabilities need not be close at all - isotonic recalibration can move them substantially - but they
        # must both be valid, and predict() must be the one applying calibration (this asserts they are not literally equal
        # by coincidence, i.e. that calibration is actually being applied and not silently skipped)
        self.assertNotAlmostEqual(calibrated_answer["probability"], float(raw_probability), places=3)

    def test_can_explain_and_the_explained_probability_matches_predict_exactly(self):
        service = self.service(self.calibrated.directory)
        self.assertTrue(service.can_explain, [c for c in service.checks if "explained" in c.name])
        predicted = service.predict(self.row)
        explained = service.explain(self.row)
        self.assertAlmostEqual(explained["probability"], predicted["probability"], places=9)

    def test_direction_still_makes_sense_after_calibration(self):
        service = self.service(self.calibrated.directory)
        old = service.explain(dict(self.row, Age=88))
        young = service.explain(dict(self.row, Age=22))
        effect = lambda result, name: next(e["effect"] for e in result["effects"] if e["name"] == name)
        self.assertGreater(effect(old, "Age"), 0)
        self.assertLess(effect(young, "Age"), 0)
        self.assertGreater(old["probability"], young["probability"])

    def test_every_effect_still_belongs_to_the_right_question(self):
        service = self.service(self.calibrated.directory)
        result = service.explain(self.row)
        names = {e["name"] for e in result["effects"]}
        self.assertEqual(names, set(contract.feature_names(self.catalog)))

    def test_a_broken_booster_is_still_caught_after_the_calibration_step(self):
        # Same idea as the uncalibrated test above (offsetting the booster's own contributions away from what
        # predict_proba() actually computes), now with a calibration curve in between: the booster's contributions
        # are wrong BEFORE calibration is even applied, so the honest add-up check (against predict()'s real,
        # calibrated answer) must still catch it, not just pass by coincidence.
        from services.model_service import ExplanationUnavailable
        model_fixtures.FakeBooster.offset = 0.5
        self.addCleanup(setattr, model_fixtures.FakeBooster, "offset", 0.0)
        service = self.service(self.calibrated.directory)
        self.assertTrue(service.ready)                                       # screening still works
        self.assertFalse(service.can_explain)
        with self.assertRaisesRegex(ExplanationUnavailable, "add up"):
            service.explain(self.row)

    def test_ensemble_true_cannot_be_proven_and_is_refused_entirely_not_partially(self):
        # ensemble=True averages several differently-trained folds: there is no single fold whose encoder categories
        # are provably the form's own, so this is refused the same honest way an unreadable pipeline always is -
        # not specially made to half-work. The real project uses ensemble=False (see model_card.json); this is only
        # here to prove a configuration the service cannot verify is refused outright, never partially trusted.
        service = self.service(self.ensemble.directory)
        self.assertFalse(service.ready)
        self.assertFalse(service.can_explain)
        self.assertIn("encoders could not be inspected", service.reason)


class RefusalTests(ServiceCase):
    def test_no_model_installed_yet(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertRefused(self.service(empty), "No model has been installed", "model_metadata.json")
        self.assertRefused(self.service(os.path.join(empty, "does-not-exist")), "No model has been installed")

    def test_unreadable_metadata(self):
        folder = self.folder()
        with open(os.path.join(folder, "model_metadata.json"), "w") as handle:
            handle.write("{ not json")
        self.assertRefused(self.service(folder), "not valid JSON")

    def test_missing_or_silly_metadata_fields(self):
        folder = self.folder()
        good = self.read_meta(folder)
        broken = [({k: v for k, v in good.items() if k != key}, key) for key in ("threshold", "features", "high_risk_class", "artifact_sha256")]
        broken += [(dict(good, threshold=t), "threshold") for t in (0, 1, 1.2, -0.1, "0.5", True, None, float("nan"))]
        broken += [(dict(good, stage="enhanced"), "stage"), (dict(good, schema_version=2), "schema_version"),
                   (dict(good, features=[]), "features"), (dict(good, features=["Age", "Age"]), "features"),
                   (dict(good, artifact_sha256="abc"), "artifact_sha256"), (dict(good, model_version=" "), "model_version")]
        for meta, word in broken:
            self.write_meta(folder, meta)
            self.assertRefused(self.service(folder), word)

    def test_the_artifact_name_may_not_point_outside_the_model_folder(self):
        folder = self.folder()
        good = self.read_meta(folder)
        for name in ("../final_model.joblib", "sub/final_model.joblib", "C:\\x.joblib", "final_model.exe", "/etc/passwd"):
            self.write_meta(folder, dict(good, artifact_file=name))
            self.assertRefused(self.service(folder), "artifact_file")

    def test_the_model_file_is_missing(self):
        folder = self.folder()
        os.remove(os.path.join(folder, "final_model.joblib"))
        self.assertRefused(self.service(folder), "Model file found", "final_model.joblib")

    def test_a_changed_model_file_is_detected_by_its_checksum(self):
        folder = self.folder()
        with open(os.path.join(folder, "final_model.joblib"), "ab") as handle:
            handle.write(b"x")
        self.assertRefused(self.service(folder), "SHA-256")

    def test_a_file_that_is_not_a_model_is_refused_even_with_a_matching_checksum(self):
        import joblib
        folder = self.folder()
        joblib.dump({"just": "a dict"}, os.path.join(folder, "final_model.joblib"))
        stand_in = model_fixtures.StandIn(folder, None, self.read_meta(folder), os.path.join(folder, "final_model.joblib"))
        stand_in.rehash()
        self.assertRefused(self.service(folder), "predict_proba")
        with open(os.path.join(folder, "final_model.joblib"), "wb") as handle:
            handle.write(b"this is not a pickle")
        stand_in.rehash()
        self.assertRefused(self.service(folder), "loaded")

    def test_a_different_scikit_learn_version_is_refused_with_the_exact_command_to_fix_it(self):
        folder = self.folder()
        meta = self.read_meta(folder)
        meta["library_versions"]["scikit-learn"] = "0.0.1"
        self.write_meta(folder, meta)
        service = self.service(folder)
        self.assertRefused(service, "scikit-learn", "0.0.1", "pip install", "scikit-learn==0.0.1")

    def test_an_xgboost_version_that_does_not_match_is_refused(self):
        folder = self.folder()
        meta = self.read_meta(folder)
        meta["library_versions"]["xgboost"] = "0.0.1"
        self.write_meta(folder, meta)
        self.assertRefused(self.service(folder), "xgboost")

    def test_a_pandas_or_numpy_difference_is_only_a_warning(self):
        folder = self.folder()
        meta = self.read_meta(folder)
        meta["library_versions"]["pandas"] = "0.0.1"
        self.write_meta(folder, meta)
        service = self.service(folder)
        self.assertTrue(service.ready)
        warning = next(c for c in service.checks if c.name == "pandas version")
        self.assertFalse(warning.ok)
        self.assertFalse(warning.fatal)

    def test_the_high_risk_class_must_be_one_of_the_models_classes(self):
        folder = self.folder()
        self.write_meta(folder, dict(self.read_meta(folder), high_risk_class=5))
        self.assertRefused(self.service(folder), "high-risk class")

    def test_the_inputs_must_be_exactly_the_questions(self):
        folder = self.folder()
        meta = self.read_meta(folder)
        self.write_meta(folder, dict(meta, features=meta["features"][1:]))
        self.assertRefused(self.service(folder), "exactly the screening questions", meta["features"][0])
        self.write_meta(folder, dict(meta, features=meta["features"] + ["HbA1c"]))
        self.assertRefused(self.service(folder), "HbA1c")

    def test_a_model_that_lacks_a_question_is_refused(self):
        folder = os.path.join(self.root, "dropped")
        model_fixtures.build_stand_in(folder, self.catalog, drop_column="Statin")
        self.assertRefused(self.service(folder), "Statin")

    def test_the_order_in_the_metadata_must_be_the_models_own_order(self):
        folder = self.folder()
        meta = self.read_meta(folder)
        features = list(meta["features"])
        features[0], features[1] = features[1], features[0]
        self.write_meta(folder, dict(meta, features=features))
        self.assertRefused(self.service(folder), "own order")

    def test_a_model_trained_without_column_names_cannot_be_trusted(self):
        folder = os.path.join(self.root, "numpy")
        stand_in = model_fixtures.build_stand_in(folder, self.catalog, use_numpy=True)
        self.assertRefused(self.service(folder), "column names")

    def test_a_country_the_model_never_saw_is_caught_before_a_single_person_is_screened(self):
        # The pipeline's OneHotEncoder(handle_unknown="ignore") would quietly treat an unknown country as the first one.
        folder = os.path.join(self.root, "three-countries")
        model_fixtures.build_stand_in(folder, self.catalog, country_options=["USA", "UK", "India"])
        service = self.service(folder)
        self.assertRefused(service, "Country", "Canada")

    def test_a_new_answer_added_to_the_form_but_not_known_to_the_model_is_caught(self):
        catalog = copy.deepcopy(self.catalog)
        contract.question_for(catalog, "Country")["options"].append({"value": "Philippines", "label": "Philippines"})
        self.assertRefused(self.service(self.base.directory, catalog), "Country", "Philippines")

    def test_a_question_asked_as_a_number_but_learned_as_categories_is_caught(self):
        catalog = copy.deepcopy(self.catalog)
        question = contract.question_for(catalog, "Sex")
        question.update(kind="number", min=0, max=1, integer=True, unit="")
        del question["options"]
        self.assertRefused(self.service(self.base.directory, catalog), "Sex")

    def test_a_model_that_cannot_run_is_refused(self):
        from sklearn.ensemble import GradientBoostingClassifier
        folder = self.folder()
        with mock.patch.object(GradientBoostingClassifier, "predict_proba", side_effect=RuntimeError("boom")):
            self.assertRefused(self.service(folder), "runs")

    def test_a_model_that_returns_nonsense_is_refused(self):
        from sklearn.ensemble import GradientBoostingClassifier
        import numpy as np
        folder = self.folder()
        with mock.patch.object(GradientBoostingClassifier, "predict_proba", return_value=np.array([[float("nan"), float("nan")]])):
            self.assertRefused(self.service(folder), "runs")

    def test_a_model_without_feature_importance_is_refused(self):
        folder = self.folder()
        service = ModelService(folder, self.catalog)
        with mock.patch.object(model_service, "_importance_by_input", side_effect=ValueError("the final model has no feature_importances_")):
            service.load()
        self.assertRefused(service, "feature importance")

    def test_a_problem_nobody_planned_for_never_crashes_the_app(self):
        folder = self.folder()
        with mock.patch.object(model_service.ModelService, "_check_features", side_effect=KeyError("surprise")):
            service = self.service(folder)
        self.assertFalse(service.ready)
        self.assertIn("Unexpected problem", service.reason)


class AnswerGuardTests(ServiceCase):
    def setUp(self):
        self.service_ = self.service(self.base.directory)
        self.row = contract.reference_row(self.catalog)

    def refuses(self, row, *words):
        with mock.patch.object(type(self.base.pipeline), "predict_proba") as predict:
            with self.assertRaises(ModelInputError) as caught:
                self.service_.predict(row)
            predict.assert_not_called()                                      # the model is never asked about a bad row
        for word in words:
            self.assertIn(word, str(caught.exception))

    def test_a_missing_answer_is_an_error_never_a_guess(self):
        for name in self.row:
            row = {k: v for k, v in self.row.items() if k != name}
            self.refuses(row, name)

    def test_an_extra_answer_is_an_error(self):
        self.refuses(dict(self.row, eGFR=45), "eGFR")

    def test_empty_or_not_a_number_answers_are_errors(self):
        for name in ("Age", "BMI", "Water_Intake_L"):
            for bad in (None, float("nan"), float("inf"), "48", True):
                self.refuses(dict(self.row, **{name: bad}), name)

    def test_an_answer_the_model_never_saw_is_an_error(self):
        self.refuses(dict(self.row, Country="Atlantis"), "Country", "Atlantis")         # not an answer the form offers at all
        self.refuses(dict(self.row, Diabetes=2), "Diabetes")
        self.refuses(dict(self.row, Diabetes=True), "Diabetes")
        self.refuses(dict(self.row, Alcohol_Consumption=None), "Alcohol_Consumption")
        self.refuses(dict(self.row, Obesity=3), "Obesity")

    def test_a_number_outside_the_trained_range_is_refused_not_adjusted(self):
        # Outside the TRAINING range is accepted (so the model can be checked on people it never saw); only an
        # unrealistic value is refused, and nothing is ever clamped to fit.
        self.refuses(dict(self.row, Age=200), "Age", "outside")
        self.refuses(dict(self.row, BMI=95.0), "BMI")
        self.refuses(dict(self.row, Water_Intake_L=11.0), "Water_Intake_L")
        for accepted in (dict(self.row, Age=17), dict(self.row, BMI=60.0), dict(self.row, Water_Intake_L=9.0)):
            self.assertIn("probability", self.service_.predict(accepted))

    def test_philippines_is_given_to_the_model_as_other(self):
        self.assertEqual(self.service_.predict(dict(self.row, Country="Philippines"))["probability"],
                         self.service_.predict(dict(self.row, Country="Other"))["probability"])

    def test_a_service_that_is_not_ready_gives_no_result(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        service = self.service(empty)
        with self.assertRaises(ModelUnavailableError):
            service.predict(self.row)


class NeverTrainsTests(ServiceCase):
    def test_the_program_contains_no_training_or_saving_code(self):
        with open(model_service.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in (".fit(", ".fit_transform(", "joblib.dump", "pickle.dump", "GridSearchCV", "train_test_split"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_loading_predicting_and_explaining_never_train_and_never_change_the_file(self):
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.pipeline import Pipeline
        folder = self.folder()
        path = os.path.join(folder, "final_model.joblib")
        with open(path, "rb") as handle:
            before = hashlib.sha256(handle.read()).hexdigest()
        with mock.patch.object(GradientBoostingClassifier, "fit", side_effect=AssertionError("trained!")), \
             mock.patch.object(Pipeline, "fit", side_effect=AssertionError("trained!")):
            service = self.service(folder)
            service.predict(contract.reference_row(self.catalog))
            service.factors()
            service.load()                                                # loading again is harmless
        self.assertTrue(service.ready)
        with open(path, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
