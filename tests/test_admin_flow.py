"""
Checks for the administrator side (routes/admin_routes.py): only an administrator gets in; accounts can be switched
off and on (never deleted, never one's own); a switched-off account cannot sign in and is signed out at once;
professionals can be verified; and no admin page ever shows anyone's health information.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase, PASSWORD  # noqa: E402


class AdminTestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()                                                   # ana@example.com
        self.pro = self.signed_in(**self.professional_details())                          # dr.cruz@example.com
        self.admin = self.signed_in(email="admin@example.com", full_name="Site Admin")
        self.admin_id = self.store.find_by_email("admin@example.com")["user_id"]
        self.store.set_admin(self.admin_id, True)
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.pro_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]


class AccessTests(AdminTestCase):
    def test_only_an_administrator_can_open_the_admin_pages(self):
        for path in ("/admin", "/admin/users", "/admin/professionals"):
            self.assertEqual(self.admin.get(path).status_code, 200, path)
            self.assertEqual(self.patient.get(path).status_code, 403, path)
            self.assertEqual(self.pro.get(path).status_code, 403, path)
            self.assertEqual(self.new_browser().get(path).status_code, 302, path)       # signed out: to the sign-in page

    def test_an_administrator_signs_in_to_the_admin_overview(self):
        browser = self.new_browser()
        response = self.post("/login", {"email": "admin@example.com", "password": PASSWORD}, client=browser, token_from="/login")
        self.assertTrue(response.headers["Location"].endswith("/admin"))

    def test_the_rail_shows_the_admin_items(self):
        page = self.text(self.admin.get("/admin"))
        for label in ("Accounts", "Professional verification"):
            self.assertIn(label, page)
        self.assertIn("Administrator", page)


class AccountTests(AdminTestCase):
    def test_switching_an_account_off_stops_sign_in_and_ends_the_open_session(self):
        self.post(f"/admin/users/{self.patient_id}/deactivate", {}, client=self.admin, token_from="/admin/users")
        self.assertFalse(self.store.find_by_id(self.patient_id)["is_active"])
        self.assertEqual(self.patient.get("/dashboard").status_code, 302)                # signed out at once
        response = self.post("/login", {"email": "ana@example.com", "password": PASSWORD}, client=self.new_browser(), token_from="/login")
        self.assertEqual(response.status_code, 403)
        self.assertIn("This account is not active", self.text(response))

    def test_a_wrong_password_never_reveals_that_an_account_is_switched_off(self):
        self.store.set_active(self.patient_id, False)
        response = self.post("/login", {"email": "ana@example.com", "password": "wrong-password-here"}, client=self.new_browser(), token_from="/login")
        self.assertNotIn("not active", self.text(response))

    def test_switching_it_on_again_restores_sign_in(self):
        self.store.set_active(self.patient_id, False)
        self.post(f"/admin/users/{self.patient_id}/reactivate", {}, client=self.admin, token_from="/admin/users")
        response = self.post("/login", {"email": "ana@example.com", "password": PASSWORD}, client=self.new_browser(), token_from="/login")
        self.assertEqual(response.status_code, 302)

    def test_an_administrator_cannot_switch_off_their_own_account(self):
        self.post(f"/admin/users/{self.admin_id}/deactivate", {}, client=self.admin, token_from="/admin/users")
        self.assertTrue(self.store.find_by_id(self.admin_id)["is_active"])

    def test_the_actions_are_post_only_and_need_a_csrf_token(self):
        self.assertEqual(self.admin.get(f"/admin/users/{self.patient_id}/deactivate").status_code, 405)
        self.assertEqual(self.admin.post(f"/admin/users/{self.patient_id}/deactivate").status_code, 400)
        self.assertTrue(self.store.find_by_id(self.patient_id)["is_active"])

    def test_a_next_address_off_the_site_is_never_followed(self):
        response = self.post(f"/admin/users/{self.patient_id}/deactivate", {"next": "https://evil.example.com/"}, client=self.admin, token_from="/admin/users")
        self.assertNotIn("evil.example.com", response.headers["Location"])

    def test_search_and_filters(self):
        page = self.text(self.admin.get("/admin/users?role=professional"))
        self.assertIn("dr.cruz@example.com", page)
        self.assertNotIn("ana@example.com", page)
        self.store.set_active(self.patient_id, False)
        self.assertIn("ana@example.com", self.text(self.admin.get("/admin/users?status=inactive")))
        self.assertIn("ana@example.com", self.text(self.admin.get("/admin/users?q=ana")))

    def test_a_patient_records_shadow_account_is_never_listed(self):
        self.post("/patient-records/new", {"full_name": "Shadow Person", "date_of_birth": "1980-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                  client=self.pro, token_from="/patient-records/new")
        self.assertNotIn("Shadow Person", self.text(self.admin.get("/admin/users")))


class VerificationTests(AdminTestCase):
    def test_a_new_professional_awaits_verification_and_can_be_verified(self):
        self.assertIn("Dr. Luis Cruz", self.text(self.admin.get("/admin/professionals")))
        self.post(f"/admin/professionals/{self.pro_id}/verify", {"back": "pending"}, client=self.admin, token_from="/admin/professionals")
        self.assertEqual(self.store.find_by_id(self.pro_id)["verification_status"], "verified")
        self.assertIn("Dr. Luis Cruz", self.text(self.admin.get("/admin/professionals?status=verified")))

    def test_a_professional_can_be_marked_not_verified(self):
        self.post(f"/admin/professionals/{self.pro_id}/reject", {}, client=self.admin, token_from="/admin/professionals")
        self.assertEqual(self.store.find_by_id(self.pro_id)["verification_status"], "rejected")

    def test_a_general_user_cannot_be_verified_as_a_professional(self):
        response = self.post(f"/admin/professionals/{self.patient_id}/verify", {}, client=self.admin, token_from="/admin/professionals")
        self.assertEqual(response.status_code, 404)


class PrivacyTests(AdminTestCase):
    model = True

    def test_admin_pages_show_counts_but_never_anyones_answers_or_results(self):
        from test_screening_flow import answers
        self.post("/screening", answers(), client=self.patient, token_from="/screening")
        overview = self.text(self.admin.get("/admin"))
        self.assertRegex(overview, r'Assessments</p><p class="stat-value">1</p>')
        for page in (overview, self.text(self.admin.get("/admin/users"))):
            self.assertNotIn("Predicted Risk Probability", page)
            self.assertNotIn("/results/", page)
            self.assertIsNone(re.search(r"\d+\.\d%", page))                       # no probability anywhere


if __name__ == "__main__":
    unittest.main()


class WhatPatientsSeeTests(AdminTestCase):
    def test_the_share_search_shows_each_professionals_licence_check(self):
        self.assertIn("Licence not yet verified", self.text(self.patient.get("/share?q=cruz")))
        self.assertEqual(self.patient.get("/share/search?q=cruz").get_json()["results"][0]["verification_status"], "pending")
        self.store.set_verification(self.pro_id, "verified", None)
        self.assertIn("Licence verified", self.text(self.patient.get("/share?q=cruz")))

    def test_a_switched_off_professional_cannot_be_found_to_share_with(self):
        self.store.set_active(self.pro_id, False)
        self.assertEqual(self.patient.get("/share/search?q=cruz").get_json()["results"], [])


class ResetPasswordTests(AdminTestCase):
    def _reset(self):
        response = self.post(f"/admin/users/{self.patient_id}/reset-password", {}, client=self.admin, token_from="/admin/users")
        return response, re.search(r'id="temp-password-value">([^<]+)<', self.text(response)).group(1)

    def test_a_reset_shows_a_temporary_password_once_and_ends_every_session(self):
        response, temporary = self._reset()
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertGreaterEqual(len(temporary), 12)
        self.assertEqual(self.patient.get("/dashboard").status_code, 302)                     # signed out everywhere
        self.assertNotIn(temporary, self.text(self.admin.get("/admin/users")))                 # never shown again
        self.assertNotIn(temporary, self.text(self.admin.get("/admin/activity")))

    def test_the_person_must_choose_a_new_password_before_anything_else(self):
        _, temporary = self._reset()
        browser = self.new_browser()
        self.post("/login", {"email": "ana@example.com", "password": temporary}, client=browser, token_from="/login")
        for path in ("/dashboard", "/screening", "/history"):
            response = browser.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertTrue(response.headers["Location"].endswith("/account"), path)
        self.assertEqual(browser.get("/account").status_code, 200)
        self.post("/account/password", {"current_password": temporary, "new_password": "my-own-new-phrase-1"}, client=browser, token_from="/account")
        self.assertEqual(browser.get("/dashboard").status_code, 200)                          # free again
        self.assertFalse(self.store.find_by_id(self.patient_id)["must_change_password"])

    def test_the_old_password_no_longer_works(self):
        self._reset()
        response = self.post("/login", {"email": "ana@example.com", "password": PASSWORD}, client=self.new_browser(), token_from="/login")
        self.assertEqual(response.status_code, 200)                                            # refused, form shown again

    def test_an_administrator_cannot_reset_their_own_password_here(self):
        response = self.post(f"/admin/users/{self.admin_id}/reset-password", {}, client=self.admin, token_from="/admin/users")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.store.find_by_id(self.admin_id)["must_change_password"])


class ActivityLogTests(AdminTestCase):
    def test_sign_ins_failures_registrations_and_admin_actions_are_logged(self):
        self.post("/login", {"email": "ana@example.com", "password": PASSWORD}, client=self.new_browser(), token_from="/login")
        self.post("/login", {"email": "ana@example.com", "password": "wrong-password-here"}, client=self.new_browser(), token_from="/login")
        self.post(f"/admin/professionals/{self.pro_id}/verify", {}, client=self.admin, token_from="/admin/professionals")
        self.post(f"/admin/users/{self.patient_id}/deactivate", {}, client=self.admin, token_from="/admin/users")
        page = self.text(self.admin.get("/admin/activity"))
        for label in ("Created an account", "Signed in", "Failed sign-in", "Verified a professional", "Switched an account off"):
            self.assertIn(label, page)
        self.assertIn("Licence", page)

    def test_the_tabs_and_search_narrow_the_log(self):
        self.post(f"/admin/users/{self.patient_id}/deactivate", {}, client=self.admin, token_from="/admin/users")
        admin_only = self.text(self.admin.get("/admin/activity?group=admin"))
        self.assertIn("Switched an account off", admin_only)
        self.assertNotIn("Created an account", admin_only)
        self.assertIn("dr.cruz@example.com", self.text(self.admin.get("/admin/activity?q=cruz")))

    def test_only_an_administrator_can_read_the_log(self):
        self.assertEqual(self.patient.get("/admin/activity").status_code, 403)


class KpiTests(AdminTestCase):
    model = True

    def test_people_screened_higher_risk_and_age_groups_count_each_person_once(self):
        from test_screening_flow import answers
        from services import patient_records, assessments
        from datetime import datetime
        store = self.app.extensions["patient_records_store"]; astore = self.app.extensions["assessment_store"]
        now = datetime(2026, 10, 3, 9, 0)
        for name, age, level in (("Young High", 30, "high"), ("Old High", 70, "high"), ("Old Low", 68, "low")):
            uid, _ = patient_records.register_patient(store, self.pro_id, name, age, "Male", now)
            for when, lvl in ((now.replace(month=9), "low"), (now, level)):         # two results; only the latest counts
                assessments.record_assessment(astore, uid, {"assessment_type": "preliminary", "probability": .5, "classification": lvl,
                                                            "threshold_used": .4, "model_version": "v1", "assessed_at": when}, {"Age": age})
        page = self.text(self.admin.get("/admin"))
        self.assertRegex(page, r'People screened</p><p class="stat-value">3</p>')
        self.assertRegex(page, r'Higher risk</p><p class="stat-value[^"]*">2</p>')
        self.assertIn("67% of people screened", page)
        self.assertRegex(page, r'<th scope="row">18-44</th>\s*<td>1</td>\s*<td>1')
        self.assertRegex(page, r'<th scope="row">65\+</th>\s*<td>2</td>\s*<td>1')
        self.assertNotIn("Young High", page)                                                 # no names, only totals

    def test_people_using_nephron_counts_accounts_but_not_administrators(self):
        self.assertRegex(self.text(self.admin.get("/admin")), r'People using Nephron</p><p class="stat-value">2</p>')


class AdminNavigationTests(AdminTestCase):
    def test_my_home_and_the_guide_lead_to_admin_pages(self):
        home = self.text(self.admin.get("/"))
        self.assertIn('href="/admin">My home', home)
        self.assertIn('href="/admin/guide"', self.text(self.admin.get("/admin")))
        guide = self.admin.get("/admin/guide")
        self.assertEqual(guide.status_code, 200)
        self.assertIn("create_admin.py", self.text(guide))
        self.assertEqual(self.patient.get("/admin/guide").status_code, 403)

    def test_other_people_keep_their_own_guide(self):
        self.assertIn('href="/about"', self.text(self.patient.get("/dashboard")))
