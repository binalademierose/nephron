"""
Checks for services/visuals.py: the numbers and chart shapes behind the dashboard.
Run from the project folder with:   python -m unittest discover -s tests -v

These protect one rule: a chart or metric is only ever calculated from real assessment
records. Nothing here needs Flask or MySQL.
"""
import math
import os
import re
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import visuals  # noqa: E402

TODAY = date(2026, 9, 25)


def record(day, probability, level, kind="Preliminary screening"):
    return {"date": day, "type": kind, "probability": probability, "level": level}


THREE = [record(date(2026, 6, 12), 15, "low"), record(date(2026, 9, 20), 31, "high"), record(date(2026, 8, 10), 18, "low")]


class SummaryTests(unittest.TestCase):
    def test_no_assessments_means_empty_everything(self):
        summary = visuals.summarize_assessments([], today=TODAY)
        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["latest"])
        self.assertIsNone(summary["change"])
        self.assertFalse(summary["has_distribution"])
        self.assertFalse(summary["has_trend"])
        self.assertEqual(summary["next_screening"]["state"], "available")

    def test_one_assessment_can_be_counted_but_is_not_a_trend(self):
        summary = visuals.summarize_assessments([record(date(2026, 9, 20), 12, "low")], today=TODAY)
        self.assertTrue(summary["has_distribution"])
        self.assertFalse(summary["has_trend"])          # one point cannot show change
        self.assertIsNone(summary["change"])
        self.assertIsNone(visuals.trend_geometry(summary["oldest_first"], 21))

    def test_records_are_ordered_by_date_whatever_order_they_arrive_in(self):
        summary = visuals.summarize_assessments(THREE, today=TODAY)
        self.assertEqual([r["probability"] for r in summary["newest_first"]], [31, 18, 15])
        self.assertEqual(summary["latest"]["probability"], 31)
        self.assertEqual(summary["previous"]["probability"], 18)
        self.assertEqual((summary["total"], summary["low_count"], summary["high_count"]), (3, 2, 1))

    def test_change_is_described_neutrally(self):
        change = visuals.summarize_assessments(THREE, today=TODAY)["change"]
        self.assertEqual((change["points"], change["direction"]), (13.0, "higher"))
        lower = visuals.summarize_assessments([record(date(2026, 8, 1), 30, "high"), record(date(2026, 9, 1), 12, "low")], today=TODAY)["change"]
        self.assertEqual((lower["points"], lower["direction"]), (18.0, "lower"))
        same = visuals.summarize_assessments([record(date(2026, 8, 1), 20, "low"), record(date(2026, 9, 1), 20, "low")], today=TODAY)["change"]
        self.assertEqual(same["direction"], "same")

    def test_next_screening_without_a_set_interval_is_available(self):
        self.assertEqual(visuals.summarize_assessments(THREE, today=TODAY)["next_screening"]["state"], "available")

    def test_next_screening_waits_until_the_interval_has_passed(self):
        waiting = visuals.summarize_assessments(THREE, today=TODAY, reassessment_days=30)["next_screening"]
        self.assertEqual(waiting["state"], "waiting")
        self.assertEqual(waiting["date"], date(2026, 10, 20))
        self.assertEqual(waiting["days_left"], 25)
        self.assertAlmostEqual(waiting["elapsed_share"], 5 / 30)
        open_again = visuals.summarize_assessments(THREE, today=date(2026, 10, 21), reassessment_days=30)["next_screening"]
        self.assertEqual((open_again["state"], open_again["days_left"]), ("available", 0))

    def test_bad_records_are_refused(self):
        with self.assertRaises(ValueError):
            visuals.summarize_assessments([record(date(2026, 9, 1), 20, "critical")], today=TODAY)
        with self.assertRaises(ValueError):
            visuals.summarize_assessments([record(date(2026, 9, 1), 140, "high")], today=TODAY)

    def test_this_month_count_only_counts_this_month(self):
        summary = visuals.summarize_assessments(THREE, today=TODAY)          # only Sep 20 is in September
        self.assertEqual(summary["month_count"], 1)
        self.assertEqual(visuals.summarize_assessments([], today=TODAY)["month_count"], 0)

    def test_screening_path_position(self):
        self.assertEqual(visuals.screening_path(0), 0)                        # nothing yet: Screening is current
        self.assertEqual(visuals.screening_path(2), 3)                        # screened, analysed, result exists
        self.assertEqual(visuals.screening_path(2, follow_up_count=1), 4)     # a follow-up exists too
        self.assertEqual(len(visuals.PATH_STEPS), 4)

    def test_date_wording(self):
        self.assertEqual(visuals.format_date(date(2026, 9, 5)), "Sep 5, 2026")
        self.assertEqual(visuals.short_date(date(2026, 9, 5)), "Sep 5")
        self.assertEqual(visuals.relative_day_text(date(2026, 9, 25), TODAY), "Today")
        self.assertEqual(visuals.relative_day_text(date(2026, 9, 24), TODAY), "Yesterday")
        self.assertEqual(visuals.relative_day_text(date(2026, 9, 20), TODAY), "5 days ago")

    def test_risk_words_come_from_one_place(self):
        self.assertEqual(visuals.level_label("low"), "Low Preliminary Risk")
        self.assertEqual(visuals.level_label("high"), "High Preliminary Risk")


class MessageAndActivityTests(unittest.TestCase):
    def test_no_assessments_means_no_message(self):
        self.assertIsNone(visuals.summary_message(0, 0))

    def test_message_follows_the_counts(self):
        self.assertIn("lower-risk group", visuals.summary_message(2, 1))
        self.assertIn("higher-risk group", visuals.summary_message(1, 2))
        self.assertIn("evenly split", visuals.summary_message(1, 1))

    def test_activity_only_contains_real_completed_assessments(self):
        summary = visuals.summarize_assessments(THREE, today=TODAY)
        items = visuals.activity_items(summary["newest_first"])
        self.assertEqual([i["date"] for i in items], [date(2026, 9, 20), date(2026, 8, 10), date(2026, 6, 12)])
        self.assertTrue(all(i["title"] == "Assessment completed" for i in items))
        self.assertEqual(visuals.activity_items([]), [])                      # nothing is added to look busy

    def test_activity_is_limited(self):
        many = [record(date(2026, 1, d), 10, "low") for d in range(1, 8)]
        self.assertEqual(len(visuals.activity_items(visuals.summarize_assessments(many, today=TODAY)["newest_first"])), 3)


class PercentTextTests(unittest.TestCase):
    def test_one_decimal_at_most_and_no_trailing_zero(self):
        for value, text in ((31.0, "31"), (55.3894, "55.4"), (64.7029, "64.7"), (0.0, "0"), (100.0, "100"), (7.04, "7"), (7.05, "7"), (12.25, "12.2"), (0.96, "1")):
            self.assertEqual(visuals.percent_text(value), text, value)


class ThresholdTests(unittest.TestCase):
    def test_a_record_may_carry_its_own_threshold_or_none(self):
        with_threshold = record(date(2026, 9, 1), 20, "low"); with_threshold["threshold"] = 21
        summary = visuals.summarize_assessments([with_threshold, record(date(2026, 9, 5), 30, "high")], today=TODAY)
        self.assertEqual(summary["latest"].get("threshold"), None)
        self.assertEqual(summary["previous"]["threshold"], 21)

    def test_an_impossible_threshold_is_refused(self):
        for bad in (-1, 101):
            broken = record(date(2026, 9, 1), 20, "low"); broken["threshold"] = bad
            with self.assertRaises(ValueError):
                visuals.summarize_assessments([broken], today=TODAY)

    def test_the_trend_works_without_a_threshold(self):
        summary = visuals.summarize_assessments(THREE, today=TODAY)
        trend = visuals.trend_geometry(summary["oldest_first"])
        self.assertIsNone(trend["threshold_y"])
        self.assertEqual(len(trend["points"]), 3)


class RingTests(unittest.TestCase):
    def test_fill_length_follows_the_percentage(self):
        empty, full, half = (visuals.ring_geometry(p) for p in (0, 100, 50))
        self.assertEqual(empty["value_length"], 0)
        self.assertAlmostEqual(full["value_length"], full["circumference"], places=1)
        self.assertAlmostEqual(half["value_length"], half["circumference"] / 2, places=1)

    def test_out_of_range_percentages_are_clamped(self):
        self.assertAlmostEqual(visuals.ring_geometry(150)["value_length"], visuals.ring_geometry(100)["value_length"], places=1)
        self.assertEqual(visuals.ring_geometry(-5)["value_length"], 0)

    def test_no_tick_unless_a_threshold_is_given(self):
        self.assertIsNone(visuals.ring_geometry(18)["tick"])

    def test_threshold_tick_sits_at_the_right_angle(self):
        centre = visuals.RING_BOX / 2
        top = visuals.ring_geometry(10, threshold=0)["tick"]                   # 0% is straight up
        self.assertAlmostEqual(top["x1"], centre, places=1)
        self.assertLess(top["y1"], centre)
        right = visuals.ring_geometry(10, threshold=25)["tick"]                # 25% is 3 o'clock
        self.assertGreater(right["x1"], centre)
        self.assertAlmostEqual(right["y1"], centre, places=1)


class DonutTests(unittest.TestCase):
    def test_no_assessments_means_no_segments(self):
        self.assertEqual(visuals.donut_geometry(0, 0)["segments"], [])

    def test_segments_add_up_to_the_ring(self):
        donut = visuals.donut_geometry(2, 1)
        self.assertEqual([s["key"] for s in donut["segments"]], ["low", "high"])
        self.assertEqual(sum(s["count"] for s in donut["segments"]), 3)
        lengths = [float(s["dasharray"].split()[0]) for s in donut["segments"]]
        self.assertAlmostEqual(sum(lengths) + 2 * donut["gap"], donut["circumference"], places=1)

    def test_a_single_class_fills_the_whole_ring_without_a_gap(self):
        donut = visuals.donut_geometry(3, 0)
        self.assertEqual(len(donut["segments"]), 1)
        self.assertAlmostEqual(float(donut["segments"][0]["dasharray"].split()[0]), donut["circumference"], places=1)


def sample_bezier(path, steps=20):
    """Read the 'M x y C ...' path back into points on the curve, so the tests can check the real shape."""
    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", path)]
    (x0, y0), rest, curve = numbers[:2], numbers[2:], []
    while rest:
        x1, y1, x2, y2, x3, y3 = rest[:6]
        rest = rest[6:]
        for t in (i / steps for i in range(steps + 1)):
            u = 1 - t
            curve.append((u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                          u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3))
        x0, y0 = x3, y3
    return curve


class TrendTests(unittest.TestCase):
    def setUp(self):
        self.summary = visuals.summarize_assessments(THREE, today=TODAY)
        self.trend = visuals.trend_geometry(self.summary["oldest_first"], 21)

    def test_axis_is_always_zero_to_one_hundred(self):
        self.assertEqual([t["value"] for t in self.trend["ticks"]], [0, 25, 50, 75, 100])
        self.assertEqual(self.trend["ticks"][0]["y"], self.trend["baseline"])          # 0% sits on the baseline

    def test_points_stay_inside_the_plot_area(self):
        for point in self.trend["points"]:
            self.assertGreaterEqual(point["x"], self.trend["left"])
            self.assertLessEqual(point["x"], self.trend["right"])
            self.assertLessEqual(point["y"], self.trend["baseline"])

    def test_a_point_sits_exactly_at_its_probability(self):
        top, baseline = self.trend["top"], self.trend["baseline"]
        for point in self.trend["points"]:
            expected = baseline - (baseline - top) * point["probability"] / 100
            self.assertAlmostEqual(point["y"], expected, delta=0.1)

    def test_higher_probability_is_drawn_higher_up(self):
        by_value = sorted(self.trend["points"], key=lambda p: p["probability"])
        self.assertEqual([p["y"] for p in by_value], sorted((p["y"] for p in by_value), reverse=True))

    def test_points_are_placed_by_real_date(self):
        xs = [p["x"] for p in self.trend["points"]]
        gap_first, gap_second = xs[1] - xs[0], xs[2] - xs[1]      # 59 days, then 41 days
        self.assertAlmostEqual(gap_first / gap_second, 59 / 41, places=1)

    def test_the_smooth_line_never_invents_a_peak(self):
        """Between two points the curve must stay between their two values (no overshoot)."""
        spiky = [record(date(2026, 1, 1), 10, "low"), record(date(2026, 1, 20), 12, "low"),
                 record(date(2026, 2, 10), 60, "high"), record(date(2026, 2, 12), 11, "low"), record(date(2026, 4, 1), 12, "low")]
        trend = visuals.trend_geometry(visuals.summarize_assessments(spiky, today=TODAY)["oldest_first"], 21)
        ys = [p["y"] for p in trend["points"]]
        curve = sample_bezier(trend["line"])
        self.assertGreater(len(curve), 20)
        self.assertLessEqual(max(y for _, y in curve), max(ys) + 0.2)               # never lower than the lowest value
        self.assertGreaterEqual(min(y for _, y in curve), min(ys) - 0.2)            # never higher than the highest value
        for (x, y) in curve:
            self.assertGreaterEqual(x, trend["points"][0]["x"] - 0.2)
            self.assertLessEqual(x, trend["points"][-1]["x"] + 0.2)

    def test_two_records_on_one_day_do_not_break_the_line(self):
        same_day = [record(date(2026, 9, 1), 15, "low"), record(date(2026, 9, 20), 20, "low"), record(date(2026, 9, 20), 30, "high")]
        trend = visuals.trend_geometry(visuals.summarize_assessments(same_day, today=TODAY)["oldest_first"], 21)
        self.assertIn("L", trend["line"])
        self.assertTrue(trend["line"].startswith("M"))

    def test_threshold_line_matches_its_value(self):
        y_axis = {tick["value"]: tick["y"] for tick in self.trend["ticks"]}
        self.assertLess(self.trend["threshold_y"], y_axis[0])
        self.assertGreater(self.trend["threshold_y"], y_axis[25])

    def test_well_spaced_dates_are_all_labelled(self):
        self.assertTrue(all(point["show_label"] for point in self.trend["points"]))

    def test_close_dates_never_print_labels_on_top_of_each_other(self):
        records = [record(date(2026, 1, 1), 15, "low"), record(date(2026, 9, 1), 18, "low"),
                   record(date(2026, 9, 4), 30, "high"), record(date(2026, 9, 25), 25, "high")]
        trend = visuals.trend_geometry(visuals.summarize_assessments(records, today=TODAY)["oldest_first"], 21)
        labelled = [point for point in trend["points"] if point["show_label"]]
        self.assertTrue(trend["points"][0]["show_label"] and trend["points"][-1]["show_label"])
        for left, right in zip(labelled, labelled[1:]):
            self.assertGreaterEqual(right["x"] - left["x"], visuals.MIN_LABEL_GAP)
        self.assertLess(len(labelled), len(trend["points"]))       # something had to be dropped

    def test_line_and_area_paths_are_built(self):
        self.assertTrue(self.trend["line"].startswith("M"))
        self.assertIn("C", self.trend["line"])                     # smooth curve segments
        self.assertTrue(self.trend["area"].endswith("Z"))

    def test_one_point_is_not_a_trend(self):
        self.assertIsNone(visuals.trend_geometry([record(date(2026, 9, 1), 15, "low")], 21))


class TrendFrameTests(unittest.TestCase):
    def test_the_empty_frame_has_the_same_scale_as_a_real_chart(self):
        frame = visuals.trend_frame()
        real = visuals.trend_geometry(visuals.summarize_assessments(THREE, today=TODAY)["oldest_first"], 21)
        for key in ("width", "height", "left", "right", "top", "baseline", "ticks"):
            self.assertEqual(frame[key], real[key])
        self.assertNotIn("points", frame)                          # a frame never contains data


class SparklineTests(unittest.TestCase):
    def test_needs_two_real_points(self):
        self.assertIsNone(visuals.sparkline_geometry([]))
        self.assertIsNone(visuals.sparkline_geometry([record(date(2026, 9, 1), 15, "low")]))

    def test_shape_stays_inside_its_box(self):
        spark = visuals.sparkline_geometry(visuals.summarize_assessments(THREE, today=TODAY)["oldest_first"])
        for x, y in sample_bezier(spark["line"]):
            self.assertTrue(0 <= x <= spark["width"] and 0 <= y <= spark["height"])
        self.assertTrue(spark["area"].endswith("Z"))

    def test_equal_values_draw_a_flat_line(self):
        flat = [record(date(2026, 9, 1), 20, "low"), record(date(2026, 9, 10), 20, "low")]
        spark = visuals.sparkline_geometry(flat)
        ys = {round(y, 1) for _, y in sample_bezier(spark["line"])}
        self.assertEqual(len(ys), 1)


if __name__ == "__main__":
    unittest.main()
