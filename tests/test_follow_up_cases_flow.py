"""
Checks for /follow-up-cases (routes/authorization_routes.py follow_up_cases). The filtering logic itself is
covered by tests/test_professional_overview.py; these confirm the page renders it.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402


class FollowUpCasesTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)},
                 client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.post(f"/patients/{self.patient_id}/appointments", {"date": "2030-11-10", "time": "14:30", "purpose": "Recheck labs"},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")

    def test_lists_the_scheduled_appointment_as_pending(self):
        page = self.text(self.professional.get("/follow-up-cases"))
        self.assertIn("Ana Reyes", page)
        self.assertIn("Recheck labs", page)
        self.assertIn("Pending", page)

    def test_all_tab_is_the_default(self):
        page = self.text(self.professional.get("/follow-up-cases"))
        self.assertRegex(page, r'tab-link is-active"[^>]*>\s*All')

    def test_pending_tab_shows_it_due_tab_does_not(self):
        page_pending = self.text(self.professional.get("/follow-up-cases?status=pending"))
        self.assertIn("Recheck labs", page_pending)
        page_due = self.text(self.professional.get("/follow-up-cases?status=due"))
        self.assertIn("No follow-up matches these filters", page_due)

    def test_completing_it_moves_it_to_the_completed_tab(self):
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        appointment_id = re.search(r"/appointments/(\d+)/complete", page).group(1)
        self.post(f"/patients/{self.patient_id}/appointments/{appointment_id}/complete", {},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page_completed = self.text(self.professional.get("/follow-up-cases?status=completed"))
        self.assertIn("Recheck labs", page_completed)
        page_pending = self.text(self.professional.get("/follow-up-cases?status=pending"))
        self.assertIn("No follow-up matches these filters", page_pending)

    def test_search_by_patient_name(self):
        page = self.text(self.professional.get("/follow-up-cases?q=Ana"))
        self.assertIn("Recheck labs", page)
        page_none = self.text(self.professional.get("/follow-up-cases?q=Nobody"))
        self.assertIn("No follow-up matches these filters", page_none)

    def test_a_different_professional_sees_none_of_this(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/follow-up-cases"))
        self.assertIn("No follow-up cases yet", page)

    def test_a_general_user_cannot_reach_it(self):
        # setUp() already signed in a general user (self.patient) - reuse it rather than registering a second
        # account with the same email, which would fail and leave a fresh client merely signed OUT (a 302),
        # masking the role check this test actually means to verify.
        self.assertEqual(self.patient.get("/follow-up-cases").status_code, 403)

    def test_an_invalid_date_period_falls_back_to_all_instead_of_crashing(self):
        response = self.professional.get("/follow-up-cases?date_period=not-real")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Recheck labs", self.text(response))

    def test_the_sidebar_now_links_to_it_instead_of_saying_coming_soon(self):
        page = self.text(self.professional.get("/professional"))
        self.assertIn('href="/follow-up-cases"', page)
        self.assertNotRegex(page, r'Follow-up<small>Coming soon</small>')


if __name__ == "__main__":
    unittest.main()


class FollowUpCalendarTests(FollowUpCasesTests):
    """The professional's Follow-up section also shows a month calendar of every appointment, each labelled with
    its own patient (setUp schedules one for Ana Reyes on 2030-11-10 at 14:30)."""

    def test_the_appointment_appears_on_its_own_day_with_the_patient_name(self):
        page = self.text(self.professional.get("/follow-up-cases?year=2030&month=11"))
        self.assertIn("November 2030", page)
        self.assertIn("Ana Reyes - Recheck labs", page)

    def test_a_different_month_does_not_show_it(self):
        page = self.text(self.professional.get("/follow-up-cases?year=2030&month=12"))
        self.assertIn("December 2030", page)
        self.assertNotIn("Ana Reyes - Recheck labs", page)

    def test_previous_and_next_month_links_wrap_the_year(self):
        page = self.text(self.professional.get("/follow-up-cases?year=2030&month=12"))
        self.assertIn("year=2031&amp;month=1", page)
        self.assertIn("year=2030&amp;month=11", page)

    def test_a_nonsense_month_falls_back_to_this_month_instead_of_crashing(self):
        self.assertEqual(self.professional.get("/follow-up-cases?year=abc&month=13").status_code, 200)

    def test_the_calendar_is_not_narrowed_by_the_table_filters(self):
        page = self.text(self.professional.get("/follow-up-cases?year=2030&month=11&status=completed"))
        self.assertIn("Ana Reyes - Recheck labs", page)                 # still on the calendar
        self.assertIn("No follow-up matches these filters", page)       # while the filtered table is empty
