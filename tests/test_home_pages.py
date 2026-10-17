"""
Checks for the Home page, the How it works walkthrough and the animation system behind them.
The promises worth guarding: the pages are complete without motion or scripting, no illustration shows an invented
number, and every "before" animation state is gated so it can never leave content invisible.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = ("Provide your information", "The model estimates your risk", "See what affected your result",
         "Share for review, if you choose", "Screen again later")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def split_selectors(group):
    """'a, b:is(c, d)' -> ['a', 'b:is(c, d)'] - commas inside parentheses do not separate selectors."""
    parts, depth, current = [], 0, ""
    for char in group:
        depth += (char == "(") - (char == ")")
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    return parts + [current.strip()]


def visible_text(html):
    """The page as a person reads it: no tags, no attribute values (an SVG path's numbers are not 'shown')."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class HomePageTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.html = self.text(self.client.get("/"))

    def test_the_headline_reads_as_one_phrase_the_animation_does_not_break_up(self):
        self.assertIn("Early kidney health risk screening,", self.html)

    def test_the_journey_has_five_steps_each_with_its_own_picture(self):
        self.assertEqual(self.html.count('class="journey-step"'), 5)
        self.assertEqual(self.html.count('class="journey-visual"'), 5)
        self.assertIn('data-animate="journey"', self.html)
        self.assertIn("See the full walkthrough", self.html)

    def test_the_journey_says_what_the_walkthrough_says_about_sharing(self):
        self.assertIn("You agree before anything is shared with a professional", self.html)

    def test_every_picture_says_it_is_an_illustration(self):
        text = visible_text(self.html)
        self.assertIn("Illustrations only, not real results", text)
        self.assertGreaterEqual(self.html.count('class="sc-tag"'), 1)
        for ring in re.findall(r'<div class="ring mini-ring[^>]*aria-label="([^"]+)"', self.html):
            self.assertIn("Illustration", ring)

    def test_no_illustration_shows_an_invented_number(self):
        text = visible_text(self.html)
        self.assertIsNone(re.search(r"\d\s*%", text), "a percentage is drawn on the public home page")
        self.assertIsNone(re.search(r"\d+(\.\d+)? percent", self.html))
        self.assertNotIn("data-count-up", self.html)              # a number that "arrives" at a figure would be an invented figure

    def test_the_call_to_action_changes_for_someone_already_signed_in(self):
        self.assertIn("Create your account", self.html)
        member = self.signed_in()
        page = self.text(member.get("/"))
        self.assertIn("Go to my home page", page)
        self.assertNotIn("Create your account", page)

    def test_a_professional_is_sent_to_their_own_home(self):
        from flask import url_for
        professional = self.signed_in(**self.professional_details())
        with self.app.test_request_context():
            their_home, general_home = url_for("account.professional_home"), url_for("account.dashboard")
        page = self.text(professional.get("/"))
        self.assertIn(f'href="{their_home}"', page)
        self.assertNotIn(f'href="{general_home}"', page.split('class="site-main')[1])       # not the patient dashboard

    def test_the_hero_keeps_the_disclaimer_language(self):
        self.assertIn("Screening, not diagnosis", self.html)
        self.assertIn("What Nephron does not do", self.html)


class AboutPageTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.html = self.text(self.client.get("/about"))

    def test_the_page_keeps_its_title_and_disclaimer(self):
        self.assertIn("How Nephron works", self.html)
        self.assertIn("does not provide a medical diagnosis", self.html.replace("\n", " "))
        self.assertIn("Values read from a laboratory document are extracted text", self.html)

    def test_all_five_steps_are_there_with_their_reviewed_wording(self):
        for title in STEPS:
            self.assertIn(title, self.html)
        self.assertIn("It does not explain the cause of any person", self.html)
        self.assertIn("you agree before anything is sent", self.html)

    def test_each_step_has_a_picture_in_the_stage_and_one_above_the_step_for_phones(self):
        self.assertEqual(self.html.count("data-walk-step"), 5)
        self.assertEqual(self.html.count("data-walk-scene"), 5)
        self.assertEqual(self.html.count('class="walk-inline"'), 5)
        self.assertGreaterEqual(self.html.count('class="sc-tag"'), 10)          # one on every scene, both copies

    def test_the_pictures_are_decorative_and_the_steps_are_the_content(self):
        self.assertRegex(self.html, r'class="walk-stage-col" aria-hidden="true"')
        self.assertEqual(self.html.count('class="walk-inline" data-animate="fade-in" aria-hidden="true"'), 5)

    def test_no_picture_shows_an_invented_number(self):
        text = visible_text(self.html)
        self.assertIsNone(re.search(r"\d\s*%", re.sub(r"Reading a result.*?not a real result\.", "", text)), "a percentage is drawn in a walkthrough picture")

    def test_the_consent_scene_matches_what_sharing_really_asks_for(self):
        self.assertIn("I understand and agree to share", self.html)
        self.assertIn("Nothing is visible until they accept", self.html)
        self.assertIn("You can end access at any time", self.html)


class AnimationSystemTests(AppTestCase):
    def _ok(self, path):
        response = self.client.get(path)
        self.addCleanup(response.close)                                       # a static file response holds the file open
        self.assertEqual(response.status_code, 200, path)

    def test_the_scripting_flag_is_an_external_file_in_the_head_not_an_inline_script(self):
        html = self.text(self.client.get("/"))
        self.assertIn("js/js-flag.js", html)
        self.assertLess(html.index("js/js-flag.js"), html.index("css/tokens.css"))       # before anything paints
        self.assertNotIn("<script>", html)
        self._ok("/static/js/js-flag.js")

    def test_motion_and_home_stylesheets_and_script_load_once_on_every_public_page(self):
        for path in ("/", "/about"):
            html = self.text(self.client.get(path))
            for asset in ("css/motion.css", "css/home.css", "js/motion.js"):
                self.assertEqual(html.count(asset), 1, f"{path} {asset}")
                self._ok("/static/" + asset)

    def test_nothing_is_hidden_unless_scripting_is_on_and_motion_is_welcome(self):
        """The property that keeps content readable: every 'before' state is inside the no-preference media query AND behind html.js."""
        for name in ("motion.css", "home.css"):
            css = read("static", "css", name)
            marker = "@media (prefers-reduced-motion: no-preference)"
            self.assertIn(marker, css, name)
            before = css[:css.index(marker)]
            self.assertNotIn("opacity: 0;", before, f"{name}: content hidden outside the no-preference block")
            after = css[css.index(marker):]
            for rule in re.findall(r"([^{}]+)\{[^{}]*(?:opacity: 0[;} ]|scaleX\(0\)|scale\(0\)|stroke-dashoffset: 1)", after):
                for selector in split_selectors(rule):
                    if ":not(.is-in)" in selector:
                        self.assertTrue(selector.startswith(".js "), f"{name}: '{selector}' hides without the .js gate")

    def test_the_walkthrough_falls_back_to_pictures_above_each_step_without_scripting(self):
        css = read("static", "css", "home.css")
        for rule in ("html:not(.js) .walk-stage-col { display: none; }", "html:not(.js) .walk-inline { display: block; }"):
            self.assertIn(rule, css)

    def test_the_script_only_ever_adds_a_class_or_a_variable(self):
        js = read("static", "js", "motion.js")
        self.assertIn('window.matchMedia("(prefers-reduced-motion: reduce)")', js)
        self.assertIn("IntersectionObserver", js)
        self.assertIn("if (reduce || !hasObserver)", js)                        # no observer support = show everything
        self.assertNotIn("innerHTML", js)
        self.assertNotIn(".style.opacity", js)

    def test_the_project_wide_reduced_motion_rule_is_still_in_force(self):
        self.assertIn("prefers-reduced-motion: reduce", read("static", "css", "base.css"))


class PublicLinksTests(AppTestCase):
    def test_every_link_on_the_home_and_about_pages_goes_somewhere_real(self):
        for path in ("/", "/about"):
            html = self.text(self.client.get(path))
            for href in sorted(set(re.findall(r'href="(/[^"#]*)"', html))):
                if href.startswith("/static/"):
                    continue
                self.assertLess(self.client.get(href).status_code, 400, f"{path} links to {href}")


if __name__ == "__main__":
    unittest.main()
