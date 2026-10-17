"""
Checks for services/model_design.py and the administrator's How the models work page
(/admin/model/how-it-works). The old Model comparison page was removed.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services import model_design, model_insights  # noqa: E402
from test_admin_flow import AdminTestCase  # noqa: E402

Y = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
P = [0.9, 0.8, 0.7, 0.3, 0.6, 0.4, 0.2, 0.1, 0.1, 0.05]


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.m = model_insights.compute_metrics(Y, P, 0.5, "hand.csv")

    def test_the_score_distribution_counts_every_person_once_in_their_group(self):
        dist = self.m["distribution"]
        self.assertEqual((sum(dist["positive"]), sum(dist["negative"])), (4, 6))
        self.assertEqual(len(dist["edges"]), model_insights.SCORE_BINS + 1)
        self.assertEqual(dist["positive"][-2], 1)                  # 0.9 falls in 90-95%
        self.assertEqual(dist["negative"][1], 1)                   # 0.05 falls in 5-10%

    def test_the_tradeoff_runs_from_flag_everyone_to_flag_no_one_and_matches_the_threshold(self):
        rows = self.m["tradeoff"]
        self.assertEqual(rows[0], [0.0, 1.0, 0.0])                 # threshold 0: every case caught, no one cleared
        self.assertEqual(rows[-1][1], 0.0)                         # threshold 100%: nothing above it here
        at_half = next(r for r in rows if r[0] == 0.5)
        self.assertEqual((at_half[1], at_half[2]), (self.m["sensitivity"], self.m["specificity"]))

    def test_histogram_geometry_stays_inside_the_frame_and_marks_the_threshold(self):
        h = model_design.histogram(self.m)
        for b in h["bins"]:
            for bar in (b["neg"], b["pos"]):
                self.assertTrue(0 <= bar["x"] and bar["x"] + bar["w"] <= h["width"] + 0.01)
                self.assertAlmostEqual(bar["y"] + bar["h"], h["height"], places=1)
        self.assertEqual(h["threshold_x"], h["width"] / 2)

    def test_an_older_metrics_file_without_the_new_parts_gives_none_not_an_error(self):
        old = {k: v for k, v in self.m.items() if k not in ("distribution", "tradeoff")}
        self.assertIsNone(model_design.histogram(old))
        self.assertIsNone(model_design.tradeoff_lines(old))
        self.assertIsNone(model_design.histogram(None))

    def test_input_groups_add_up_the_weight_of_their_members(self):
        importance = [{"name": "Age", "percent": 30.0}, {"name": "Diabetes", "percent": 50.0}, {"name": "Smoking", "percent": 20.0}]
        rows = model_design.input_groups(["Age", "Diabetes", "Smoking"], importance,
                                         [("About you", ["Age"]), ("Health history", ["Diabetes"])])
        self.assertEqual([(r["label"], r["count"], r["weight"]) for r in rows],
                         [("About you", 1, 30.0), ("Health history", 1, 50.0), ("Other inputs", 1, 20.0)])
        self.assertEqual(max(r["share"] for r in rows), 100)


class PipelineDescriptionTests(unittest.TestCase):
    def test_a_calibrated_pipeline_is_read_step_by_step_in_plain_words(self):
        import numpy as np
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.compose import ColumnTransformer
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
        import pandas as pd
        frame = pd.DataFrame({"Age": [30, 40, 50, 60, 70, 80] * 5, "Sex": ["Male", "Female"] * 15})
        y = np.array([0, 0, 1, 0, 1, 1] * 5)
        prepare = ColumnTransformer([("numeric", SimpleImputer(strategy="median", add_indicator=True), ["Age"]),
                                     ("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                                                               ("onehot", OneHotEncoder(handle_unknown="ignore"))]), ["Sex"])])
        pipe = Pipeline([("prepare", prepare), ("model", GradientBoostingClassifier(n_estimators=7, max_depth=2))])
        model = CalibratedClassifierCV(pipe, method="isotonic", cv=3, ensemble=False).fit(frame, y)

        class Service:
            ready, _pipeline = True, model
            metadata = {"threshold": 0.46, "threshold_method": "Youden's J"}

        steps = model_design.pipeline_steps(Service(), "2 answers", "test")
        self.assertEqual([s["kind"] for s in steps], ["inputs", "prepare", "model", "calibrate", "threshold", "result"])
        prepare_words = " ".join(item["words"] for item in steps[1]["items"])
        self.assertIn("median", prepare_words)
        self.assertIn("told the value was blank", prepare_words)
        self.assertIn("one-hot", prepare_words)
        self.assertIn("7 trees", steps[2]["title"])
        self.assertIn("46.00%", steps[4]["title"])

    def test_a_model_that_is_not_ready_has_no_steps(self):
        class Service:
            ready, _pipeline, metadata = False, None, {}
        self.assertEqual(model_design.pipeline_steps(Service(), "x", "y"), [])
        self.assertEqual(model_design.pipeline_steps(None, "x", "y"), [])


class PagesTests(AdminTestCase):
    model = True
    stage2_model = True

    def setUp(self):
        super().setUp()
        self.paths = [os.path.join(self.app.extensions[key].model_dir, model_insights.METRICS_FILE)
                      for key in ("model_service", "model_service_stage2")]
        for path in self.paths:
            if os.path.exists(path):
                os.remove(path)
            self.addCleanup(lambda p=path: os.path.exists(p) and os.remove(p))

    def _measure(self, key, threshold=0.5):
        model_insights.save_metrics(self.app.extensions[key].model_dir, model_insights.compute_metrics(Y, P, threshold, f"{key}.csv"))

    def test_how_the_models_work_shows_each_pipeline_and_waits_honestly_for_measurements(self):
        page = self.text(self.admin.get("/admin/model/how-it-works"))
        self.assertIn("From answers to a result", page)
        self.assertIn("Preliminary Screening model", page)
        self.assertIn("Enhanced Screening model", page)
        self.assertIn('class="flow-step flow-model"', page)
        self.assertIn("Where its inputs and weight come from", page)
        self.assertIn("python model_report.py --stage 1 --csv ml\\validation_holdout.csv --target CKD", page)
        self.assertIn("python model_report.py --stage 2 --csv ml\\stage2_sealed_test.csv --target CKD", page)

    def test_once_measured_it_draws_the_score_distribution_and_the_threshold_tradeoff(self):
        self._measure("model_service")
        page = self.text(self.admin.get("/admin/model/how-it-works"))
        self.assertIn('class="dist-bar dist-positive"', page)
        self.assertIn("Threshold 50.0%", page)
        self.assertIn('class="trade-line trade-sens"', page)
        self.assertIn("Youden&#39;s J", page)
        self.assertIn("<strong>75.0%</strong> sensitivity", page)

    def test_the_model_comparison_page_is_gone(self):
        # The Model comparison feature was removed: its route no longer exists and its menu item is gone.
        self.assertEqual(self.admin.get("/admin/model/compare").status_code, 404)
        self.assertNotIn("Model comparison", self.text(self.admin.get("/admin")))

    def test_how_the_models_work_is_in_the_admin_menu_and_closed_to_everyone_else(self):
        menu = self.text(self.admin.get("/admin"))
        self.assertIn("How the models work", menu)
        self.assertEqual(self.patient.get("/admin/model/how-it-works").status_code, 403)
        self.assertEqual(self.pro.get("/admin/model/how-it-works").status_code, 403)


if __name__ == "__main__":
    unittest.main()
