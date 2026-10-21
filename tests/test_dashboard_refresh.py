"""
test_dashboard_refresh.py - the October 2026 refresh:
  * both dashboards: the profile card and quick actions are gone and the kidney-health facts take their place;
  * the daily checklist sits on the General User dashboard right under the checklist-days card, and ticks without a
    reload (JSON for the page's script; a plain post goes back to the page it came from);
  * a professional sees a shared result's answers and factors - and only for a result actually shared with them;
  * the phone navigation drawer sits above its backdrop, so its links can be tapped.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DashboardTests(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.post("/screening", answers(), client=self.member, token_from="/screening")

    def test_profile_and_quick_actions_are_replaced_by_the_kidney_facts(self):
        page = self.text(self.member.get("/dashboard"))
        for gone in ("Quick Actions", "quick-action", "profile-row"):
            self.assertNotIn(gone, page)
        side = page.index('class="dash-side"')
        self.assertLess(side, page.index('id="ckd-facts-heading"'))                       # the facts are in the right-hand column,
        self.assertLess(page.index('id="ckd-facts-heading"'), page.index('id="activity-heading"'))   # above recent activity
        self.assertIn("Kidney health in the Philippines", page)

    def test_the_checklist_is_right_under_the_checklist_days_card(self):
        page = self.text(self.member.get("/dashboard"))
        days, checklist = page.index('id="checklist-days-heading"'), page.index('id="checklist"')
        self.assertLess(days, checklist)
        self.assertNotIn("Helpful Resources", page[days:checklist])                         # nothing in between
        self.assertIn('name="next" value="/dashboard"', page)                             # a tick without JavaScript comes back here
        self.assertIn("js/checklist.js", page)

    def test_without_a_screening_there_is_no_checklist_but_the_facts_still_show(self):
        page = self.text(self.signed_in(email="new@example.com").get("/dashboard"))
        self.assertNotIn('id="checklist"', page)
        self.assertIn('id="ckd-facts-heading"', page)

    def test_the_professional_home_has_the_facts_instead_of_profile_and_quick_actions(self):
        page = self.text(self.signed_in(**self.professional_details()).get("/professional"))
        for gone in ("Quick Actions", "quick-action", "profile-row"):
            self.assertNotIn(gone, page)
        self.assertLess(page.index('id="ckd-facts-heading"'), page.index('id="side-activity-heading"'))


class ChecklistToggleTests(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.post("/screening", answers(), client=self.member, token_from="/screening")
        self.tip = re.search(r"/follow-up/checklist/([a-z_]+)", self.text(self.member.get("/dashboard"))).group(1)

    def test_the_page_script_gets_todays_real_totals_back(self):
        response = self.post(f"/follow-up/checklist/{self.tip}", {"is_complete": "1", "next": "/dashboard"}, client=self.member,
                             token_from="/dashboard", headers={"X-Requested-With": "fetch"})
        data = response.get_json()
        self.assertEqual((response.status_code, data["is_complete"], data["done"]), (200, True, 1))
        self.assertGreater(data["total"], 1)
        self.assertIn('<strong data-checklist-done>1</strong>', self.text(self.member.get("/dashboard")))
        undo = self.post(f"/follow-up/checklist/{self.tip}", {"is_complete": "0"}, client=self.member, token_from="/dashboard",
                         headers={"X-Requested-With": "fetch"}).get_json()
        self.assertEqual((undo["is_complete"], undo["done"]), (False, 0))

    def test_a_plain_tick_goes_back_to_the_page_it_came_from(self):
        response = self.post(f"/follow-up/checklist/{self.tip}", {"is_complete": "1", "next": "/dashboard"}, client=self.member, token_from="/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard#checklist"), response.headers["Location"])

    def test_a_tick_never_sends_anyone_to_another_site(self):
        for target in ("//evil.example/x", "https://evil.example/", "javascript:alert(1)"):
            response = self.post(f"/follow-up/checklist/{self.tip}", {"is_complete": "1", "next": target}, client=self.member, token_from="/dashboard")
            self.assertTrue(response.headers["Location"].endswith("/follow-up#checklist"), (target, response.headers["Location"]))

    def test_the_follow_up_page_shows_the_same_list(self):
        page = self.text(self.member.get("/follow-up"))
        self.assertIn('id="checklist-heading"', page)          # old links to #checklist-heading still land on it
        self.assertIn(f"/follow-up/checklist/{self.tip}", page)


class SharedResultTests(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.post("/screening", answers(), client=self.patient, token_from="/screening")
        self.professional = self.signed_in(**self.professional_details())
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.assessment_id = self.app.extensions["assessment_store"].list_assessments(self.patient_id)[0]["assessment_id"]
        self.url = f"/patients/{self.patient_id}/assessments/{self.assessment_id}"

    def test_the_professional_sees_the_answers_and_the_factors(self):
        response = self.professional.get(self.url)
        page = self.text(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ana Reyes's answers", page)
        self.assertIn("Family history of kidney disease", page)
        self.assertIn("What raised the estimate", page)
        for patient_wording in ("Your answer", "your answer was", "your estimate"):
            self.assertNotIn(patient_wording, page)                                           # worded for the professional

    def test_the_history_and_the_shared_list_link_to_it(self):
        self.assertIn(self.url, self.text(self.professional.get(f"/patients/{self.patient_id}")))
        self.assertIn(self.url, self.text(self.professional.get("/patients")))

    def test_a_professional_it_was_not_shared_with_gets_not_found(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        self.assertEqual(other.get(self.url).status_code, 404)

    def test_someone_elses_result_cannot_be_opened_through_a_shared_patient(self):
        stranger = self.signed_in(email="stranger@example.com")
        self.post("/screening", answers(), client=stranger, token_from="/screening")
        stranger_id = self.store.find_by_email("stranger@example.com")["user_id"]
        theirs = self.app.extensions["assessment_store"].list_assessments(stranger_id)[0]["assessment_id"]
        self.assertEqual(self.professional.get(f"/patients/{self.patient_id}/assessments/{theirs}").status_code, 404)

    def test_access_ends_when_the_patient_ends_the_sharing(self):
        self.post(f"/share/revoke/{self.professional_id}", {}, client=self.patient, token_from="/share")
        self.assertEqual(self.professional.get(self.url).status_code, 404)

    def test_the_patient_and_visitors_cannot_use_the_professional_page(self):
        self.assertEqual(self.patient.get(self.url).status_code, 403)
        self.assertEqual(self.new_browser().get(self.url).status_code, 302)


class MobileDrawerTests(unittest.TestCase):
    def test_the_open_drawer_sits_above_its_backdrop(self):
        with open(os.path.join(ROOT, "static", "css", "layout.css"), encoding="utf-8") as handle:
            css = handle.read()
        backdrop = int(re.search(r"\.drawer-backdrop\s*\{[^}]*z-index:\s*(\d+)", css).group(1))
        phone_block = css[css.index("@media (max-width: 63.99rem)"):]
        rail = int(re.search(r"\.rail\s*\{[^}]*z-index:\s*(\d+)", phone_block).group(1))
        self.assertGreater(rail, backdrop)


if __name__ == "__main__":
    unittest.main()
