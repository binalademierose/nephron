"""
Checks for services/professional_overview.py: it combines a professional's own patient records and their
shared/authorized patients into one dashboard - correctly scoped to that ONE professional, with review status
only ever applying to a shared patient's own assessment.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import assessments, clinical_reviews, patient_records, professional_overview  # noqa: E402
from test_screening_flow import at  # noqa: E402
from services.assessment_store import MemoryAssessmentStore  # noqa: E402
from services.authorization_store import MemoryAuthorizationStore  # noqa: E402
from services.clinical_review_store import MemoryClinicalReviewStore  # noqa: E402
from services.followup_appointment_store import MemoryFollowUpAppointmentStore  # noqa: E402
from services.patient_records_store import MemoryPatientRecordsStore  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)


def new_general(users, full_name="Ana Reyes"):
    return users.create_user({"email": f"{uuid.uuid4().hex[:10]}@example.com", "full_name": full_name, "role": "general", "professional": None}, "h", NOW)


def new_professional(users, full_name="Dr. Luis Cruz"):
    return users.create_user({"email": f"{uuid.uuid4().hex[:10]}@example.com", "full_name": full_name, "role": "professional",
                              "professional": {"profession_title": "Nephrologist", "institution": None, "license_number": None}}, "h", NOW)


class ProfessionalOverviewTests(unittest.TestCase):
    def setUp(self):
        self.users = MemoryUserStore()
        self.patient_records_store = MemoryPatientRecordsStore(self.users)
        self.auth_store = MemoryAuthorizationStore(self.users)
        self.assessment_store = MemoryAssessmentStore(self.users)
        self.review_store = MemoryClinicalReviewStore(self.assessment_store)
        self.followup_store = MemoryFollowUpAppointmentStore()
        self.professional_id = new_professional(self.users)
        self.professional = self.users.find_by_id(self.professional_id)

    def _dashboard(self):
        return professional_overview.dashboard(self.patient_records_store, self.auth_store, self.users, self.assessment_store,
                                                self.review_store, self.followup_store, self.professional_id, "Asia/Manila")

    def test_an_empty_dashboard_is_honest_about_having_nothing(self):
        overview = self._dashboard()
        self.assertEqual(overview["total_patients"], 0)
        self.assertFalse(overview["has_any_patients"])
        self.assertEqual(overview["recent_assessments"], [])
        self.assertEqual(overview["pending_review_count"], 0)
        self.assertEqual(overview["follow_up_count"], 0)

    def test_a_patient_record_counts_toward_total_patients(self):
        patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        self.assertEqual(self._dashboard()["total_patients"], 1)

    def test_only_an_accepted_shared_patient_counts_not_a_pending_request(self):
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.assertEqual(self._dashboard()["total_patients"], 0)          # still pending, not accepted
        self.auth_store.accept(general_id, self.professional_id, NOW)
        self.assertEqual(self._dashboard()["total_patients"], 1)

    def test_a_different_professionals_patients_are_never_counted(self):
        other_id = new_professional(self.users, "Dr. Other")
        patient_records.register_patient(self.patient_records_store, other_id, "Not Mine", 40, "Female", NOW)
        self.assertEqual(self._dashboard()["total_patients"], 0)

    def test_low_and_high_risk_counts_use_each_patients_own_latest_assessment(self):
        low_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Low Risk Patient", 40, "Female", NOW)
        high_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "High Risk Patient", 60, "Male", NOW)
        assessments.record_assessment(self.assessment_store, low_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        assessments.record_assessment(self.assessment_store, high_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 60})
        # low_user re-screens and their MOST RECENT result becomes high - only the latest should count
        assessments.record_assessment(self.assessment_store, low_user, {
            "assessment_type": "preliminary", "probability": 0.8, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": LATER}, {"Age": 40})
        overview = self._dashboard()
        self.assertEqual(overview["low_risk_count"], 0)
        self.assertEqual(overview["high_risk_count"], 2)

    def test_a_patient_with_no_assessment_yet_is_counted_as_a_patient_but_not_in_either_risk_bucket(self):
        patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        overview = self._dashboard()
        self.assertEqual(overview["total_patients"], 1)
        self.assertEqual(overview["low_risk_count"] + overview["high_risk_count"], 0)

    def test_recent_assessments_are_newest_first_across_every_patient(self):
        user_a, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Patient A", 40, "Female", NOW)
        user_b, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Patient B", 50, "Male", NOW)
        assessments.record_assessment(self.assessment_store, user_a, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        assessments.record_assessment(self.assessment_store, user_b, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": LATER}, {"Age": 40})
        overview = self._dashboard()
        self.assertEqual([row["patient"]["display_name"] for row in overview["recent_assessments"]], ["Patient B", "Patient A"])

    def test_a_patient_records_own_assessment_is_self_recorded_never_pending(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        overview = self._dashboard()
        self.assertEqual(overview["recent_assessments"][0]["review_status"], "self_recorded")
        self.assertEqual(overview["pending_review_count"], 0)

    def test_a_shared_patients_assessment_is_awaiting_review_until_one_is_added(self):
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        assessment_id = assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        overview = self._dashboard()
        self.assertEqual(overview["recent_assessments"][0]["review_status"], "awaiting_review")
        self.assertEqual(overview["pending_review_count"], 1)

        clinical_reviews.add_review(self.review_store, self.auth_store, self.professional, assessment_id, general_id, "Looks fine.", NOW)
        overview = self._dashboard()
        self.assertEqual(overview["recent_assessments"][0]["review_status"], "reviewed")
        self.assertEqual(overview["pending_review_count"], 0)

    def _insights(self):
        return professional_overview.patient_insights(self.patient_records_store, self.auth_store, self.users, self.assessment_store,
                                                       self.professional_id, "Asia/Manila")

    def test_fewer_than_three_results_returns_none_rather_than_a_misleading_chart(self):
        user_a, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Patient A", 40, "Female", NOW)
        assessments.record_assessment(self.assessment_store, user_a, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40, "Sex": "Female"})
        self.assertIsNone(self._insights())

    def _add_patient_with_result(self, name, age, sex, classification):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, name, age, sex, NOW)
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.8 if classification == "high" else 0.2,
            "classification": classification, "threshold_used": 0.6, "model_version": "v1", "assessed_at": NOW},
            {"Age": age, "Sex": sex})
        return user_id

    def test_risk_counts_and_percent_with_three_patients(self):
        self._add_patient_with_result("A", 40, "Female", "low")
        self._add_patient_with_result("B", 50, "Male", "high")
        self._add_patient_with_result("C", 60, "Male", "high")
        insights = self._insights()
        self.assertEqual(insights["total_with_result"], 3)
        self.assertEqual(insights["risk"]["ring_percent"], 67)
        self.assertIn("2", insights["risk"]["detail"])
        self.assertIn("3", insights["risk"]["detail"])

    def test_a_gender_count_plot_of_their_patients_and_who_is_at_higher_risk(self):
        self._add_patient_with_result("A", 40, "Female", "low")
        self._add_patient_with_result("B", 45, "Female", "high")
        self._add_patient_with_result("C", 50, "Male", "high")
        rows = {r["label"]: r for r in self._insights()["gender"]["rows"]}
        self.assertEqual((rows["Female"]["people"], rows["Female"]["high"], rows["Female"]["high_percent"]), (2, 1, 50))
        self.assertEqual((rows["Male"]["people"], rows["Male"]["high"], rows["Male"]["high_percent"]), (1, 1, 100))
        self.assertEqual(rows["Female"]["bar"], 100)                     # the largest group sets the scale
        self.assertEqual(self._insights()["gender"]["hidden"], 0)         # their own patients: nothing folded away

    def test_a_patient_records_own_gender_is_used_not_only_male_or_female(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "A", 40, "Male", NOW,
                                                      country="Philippines", gender="Gay man")
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.8, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40, "Sex": "Male", "Gender": "Gay man", "Country": "Philippines"})
        self._add_patient_with_result("B", 50, "Male", "low")
        self._add_patient_with_result("C", 60, "Female", "low")
        insights = self._insights()
        self.assertEqual([r["label"] for r in insights["gender"]["rows"]], ["Male", "Female", "Gay man"])   # the form's order
        self.assertEqual((insights["philippines"]["people"], insights["philippines"]["high"]), (1, 1))

    def test_patients_in_the_philippines_are_counted_from_the_record_or_their_answers(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "PH", 40, "Female", NOW,
                                                      country="Philippines", gender="Female")
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40, "Sex": "Female"})
        general_id = new_general(self.users, "Ana Reyes")
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.9, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 33, "Sex": "Female", "Gender": "Lesbian woman", "Country": "Philippines"})
        self._add_patient_with_result("C", 60, "Male", "high")                   # no country: not counted as living in the Philippines
        philippines = self._insights()["philippines"]
        self.assertEqual((philippines["people"], philippines["high"], philippines["high_percent"]), (2, 1, 50))

    def test_age_buckets(self):
        self._add_patient_with_result("A", 30, "Female", "low")
        self._add_patient_with_result("B", 50, "Male", "low")
        self._add_patient_with_result("C", 70, "Male", "high")
        groups = {g["label"]: g["percent"] for g in self._insights()["age"]["groups"]}
        self.assertEqual(groups, {"18-44": 33, "45-64": 33, "65+": 33})

    def test_a_shared_patients_age_and_sex_come_from_their_own_latest_assessment(self):
        general_id = new_general(self.users, "Ana Reyes")
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 33, "Sex": "Female"})
        self._add_patient_with_result("B", 50, "Male", "high")
        self._add_patient_with_result("C", 60, "Male", "high")
        insights = self._insights()
        rows = {r["label"]: r["people"] for r in insights["gender"]["rows"]}
        self.assertEqual(rows["Female"], 1)
        groups = {g["label"]: g["percent"] for g in insights["age"]["groups"]}
        self.assertGreater(groups["18-44"], 0)

    def test_a_different_professionals_patients_never_affect_the_numbers(self):
        self._add_patient_with_result("A", 40, "Female", "low")
        self._add_patient_with_result("B", 50, "Male", "high")
        self._add_patient_with_result("C", 60, "Male", "high")
        other_id = new_professional(self.users, "Dr. Other")
        other_user, _ = patient_records.register_patient(self.patient_records_store, other_id, "Not Mine", 80, "Female", NOW)
        assessments.record_assessment(self.assessment_store, other_user, {
            "assessment_type": "preliminary", "probability": 0.9, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 80, "Sex": "Female"})
        insights = self._insights()
        self.assertEqual(insights["total_with_result"], 3)

    def _follow_up_list(self, **kwargs):
        return professional_overview.follow_up_list(self.patient_records_store, self.auth_store, self.users, self.followup_store,
                                                     self.professional_id, "Asia/Manila", NOW, **kwargs)

    def test_a_future_appointment_is_pending(self):
        general_id = self._accept_shared_patient()
        from services import followup_appointments
        followup_appointments.schedule(self.followup_store, self.auth_store, self.professional, general_id, LATER, "Recheck", None, NOW)
        rows = self._follow_up_list()
        self.assertEqual(rows[0]["follow_up_status"], "pending")
        self.assertEqual(len(self._follow_up_list(status="pending")), 1)
        self.assertEqual(self._follow_up_list(status="due"), [])

    def test_a_past_scheduled_appointment_is_due(self):
        general_id = self._accept_shared_patient()
        from services import followup_appointments
        past = NOW - timedelta(days=2)
        followup_appointments.schedule(self.followup_store, self.auth_store, self.professional, general_id, NOW - timedelta(minutes=1), "Recheck", None, past)
        rows = self._follow_up_list()
        self.assertEqual(rows[0]["follow_up_status"], "due")
        self.assertEqual(len(self._follow_up_list(status="due")), 1)

    def test_completed_and_cancelled_statuses(self):
        general_id = self._accept_shared_patient()
        from services import followup_appointments
        aid = followup_appointments.schedule(self.followup_store, self.auth_store, self.professional, general_id, LATER, "Recheck", None, NOW)
        followup_appointments.complete(self.followup_store, self.auth_store, self.professional_id, aid, NOW)
        self.assertEqual(self._follow_up_list()[0]["follow_up_status"], "completed")
        self.assertEqual(len(self._follow_up_list(status="completed")), 1)

    def test_search_by_patient_name_or_code(self):
        record_user, code = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        # scheduling a follow-up for a patient record: only possible through the store directly today (no UI yet)
        self.followup_store.create(record_user, self.professional_id, "Dr. Luis Cruz", "Nephrologist", LATER, "Recheck", None, NOW)
        self.assertEqual(len(self._follow_up_list(term="dela cruz")), 1)
        self.assertEqual(len(self._follow_up_list(term=code)), 1)
        self.assertEqual(self._follow_up_list(term="nobody"), [])

    def test_a_different_professionals_follow_ups_never_appear(self):
        other_id = new_professional(self.users, "Dr. Other")
        other_user, _ = patient_records.register_patient(self.patient_records_store, other_id, "Not Mine", 40, "Female", NOW)
        self.followup_store.create(other_user, other_id, "Dr. Other", None, LATER, "Recheck", None, NOW)
        self.assertEqual(self._follow_up_list(), [])

    def test_date_period_matches_the_appointments_own_scheduled_date(self):
        general_id = self._accept_shared_patient()
        from services import followup_appointments
        with at(NOW):
            followup_appointments.schedule(self.followup_store, self.auth_store, self.professional, general_id, NOW, "Recheck", None, NOW)
            self.assertEqual(len(self._follow_up_list(date_period="today")), 1)
        next_month = NOW.replace(month=10, day=5)
        with at(next_month):
            self.assertEqual(self._follow_up_list(date_period="today"), [])

    def _shared_list(self, **kwargs):
        return professional_overview.shared_assessment_list(self.auth_store, self.users, self.assessment_store,
                                                             self.review_store, self.professional_id, "Asia/Manila", **kwargs)

    def _accept_shared_patient(self, full_name="Ana Reyes"):
        general_id = new_general(self.users, full_name)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        return general_id

    def test_never_includes_a_patient_record_only_shared_patients(self):
        record_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Own Patient", 40, "Female", NOW)
        assessments.record_assessment(self.assessment_store, record_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        self.assertEqual(self._shared_list(), [])

    def test_a_pending_not_yet_accepted_patients_assessment_never_appears(self):
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 30})
        self.assertEqual(self._shared_list(), [])

    def test_review_status_starts_awaiting_review_then_moves_to_reviewed(self):
        general_id = self._accept_shared_patient()
        assessment_id = assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 30})
        self.assertEqual(self._shared_list()[0]["review_status"], "awaiting_review")
        self.assertEqual(len(self._shared_list(review_status="awaiting_review")), 1)
        self.assertEqual(self._shared_list(review_status="reviewed"), [])
        clinical_reviews.add_review(self.review_store, self.auth_store, self.professional, assessment_id, general_id, "Fine.", NOW)
        self.assertEqual(self._shared_list()[0]["review_status"], "reviewed")
        self.assertEqual(self._shared_list(review_status="awaiting_review"), [])

    def test_term_matches_name_or_exact_assessment_id(self):
        general_id = self._accept_shared_patient("Maria Santos")
        assessment_id = assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 30})
        self.assertEqual(len(self._shared_list(term="santos")), 1)
        self.assertEqual(len(self._shared_list(term=str(assessment_id))), 1)
        self.assertEqual(self._shared_list(term="nobody"), [])

    def test_risk_filter(self):
        low_id = self._accept_shared_patient("Low Patient")
        high_id = self._accept_shared_patient("High Patient")
        assessments.record_assessment(self.assessment_store, low_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 30})
        assessments.record_assessment(self.assessment_store, high_id, {
            "assessment_type": "preliminary", "probability": 0.8, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 30})
        self.assertEqual(len(self._shared_list(risk="low")), 1)
        self.assertEqual(len(self._shared_list(risk="high")), 1)

    def test_date_period_today_this_week_this_month(self):
        general_id = self._accept_shared_patient()
        with at(NOW):
            assessments.record_assessment(self.assessment_store, general_id, {
                "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
                "model_version": "v1", "assessed_at": NOW}, {"Age": 30})
            self.assertEqual(len(self._shared_list(date_period="today")), 1)
            self.assertEqual(len(self._shared_list(date_period="this_week")), 1)
            self.assertEqual(len(self._shared_list(date_period="this_month")), 1)
        two_days_later = NOW + timedelta(days=2)
        with at(two_days_later):
            self.assertEqual(self._shared_list(date_period="today"), [])          # the assessment was 2 days ago
            # NOW (Sept 20) is a Sunday - the LAST day of its Mon-Sun week - so 2 days later has already
            # crossed into a new calendar week; "this month" is the one that still includes it.
            self.assertEqual(self._shared_list(date_period="this_week"), [])
            self.assertEqual(len(self._shared_list(date_period="this_month")), 1)
        next_month = NOW.replace(month=10, day=5)
        with at(next_month):
            self.assertEqual(self._shared_list(date_period="today"), [])
            self.assertEqual(self._shared_list(date_period="this_week"), [])
            self.assertEqual(self._shared_list(date_period="this_month"), [])

    def test_this_week_still_includes_an_earlier_day_in_the_same_calendar_week(self):
        general_id = self._accept_shared_patient()
        monday = datetime(2026, 9, 21, 9, 0, 0)                        # the Monday right after NOW's Sunday
        with at(monday):
            assessments.record_assessment(self.assessment_store, general_id, {
                "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
                "model_version": "v1", "assessed_at": monday}, {"Age": 30})
        wednesday_same_week = monday + timedelta(days=2)
        with at(wednesday_same_week):
            self.assertEqual(len(self._shared_list(date_period="this_week")), 1)
            self.assertEqual(self._shared_list(date_period="today"), [])

    def _assessment_list(self, **kwargs):
        return professional_overview.assessment_list(self.patient_records_store, self.auth_store, self.users, self.assessment_store,
                                                      self.review_store, self.professional_id, "Asia/Manila", **kwargs)

    def test_lists_every_assessment_across_every_patient(self):
        user_a, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Patient A", 40, "Female", NOW)
        user_b, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Patient B", 50, "Male", NOW)
        assessments.record_assessment(self.assessment_store, user_a, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        assessments.record_assessment(self.assessment_store, user_b, {
            "assessment_type": "preliminary", "probability": 0.8, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 50})
        self.assertEqual(len(self._assessment_list()), 2)

    def test_a_different_professionals_assessments_never_appear(self):
        other_id = new_professional(self.users, "Dr. Other")
        other_user, _ = patient_records.register_patient(self.patient_records_store, other_id, "Not Mine", 40, "Female", NOW)
        assessments.record_assessment(self.assessment_store, other_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        self.assertEqual(self._assessment_list(), [])

    def test_search_by_assessment_id_matches_exactly_not_as_a_substring(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        assessment_id = assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 52})
        self.assertEqual(len(self._assessment_list(term=str(assessment_id))), 1)
        self.assertEqual(self._assessment_list(term=str(assessment_id) + "9"), [])

    def test_search_by_patient_name_or_code(self):
        user_id, code = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 52})
        self.assertEqual(len(self._assessment_list(term="dela cruz")), 1)
        self.assertEqual(len(self._assessment_list(term=code)), 1)
        self.assertEqual(self._assessment_list(term="nobody"), [])

    def test_risk_filter(self):
        low_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Low", 40, "Female", NOW)
        high_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "High", 50, "Male", NOW)
        assessments.record_assessment(self.assessment_store, low_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        assessments.record_assessment(self.assessment_store, high_user, {
            "assessment_type": "preliminary", "probability": 0.8, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 50})
        self.assertEqual(len(self._assessment_list(risk="low")), 1)
        self.assertEqual(len(self._assessment_list(risk="high")), 1)

    def test_time_period_filter(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        old_date = NOW - timedelta(days=60)
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": old_date}, {"Age": 52})
        self.assertEqual(len(self._assessment_list(period="all")), 1)
        self.assertEqual(self._assessment_list(period="30_days"), [])

    def test_review_status_follows_the_same_rule_as_the_dashboard(self):
        record_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Own Patient", 40, "Female", NOW)
        assessments.record_assessment(self.assessment_store, record_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 30})
        statuses = {row["patient"]["display_name"]: row["review_status"] for row in self._assessment_list()}
        self.assertEqual(statuses["Own Patient"], "self_recorded")
        self.assertEqual(statuses["Ana Reyes"], "awaiting_review")

    def _patient_list(self, **kwargs):
        return professional_overview.patient_list(self.patient_records_store, self.auth_store, self.users, self.assessment_store,
                                                   self.review_store, self.followup_store, self.professional_id, "Asia/Manila", **kwargs)

    def test_a_patient_record_with_no_assessment_yet_is_pending(self):
        patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        rows = self._patient_list()
        self.assertEqual(rows[0]["is_pending"], True)
        pending_only = self._patient_list(category="pending")
        self.assertEqual(len(pending_only), 1)
        reviewed_only = self._patient_list(category="reviewed")
        self.assertEqual(reviewed_only, [])

    def test_a_patient_records_own_assessment_is_never_pending(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 52})
        rows = self._patient_list()
        self.assertFalse(rows[0]["is_pending"])
        self.assertEqual(len(self._patient_list(category="reviewed")), 1)
        self.assertEqual(self._patient_list(category="pending"), [])

    def test_a_shared_patient_is_pending_until_reviewed_then_moves_to_reviewed(self):
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        assessment_id = assessments.record_assessment(self.assessment_store, general_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        self.assertEqual(len(self._patient_list(category="pending")), 1)
        self.assertEqual(self._patient_list(category="reviewed"), [])
        clinical_reviews.add_review(self.review_store, self.auth_store, self.professional, assessment_id, general_id, "Fine.", NOW)
        self.assertEqual(self._patient_list(category="pending"), [])
        self.assertEqual(len(self._patient_list(category="reviewed")), 1)

    def test_follow_up_category_only_includes_patients_with_a_scheduled_appointment(self):
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        patient_records.register_patient(self.patient_records_store, self.professional_id, "No Follow-up", 40, "Female", NOW)
        self.assertEqual(self._patient_list(category="follow_up"), [])
        from services import followup_appointments
        followup_appointments.schedule(self.followup_store, self.auth_store, self.professional, general_id, LATER, "Recheck", None, NOW)
        follow_up_rows = self._patient_list(category="follow_up")
        self.assertEqual(len(follow_up_rows), 1)
        self.assertEqual(follow_up_rows[0]["source"], "shared")

    def test_risk_filter_only_matches_a_patients_latest_result(self):
        low_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Low Patient", 40, "Female", NOW)
        high_user, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "High Patient", 60, "Male", NOW)
        assessments.record_assessment(self.assessment_store, low_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        assessments.record_assessment(self.assessment_store, high_user, {
            "assessment_type": "preliminary", "probability": 0.8, "classification": "high", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 60})
        self.assertEqual([row["display_name"] for row in self._patient_list(risk="low")], ["Low Patient"])
        self.assertEqual([row["display_name"] for row in self._patient_list(risk="high")], ["High Patient"])

    def test_term_narrows_the_list_by_name_or_code(self):
        _, code = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        patient_records.register_patient(self.patient_records_store, self.professional_id, "Maria Santos", 40, "Female", NOW)
        self.assertEqual([r["display_name"] for r in self._patient_list(term="dela cruz")], ["Juan Dela Cruz"])
        self.assertEqual([r["display_name"] for r in self._patient_list(term=code)], ["Juan Dela Cruz"])

    def test_a_different_professionals_patients_never_appear_in_the_list(self):
        other_id = new_professional(self.users, "Dr. Other")
        patient_records.register_patient(self.patient_records_store, other_id, "Not Mine", 40, "Female", NOW)
        self.assertEqual(self._patient_list(), [])

    def _search(self, term):
        return professional_overview.search(self.patient_records_store, self.auth_store, self.users, self.assessment_store,
                                            self.professional_id, term, "Asia/Manila")

    def test_search_finds_a_patient_by_partial_name(self):
        patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        results = self._search("dela cruz")
        self.assertEqual([p["display_name"] for p in results["patients"]], ["Juan Dela Cruz"])

    def test_search_finds_a_patient_by_patient_code(self):
        _, code = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        results = self._search(code)
        self.assertEqual([p["display_name"] for p in results["patients"]], ["Juan Dela Cruz"])

    def test_search_never_finds_another_professionals_patient(self):
        other_id = new_professional(self.users, "Dr. Other")
        patient_records.register_patient(self.patient_records_store, other_id, "Not Mine", 40, "Female", NOW)
        results = self._search("Not Mine")
        self.assertEqual(results["patients"], [])

    def test_search_by_name_also_lists_that_patients_assessments(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 52})
        results = self._search("Juan")
        self.assertEqual(len(results["assessments"]), 1)
        self.assertEqual(results["assessments"][0]["patient"]["display_name"], "Juan Dela Cruz")

    def test_search_by_a_numeric_assessment_id_finds_it_directly(self):
        user_id, _ = patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        assessment_id = assessments.record_assessment(self.assessment_store, user_id, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 52})
        results = self._search(str(assessment_id))
        self.assertEqual([a["assessment_id"] for a in results["assessments"]], [assessment_id])

    def test_search_by_id_never_finds_another_professionals_assessment(self):
        other_id = new_professional(self.users, "Dr. Other")
        other_user, _ = patient_records.register_patient(self.patient_records_store, other_id, "Not Mine", 40, "Female", NOW)
        assessment_id = assessments.record_assessment(self.assessment_store, other_user, {
            "assessment_type": "preliminary", "probability": 0.2, "classification": "low", "threshold_used": 0.6,
            "model_version": "v1", "assessed_at": NOW}, {"Age": 40})
        results = self._search(str(assessment_id))
        self.assertEqual(results["assessments"], [])

    def test_a_blank_search_returns_nothing_rather_than_everything(self):
        patient_records.register_patient(self.patient_records_store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        self.assertEqual(self._search(""), {"patients": [], "assessments": []})
        self.assertEqual(self._search("   "), {"patients": [], "assessments": []})

    def test_search_finds_a_shared_patient_too(self):
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        results = self._search("Ana")
        self.assertEqual([p["display_name"] for p in results["patients"]], ["Ana Reyes"])
        self.assertIsNone(results["patients"][0]["patient_code"])

    def test_follow_up_count_only_counts_scheduled_ones_not_completed_or_cancelled(self):
        general_id = new_general(self.users)
        self.auth_store.request(general_id, self.professional_id, NOW)
        self.auth_store.accept(general_id, self.professional_id, NOW)
        from services import followup_appointments
        first = followup_appointments.schedule(self.followup_store, self.auth_store, self.professional, general_id, LATER, "Recheck", None, NOW)
        second = followup_appointments.schedule(self.followup_store, self.auth_store, self.professional, general_id, LATER.replace(month=11), "Recheck 2", None, NOW)
        self.assertEqual(self._dashboard()["follow_up_count"], 2)
        followup_appointments.complete(self.followup_store, self.auth_store, self.professional_id, first, NOW)
        self.assertEqual(self._dashboard()["follow_up_count"], 1)
        followup_appointments.cancel(self.followup_store, self.auth_store, self.professional_id, second, NOW)
        self.assertEqual(self._dashboard()["follow_up_count"], 0)


if __name__ == "__main__":
    unittest.main()
