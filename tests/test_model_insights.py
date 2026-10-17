"""Checks for services/model_insights.py, model_report.py, and the administrator's Model performance page."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services import model_insights  # noqa: E402
from test_admin_flow import AdminTestCase  # noqa: E402
import model_fixtures  # noqa: E402


class ComputeMetricsTests(unittest.TestCase):
    """Hand-checkable numbers: 4 high-risk and 6 lower-risk people, threshold 0.5."""
    Y = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    P = [0.9, 0.8, 0.7, 0.3, 0.6, 0.4, 0.2, 0.1, 0.1, 0.05]

    def setUp(self):
        self.m = model_insights.compute_metrics(self.Y, self.P, 0.5, "hand.csv")

    def test_the_confusion_matrix_and_the_rates_follow_from_it(self):
        self.assertEqual(self.m["confusion"], {"tp": 3, "fn": 1, "fp": 1, "tn": 5})
        self.assertEqual((self.m["sensitivity"], self.m["specificity"], self.m["precision"], self.m["accuracy"]), (0.75, 0.8333, 0.75, 0.8))
        self.assertEqual(self.m["f1"], 0.75)
        self.assertEqual((self.m["rows"], self.m["positives"], self.m["prevalence"]), (10, 4, 0.4))

    def test_roc_auc_matches_a_count_of_correctly_ranked_pairs(self):
        pairs = [(a, b) for a, ya in zip(self.P, self.Y) for b, yb in zip(self.P, self.Y) if ya == 1 and yb == 0]
        expected = sum(1 if a > b else 0.5 if a == b else 0 for a, b in pairs) / len(pairs)
        self.assertAlmostEqual(self.m["roc_auc"], round(expected, 4))

    def test_the_roc_curve_runs_from_0_0_to_1_1_and_draws_inside_the_frame(self):
        self.assertEqual(self.m["roc"][0], [0.0, 0.0])
        self.assertEqual(self.m["roc"][-1], [1.0, 1.0])
        points = [tuple(map(float, p.split(","))) for p in model_insights.roc_polyline(self.m).split()]
        self.assertTrue(all(0 <= x <= 200 and 0 <= y <= 200 for x, y in points))

    def test_saved_metrics_load_back_and_a_missing_or_broken_file_is_none(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(model_insights.load_metrics(folder))
            model_insights.save_metrics(folder, self.m)
            self.assertEqual(model_insights.load_metrics(folder)["roc_auc"], self.m["roc_auc"])
            with open(os.path.join(folder, model_insights.METRICS_FILE), "w") as handle:
                handle.write("{not json")
            self.assertIsNone(model_insights.load_metrics(folder))


class ModelPageTests(AdminTestCase):
    model = True

    def setUp(self):
        super().setUp()
        # The stand-in model's folder is shared between tests: start each test without a saved metrics file.
        path = os.path.join(self.app.extensions["model_service"].model_dir, model_insights.METRICS_FILE)
        if os.path.exists(path):
            os.remove(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

    def test_without_saved_metrics_the_page_says_how_to_measure_instead_of_showing_numbers(self):
        page = self.text(self.admin.get("/admin/model"))
        self.assertIn("Not measured yet", page)
        self.assertIn("python model_report.py --stage 1", page)

    def test_saved_metrics_are_shown_with_the_confusion_matrix_and_roc_curve(self):
        service = self.app.extensions["model_service"]
        metrics = model_insights.compute_metrics(ComputeMetricsTests.Y, ComputeMetricsTests.P, 0.5, "holdout.csv")
        model_insights.save_metrics(service.model_dir, metrics)
        page = self.text(self.admin.get("/admin/model"))
        self.assertIn("holdout.csv", page)
        self.assertIn("75.0%", page)                                  # sensitivity
        self.assertIn('class="roc-line"', page)
        self.assertRegex(page, r'cm-bad">1<small>missed')

    def test_feature_importance_comes_from_the_loaded_model(self):
        page = self.text(self.admin.get("/admin/model"))
        self.assertIn("Feature importance", page)
        expected = self.app.extensions["model_service"].factors(limit=1)[0]["label"]
        self.assertIn(expected, page)

    def test_the_model_card_shows_the_version_and_threshold(self):
        service = self.app.extensions["model_service"]
        page = self.text(self.admin.get("/admin/model"))
        self.assertIn(service.version, page)
        self.assertIn("Decision threshold", page)

    def test_only_an_administrator_can_open_it(self):
        self.assertEqual(self.patient.get("/admin/model").status_code, 403)
        self.assertEqual(self.pro.get("/admin/model").status_code, 403)


class ModelReportCommandTests(unittest.TestCase):
    def test_it_measures_a_model_on_labelled_rows_and_saves_the_file(self):
        if not model_fixtures.libraries_available():
            self.skipTest("model libraries are not installed")
        import numpy as np
        import pandas as pd
        from services import screening_contract
        import model_report
        catalog = screening_contract.load_catalog()
        with tempfile.TemporaryDirectory() as folder:
            model_fixtures.build_stand_in(folder, catalog)
            rows = model_fixtures.random_answers(catalog, np.random.default_rng(3), 300)
            frame = pd.DataFrame(rows)
            frame["CKD"] = (frame["Diabetes"].astype(int) | frame["Hypertension"].astype(int)).astype(int)
            csv = os.path.join(folder, "holdout.csv")
            frame.to_csv(csv, index=False)
            self.assertEqual(model_report.main(["--stage", "1", "--csv", csv, "--target", "CKD", "--model-dir", folder]), 0)
            with open(os.path.join(folder, model_insights.METRICS_FILE)) as handle:
                saved = json.load(handle)
            self.assertEqual(saved["rows"], 300)
            self.assertEqual(sum(saved["confusion"].values()), 300)
            self.assertTrue(0 <= saved["roc_auc"] <= 1)

    def test_a_missing_target_column_is_reported_not_crashed(self):
        if not model_fixtures.libraries_available():
            self.skipTest("model libraries are not installed")
        from services import screening_contract
        import model_report
        import numpy as np
        import pandas as pd
        catalog = screening_contract.load_catalog()
        with tempfile.TemporaryDirectory() as folder:
            model_fixtures.build_stand_in(folder, catalog)
            csv = os.path.join(folder, "nolabel.csv")
            pd.DataFrame(model_fixtures.random_answers(catalog, np.random.default_rng(1), 20)).to_csv(csv, index=False)
            self.assertEqual(model_report.main(["--stage", "1", "--csv", csv, "--target", "CKD", "--model-dir", folder]), 2)


if __name__ == "__main__":
    unittest.main()
