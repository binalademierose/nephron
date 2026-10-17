"""
Phase 1 automated checks. Run from the project folder with:

    python -m unittest discover -s tests -v

These check the pages, error handling and headers. They do not need MySQL to
be running: /health is allowed to answer "ok" or "degraded" as long as its
answer is consistent. The real MySQL check is done by opening /health yourself.
"""
import os
import re
import sys
import unittest
from html.parser import HTMLParser

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ["FLASK_DEBUG"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector  # noqa: E402
from app import create_app  # noqa: E402


def _raise_python_error():
    raise ZeroDivisionError("secret internal detail")


def _raise_database_error():
    raise mysql.connector.OperationalError("SELECT * FROM secret_table failed")


class FoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["PROPAGATE_EXCEPTIONS"] = False  # show the friendly 500 page
        cls.app.add_url_rule("/_test/python-error", "test_python_error", _raise_python_error)
        cls.app.add_url_rule("/_test/database-error", "test_database_error", _raise_database_error)
        cls.client = cls.app.test_client()

    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Early kidney health risk screening", response.data)

    def test_about_page_loads(self):
        response = self.client.get("/about")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"How Nephron works", response.data)

    def test_disclaimer_is_on_every_page(self):
        disclaimer = self.app.config["MEDICAL_DISCLAIMER"].encode()
        for path in ("/", "/about", "/does-not-exist"):
            self.assertIn(disclaimer, self.client.get(path).data, path)

    def test_diagnostic_wording_is_not_used(self):
        # The system must never claim to diagnose. Check the public pages.
        for path in ("/", "/about"):
            text = self.client.get(path).get_data(as_text=True).lower()
            for phrase in ("you have ckd", "confirms kidney disease", "confidence score"):
                self.assertNotIn(phrase, text, f"{phrase!r} found on {path}")

    def test_unknown_page_shows_friendly_404(self):
        response = self.client.get("/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Page not found", response.data)

    def test_wrong_method_shows_friendly_405(self):
        response = self.client.post("/")
        self.assertEqual(response.status_code, 405)
        self.assertIn(b"Action not allowed", response.data)

    def test_unexpected_error_hides_technical_details(self):
        # The detail must reach the log file but never the screen.
        with self.assertLogs(self.app.logger, level="ERROR") as logged:
            response = self.client.get("/_test/python-error")
        self.assertIn("secret internal detail", "\n".join(logged.output))
        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertIn("Something went wrong", body)
        for secret in ("ZeroDivisionError", "secret internal detail", "Traceback", "app.py"):
            self.assertNotIn(secret, body)

    def test_database_error_hides_sql(self):
        with self.assertLogs(self.app.logger, level="ERROR") as logged:
            response = self.client.get("/_test/database-error")
        self.assertIn("secret_table", "\n".join(logged.output))
        self.assertEqual(response.status_code, 503)
        body = response.get_data(as_text=True)
        self.assertIn("temporarily unavailable", body)
        self.assertNotIn("secret_table", body)
        self.assertNotIn("SELECT", body)

    def test_health_answer_is_consistent(self):
        response = self.client.get("/health")
        data = response.get_json()
        if response.status_code == 200:
            self.assertEqual(data, {"status": "ok", "database": "connected"})
        else:
            self.assertEqual(response.status_code, 503)
            self.assertEqual(data, {"status": "degraded", "database": "unavailable"})

    def test_security_headers_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")

    def test_static_files_are_served(self):
        for path in ("/static/css/tokens.css", "/static/css/base.css", "/static/css/layout.css",
                     "/static/css/components.css", "/static/css/domain.css", "/static/css/pages.css",
                     "/static/js/main.js",
                     "/static/images/brand/nephron-logo.png", "/static/images/brand/nephron-badge.png",
                     "/static/images/brand/nephron-logo-master.png",
                     "/static/images/brand/favicon-64.png", "/static/images/brand/apple-touch-icon.png"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200, path)

    def test_official_logo_is_used_and_not_replaced(self):
        for path in ("/", "/about", "/does-not-exist"):
            page = self.client.get(path).get_data(as_text=True)
            self.assertIn("images/brand/nephron-logo.png", page, path)       # the mark, in the header and the footer
            self.assertIn('class="brand-name"', page, path)                  # and the name, as real text

    def test_logo_files_keep_their_shape(self):
        # The mark must never be stretched: the width and height written in the HTML must match the
        # real picture. (We read the PNG header directly: no extra library.)
        import re
        import struct
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "images", "brand")
        sizes, colour_types = {}, {}
        for name in ("nephron-logo.png", "nephron-badge.png", "favicon-64.png", "apple-touch-icon.png", "nephron-logo-master.png"):
            with open(os.path.join(base, name), "rb") as file:
                header = file.read(26)
            sizes[name] = struct.unpack(">II", header[16:24])
            colour_types[name] = header[25]
        home = self.client.get("/").get_data(as_text=True)
        for width, height in re.findall(r'nephron-logo\.png[^>]*width="(\d+)" height="(\d+)"', home):
            self.assertEqual((int(width), int(height)), sizes["nephron-logo.png"])
        self.assertEqual(sizes["nephron-badge.png"][0], sizes["nephron-badge.png"][1])      # a round badge is square
        self.assertEqual(sizes["favicon-64.png"], (64, 64))
        self.assertEqual(sizes["apple-touch-icon.png"], (180, 180))
        # The mark is a wide shape: cropping must not have changed its proportions (the master is the untouched original).
        master_w, master_h = sizes["nephron-logo-master.png"]
        crop_w, crop_h = sizes["nephron-logo.png"]
        self.assertLessEqual(crop_w, master_w)
        self.assertLessEqual(crop_h, master_h)
        self.assertEqual(colour_types["nephron-logo.png"], 6, "the logo lost its transparent background")   # 6 = RGBA

    def test_public_pages_load_nothing_from_other_sites(self):
        import re
        for path in ("/", "/about", "/does-not-exist"):
            page = self.client.get(path).get_data(as_text=True)
            for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', page):
                self.fail(f"{path} loads {url} from another site")

    def test_error_pages_say_what_to_do_next(self):
        self.assertIn(b"Check the address for typing mistakes", self.client.get("/does-not-exist").data)
        with self.assertLogs(self.app.logger, level="ERROR"):
            page = self.client.get("/_test/database-error").get_data(as_text=True)
        self.assertIn("contact your system administrator", page)

    def test_design_previews_do_not_exist_when_not_debugging(self):
        self.assertNotIn("design", self.app.blueprints)
        for path in ("/design/", "/design/login", "/design/dashboard", "/design/assessment",
                     "/design/result", "/design/states"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertNotIn("Design previews", self.client.get("/").get_data(as_text=True))

    def test_style_guide_hidden_when_not_debugging(self):
        self.assertEqual(self.client.get("/style-guide").status_code, 404)

    def test_missing_secret_key_stops_startup(self):
        from config import validate_config
        with self.assertRaises(RuntimeError):
            validate_config({"SECRET_KEY": None, "DB_NAME": "nephron"})
        with self.assertRaises(RuntimeError):
            validate_config({"SECRET_KEY": "x", "DB_NAME": "bad name; DROP"})


class _PageInspector(HTMLParser):
    """Collects the facts the accessibility checks need from one page of HTML."""

    def __init__(self):
        super().__init__()
        self.ids, self.label_targets, self.images_without_alt = [], set(), []
        self.dead_links, self.fields, self.buttons = [], [], []
        self._button = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "label" and "for" in a:
            self.label_targets.add(a["for"])
        # An image needs a text alternative. An EMPTY alt is right for a purely decorative picture, but only if it is also hidden from screen readers.
        if tag == "img" and ("alt" not in a or (a["alt"] == "" and a.get("aria-hidden") != "true")):
            self.images_without_alt.append(a.get("src"))
        if tag == "a" and a.get("href") == "#" and "data-preview-link" not in a:
            self.dead_links.append(a)
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "radio", "submit"):
            self.fields.append(a)
        if tag == "input" and a.get("type") == "radio":
            pass   # radios are labelled by the <label class="choice"> that wraps them
        if tag == "button":
            self._button = {"aria-label": a.get("aria-label"), "text": ""}
            self.buttons.append(self._button)

    def handle_data(self, data):
        if self._button is not None:
            self._button["text"] += data.strip()

    def handle_endtag(self, tag):
        if tag == "button":
            self._button = None


class DesignPreviewTests(unittest.TestCase):
    """The design previews exist only in debug mode. They must still be honest and accessible."""

    PAGES = ("/design/", "/design/login", "/design/login?state=error", "/design/register",
             "/design/dashboard", "/design/dashboard?data=sample",
             "/design/assessment", "/design/result", "/design/result?level=low",
             "/design/states", "/style-guide")

    @classmethod
    def setUpClass(cls):
        cls.app = create_app({"DEBUG": True})
        cls.client = cls.app.test_client()

    def test_previews_are_registered_only_in_debug_mode(self):
        self.assertIn("design", self.app.blueprints)

    def test_every_preview_page_loads_and_says_it_is_a_preview(self):
        for path in self.PAGES:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(b"Design preview", response.data, path)
            self.assertIn(b"Sample values only", response.data, path)

    def test_no_dead_links(self):
        # A link that goes nowhere must say so (data-preview-link shows a "Preview only" message).
        for path in self.PAGES:
            inspector = _PageInspector()
            inspector.feed(self.client.get(path).get_data(as_text=True))
            self.assertEqual(inspector.dead_links, [], path)

    def test_images_have_alt_text_and_ids_are_unique(self):
        for path in self.PAGES:
            inspector = _PageInspector()
            inspector.feed(self.client.get(path).get_data(as_text=True))
            self.assertEqual(inspector.images_without_alt, [], path)
            duplicates = {i for i in inspector.ids if inspector.ids.count(i) > 1}
            self.assertEqual(duplicates, set(), f"{path}: repeated ids {duplicates}")

    def test_every_form_field_has_a_label(self):
        for path in self.PAGES:
            inspector = _PageInspector()
            inspector.feed(self.client.get(path).get_data(as_text=True))
            for field in inspector.fields:
                labelled = field.get("id") in inspector.label_targets or field.get("aria-label")
                self.assertTrue(labelled, f"{path}: unlabelled field {field}")

    def test_every_button_has_a_name(self):
        for path in self.PAGES:
            inspector = _PageInspector()
            inspector.feed(self.client.get(path).get_data(as_text=True))
            for button in inspector.buttons:
                self.assertTrue(button["text"] or button["aria-label"], f"{path}: nameless button")

    def test_previews_never_use_diagnostic_wording(self):
        for path in self.PAGES:
            text = self.client.get(path).get_data(as_text=True).lower()
            for phrase in ("you have ckd", "you have kidney disease", "confirms kidney disease",
                           "diagnosed with", "confidence score", "you are healthy", "you are safe"):
                self.assertNotIn(phrase, text, f"{phrase!r} found on {path}")

    def test_risk_is_always_shown_with_words_and_an_icon_not_colour_alone(self):
        import re
        badge_pattern = re.compile(r'<span class="badge (risk-badge-(?:high|low))[^"]*">(.*?)</span>', re.S)
        found = 0
        for path in ("/design/dashboard", "/design/dashboard?data=sample", "/design/result",
                     "/design/result?level=low", "/design/states", "/about", "/style-guide"):
            html = self.client.get(path).get_data(as_text=True)
            for kind, inner in badge_pattern.findall(html):
                found += 1
                self.assertIn("<svg", inner, f"{path}: {kind} badge has no icon")
                words = "High Preliminary Risk" if kind.endswith("high") else "Low Preliminary Risk"
                self.assertIn(words, inner, f"{path}: {kind} badge has no words")
        self.assertGreater(found, 5)   # make sure the check actually looked at badges

    def test_result_wording_for_high_and_low(self):
        high = self.client.get("/design/result?level=high").get_data(as_text=True)
        self.assertIn("High Preliminary Risk", high)
        self.assertIn("Consider professional evaluation", high)
        self.assertIn("not a diagnosis", high)
        low = self.client.get("/design/result?level=low").get_data(as_text=True)
        self.assertIn("Low Preliminary Risk", low)
        self.assertIn("does not mean you are free of kidney disease", low)
        for html in (high, low):
            self.assertIn(self.app.config["MEDICAL_DISCLAIMER"], html)

    def test_previews_use_no_database(self):
        from unittest import mock
        with mock.patch("db.get_db", side_effect=AssertionError("a preview touched the database")):
            for path in self.PAGES:
                self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_unknown_result_variant_falls_back_safely(self):
        self.assertEqual(self.client.get("/design/result?level=<script>").status_code, 200)
        self.assertNotIn(b"<script>", self.client.get("/design/result?level=<script>").data)


class MigrationRunnerTests(unittest.TestCase):
    def test_statements_are_split_and_comments_removed(self):
        from init_db import split_sql_statements
        sql = "-- a comment\nCREATE TABLE a (id INT);\n\nCREATE TABLE b (id INT);\n"
        self.assertEqual(
            split_sql_statements(sql),
            ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"],
        )


    def test_migration_runs_once_and_is_then_skipped(self):
        """Uses a recording fake connection, so no MySQL is needed."""
        import tempfile
        from unittest import mock
        import init_db

        applied_files = []     # what the fake "schema_migrations" table holds
        executed_sql = []      # every statement the runner sends

        class FakeCursor:
            def execute(self, sql, params=None):
                executed_sql.append(sql.strip())
                if sql.strip().startswith("INSERT INTO schema_migrations"):
                    applied_files.append(params[0])
            def fetchall(self):
                return [(name,) for name in applied_files]
            def close(self):
                pass

        class FakeConnection:
            def cursor(self):
                return FakeCursor()
            def commit(self):
                pass
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "002_second.sql"), "w") as file:
                file.write("CREATE TABLE second_table (id INT);")
            with open(os.path.join(folder, "001_first.sql"), "w") as file:
                file.write("-- first\nCREATE TABLE first_table (id INT);")

            with mock.patch.object(init_db, "MIGRATIONS_DIR", folder), \
                 mock.patch.object(init_db.mysql.connector, "connect", return_value=FakeConnection()):
                init_db.apply_migrations()
                self.assertEqual(applied_files, ["001_first.sql", "002_second.sql"])  # number order
                statements_after_first_run = len(executed_sql)
                init_db.apply_migrations()  # second run: nothing new should be applied
                self.assertEqual(applied_files, ["001_first.sql", "002_second.sql"])
                new_statements = executed_sql[statements_after_first_run:]
                self.assertFalse(any("first_table" in sql or "second_table" in sql for sql in new_statements))



class DataHonestyTests(unittest.TestCase):
    """
    Nephron's rule: a chart or number is only drawn from real assessment data.
    With no data the page must show an empty state, and any made-up data must be labelled.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = create_app({"DEBUG": True}).test_client()

    def page(self, path):
        return self.client.get(path).get_data(as_text=True)

    def test_real_state_dashboard_draws_no_data_visuals_and_no_sample_tags(self):
        html = self.page("/design/dashboard")
        for words in ("No assessments yet", "Chart appears when sufficient data exists", "No result yet", "No activity yet", "No results to summarise yet"):
            self.assertIn(words, html)
        # "Kidney health, by the numbers" always draws its own rings - population statistics, not this person's
        # data (see the equivalent note in tests/test_dashboard.py) - so it is excluded here.
        without_ckd_facts = re.sub(r'<aside class="dash-ckd[^>]*aria-labelledby="ckd-facts-heading".*?</aside>', "", html, flags=re.S)
        self.assertIn("ckd-facts-heading", html)
        self.assertNotIn("ckd-facts-heading", without_ckd_facts)
        for drawn in ('class="chart-line"', 'class="ring-value"', "donut-segment", "timeline-item timeline-", "activity-item",
                      'class="sparkline"', 'class="sample-tag"', "risk-pill"):
            self.assertNotIn(drawn, without_ckd_facts, f"{drawn} appears with no assessment data")
        self.assertRegex(html, r'class="stat-value"\s*>0<')                   # the honest count is zero

    def test_sample_dashboard_is_labelled_on_every_chart_card(self):
        html = self.page("/design/dashboard?data=sample")
        self.assertGreaterEqual(html.count('class="sample-tag"'), 2)   # trend and summary cards
        for drawn in ('class="chart-line"', 'class="ring-value"', "donut-segment", "activity-item", 'class="sparkline"'):
            self.assertIn(drawn, html)
        self.assertIn('data-count-to="3"', html)                       # 3 sample records, counted by visuals.py

    # ---- the blueprint's dashboard rules: no fake notification count, no invented statistics ----
    def test_dashboard_has_no_notification_count_in_either_state(self):
        import re
        for path in ("/design/dashboard", "/design/dashboard?data=sample"):
            html = self.page(path)
            bell = re.search(r'aria-label="Notifications">(.*?)</a>', html, re.S).group(1)
            self.assertNotRegex(bell, r"\d", f"{path}: the bell shows a number")
            self.assertNotIn("notification-count", html)

    def test_recent_activity_only_lists_real_assessments(self):
        html = self.page("/design/dashboard?data=sample")
        self.assertEqual(html.count('class="activity-title">Assessment completed<'), 3)
        for invented in ("Profile Updated", "Lab Result Uploaded"):
            self.assertNotIn(invented, html)                            # no such records exist in this phase

    def test_risk_is_only_ever_low_or_high(self):
        for path in ("/design/dashboard", "/design/dashboard?data=sample", "/design/result", "/design/result?level=low", "/", "/about"):
            self.assertNotIn("Moderate", self.page(path), path)         # the model is binary

    def test_no_assessment_means_no_invented_latest_result(self):
        html = self.page("/design/dashboard")
        self.assertNotIn("Preliminary Risk", html)                      # neither classification is named without a result

    def test_a_waiting_period_disables_starting_a_new_assessment(self):
        html = self.page("/design/dashboard?data=sample&locked=1")
        self.assertIn("Your next screening opens on", html)
        self.assertIn('aria-disabled="true"', html)
        self.assertNotIn("Start Assessment</a>", html)                  # no working link to start while locked

    def test_result_page_always_says_its_values_are_sample_values(self):
        for path in ("/design/result", "/design/result?level=low"):
            self.assertGreaterEqual(self.page(path).count('class="sample-tag"'), 3, path)

    def test_public_pages_show_no_invented_percentages(self):
        import re
        for path in ("/", "/about"):
            html = self.page(path)
            self.assertIsNone(re.search(r"\d+(\.\d+)? percent", html), f"{path} announces a percentage")
            self.assertNotIn('class="chart-line"', html)

    def test_no_confidence_score_wording_anywhere(self):
        for path in ("/design/dashboard", "/design/dashboard?data=sample", "/design/result", "/", "/about", "/style-guide"):
            self.assertNotIn("confidence", self.page(path).lower(), path)

    def test_states_table_has_its_rows_and_says_they_are_sample_data(self):
        import re
        html = self.page("/design/states")
        body = re.search(r"<tbody>(.*?)</tbody>", html, re.S).group(1)
        self.assertEqual(body.count("<tr>"), 3)                      # it once rendered silently empty
        self.assertIn('class="sample-tag"', html)
        self.assertNotIn("31.0%", html)                               # numbers are formatted like the rest of the page

    def test_register_offers_both_roles_as_labelled_choices(self):
        html = self.page("/design/register")
        self.assertIn('value="general"', html)
        self.assertIn('value="professional"', html)
        self.assertIn("General user", html)
        self.assertIn("Healthcare professional", html)
        self.assertGreaterEqual(html.count("chip-required"), 3)


class NoSilentEmptinessTests(unittest.TestCase):
    """
    Jinja quietly prints nothing for a variable a route forgot to pass. That once left a table
    with no rows and no error. Strict mode turns any such slip into a failing test.
    """

    def test_no_page_uses_an_undefined_variable(self):
        from jinja2 import StrictUndefined
        app = create_app({"DEBUG": True})
        app.jinja_env.undefined = StrictUndefined
        client = app.test_client()
        for path in ("/", "/about", "/style-guide", "/design/", "/design/login", "/design/login?state=error",
                     "/design/register", "/design/dashboard", "/design/dashboard?data=sample",
                     "/design/assessment", "/design/result", "/design/result?level=low", "/design/states"):
            self.assertEqual(client.get(path).status_code, 200, f"{path} uses a variable that was never passed to it")


class ReducedMotionTests(unittest.TestCase):
    def test_reduced_motion_rule_exists_and_covers_the_new_animations(self):
        with open("static/css/base.css", encoding="utf-8") as css_file:
            base = css_file.read()
        self.assertIn("prefers-reduced-motion", base)
        self.assertIn("animation-duration: 0.01ms", base.replace("!important", ""))


if __name__ == "__main__":
    unittest.main()
