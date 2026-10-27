"""
test_review_and_labels.py - the October 27 revision:
  * a professional reviews a shared result in ONE form: a clinical note only, or a clinical note + a follow-up
    appointment (optionally letting the patient screen again now) - all checked before anything is saved;
  * a shared result offers both, already pointed at that result;
  * a note can only ever be attached to the shared patient's own result;
  * every field in every form says whether it is Required or Optional.
"""
import datetime
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class SharedPatientCase(AppTestCase):
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
        self.history = f"/patients/{self.patient_id}"

    def review(self, **form):
        data = {"assessment_id": str(self.assessment_id), "mode": "note", "note": "Kidney function needs a recheck."}
        data.update(form)
        return self.post(f"{self.history}/review", data, client=self.professional, token_from=self.history)

    def notes(self):
        return self.app.extensions["clinical_review_store"].list_for_assessment(self.assessment_id)

    def appointments(self):
        return self.app.extensions["followup_appointment_store"].list_for_patient(self.patient_id)

    def rescreen_requests(self):
        return self.app.extensions["followup_store"].list_for_patient(self.patient_id)


def next_week():
    return (datetime.date.today() + datetime.timedelta(days=7)).isoformat()


class CombinedReviewTests(SharedPatientCase):
    def test_a_clinical_note_only_saves_just_the_note(self):
        response = self.review()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"{self.history}#assessment-{self.assessment_id}"))
        self.assertEqual([n["note"] for n in self.notes()], ["Kidney function needs a recheck."])
        self.assertEqual(self.appointments(), [])
        self.assertEqual(self.rescreen_requests(), [])

    def test_a_note_only_ignores_follow_up_fields_that_were_left_in_the_form(self):
        self.review(date=next_week(), time="09:00", purpose="leftover")
        self.assertEqual(len(self.notes()), 1)
        self.assertEqual(self.appointments(), [])

    def test_a_clinical_note_with_a_follow_up_saves_both(self):
        response = self.review(mode="note_follow_up", date=next_week(), time="09:30", purpose="Repeat creatinine and ACR", notes="Fasting")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.notes()), 1)
        (appointment,) = self.appointments()
        self.assertEqual((appointment["purpose"], appointment["notes"]), ("Repeat creatinine and ACR", "Fasting"))
        self.assertEqual(self.rescreen_requests(), [])                  # only when asked for

    def test_the_follow_up_can_also_let_the_patient_screen_again_now(self):
        self.review(mode="note_follow_up", date=next_week(), time="09:30", purpose="Recheck", rescreen="1")
        self.assertEqual(len(self.rescreen_requests()), 1)
        self.assertIn("requested a follow-up screening", self.text(self.patient.get("/dashboard")))

    def test_nothing_is_saved_when_the_follow_up_is_incomplete_and_what_was_typed_is_kept(self):
        for missing in ({"purpose": "Recheck"}, {"date": next_week(), "time": "09:30"}, {"date": "2020-01-01", "time": "09:00", "purpose": "Recheck"}):
            response = self.review(mode="note_follow_up", note="A long careful clinical note.", **missing)
            page = self.text(response)
            self.assertEqual(response.status_code, 200, missing)
            self.assertIn("Nothing was saved yet", page)
            self.assertIn("A long careful clinical note.", page)            # the note is never lost to a date typo
            self.assertIn('value="note_follow_up" checked', page)
            self.assertEqual(self.notes(), [], missing)                      # not even the note
            self.assertEqual(self.appointments(), [], missing)

    def test_an_empty_note_is_refused_either_way(self):
        for mode in ("note", "note_follow_up"):
            page = self.text(self.review(mode=mode, note="   ", date=next_week(), time="09:00", purpose="Recheck"))
            self.assertIn("Write your clinical note.", page)
        self.assertEqual((self.notes(), self.appointments()), ([], []))

    def test_a_note_can_only_go_on_this_patients_own_results(self):
        stranger = self.signed_in(email="stranger@example.com")
        self.post("/screening", answers(), client=stranger, token_from="/screening")
        theirs = self.app.extensions["assessment_store"].list_assessments(self.store.find_by_email("stranger@example.com")["user_id"])[0]["assessment_id"]
        self.assertEqual(self.review(assessment_id=str(theirs)).status_code, 404)
        self.assertEqual(self.app.extensions["clinical_review_store"].list_for_assessment(theirs), [])
        self.assertEqual(self.review(assessment_id="999999").status_code, 404)          # a missing result: 404, never a crash
        self.assertEqual(self.review(mode="something-else").status_code, 400)

    def test_the_page_has_one_review_form_instead_of_three(self):
        page = self.text(self.professional.get(self.history))
        self.assertEqual(page.count('action="/patients/%d/review"' % self.patient_id), 1)
        self.assertNotIn('action="/patients/%d/follow-up"' % self.patient_id, page)        # the separate request form is gone
        self.assertNotIn('action="/patients/%d/appointments"' % self.patient_id, page)     # and the separate appointment form
        self.assertIn("Clinical note only", page)
        self.assertIn("Clinical note + follow-up", page)

    def test_a_link_can_open_the_form_on_a_result_with_the_follow_up_chosen(self):
        page = self.text(self.professional.get(f"{self.history}?assessment={self.assessment_id}&with=follow-up"))
        self.assertIn('value="note_follow_up" checked', page)
        self.assertIn(f'<option value="{self.assessment_id}" selected', page)
        self.assertNotIn('data-shown-when="mode=note_follow_up" hidden', page)
        page = self.text(self.professional.get(self.history))
        self.assertIn('value="note" checked', page)
        self.assertIn('data-shown-when="mode=note_follow_up" hidden', page)


class SharedResultButtonsTests(SharedPatientCase):
    def test_a_shared_result_offers_a_note_or_a_note_with_a_follow_up_for_that_result(self):
        page = self.text(self.professional.get(f"{self.history}/assessments/{self.assessment_id}"))
        note_link = f"/patients/{self.patient_id}?assessment={self.assessment_id}#write-review"
        follow_up_link = f"/patients/{self.patient_id}?assessment={self.assessment_id}&amp;with=follow-up#write-review"
        self.assertIn(note_link, page)
        self.assertIn(follow_up_link, page)
        self.assertIn("Add a clinical note", page)
        self.assertIn("Add note + follow-up", page)


class Labels(HTMLParser):
    """Every visible field of every POST form, with the text of its own <label>, its <fieldset>'s <legend>, or the
    element a role="radiogroup" points at with aria-labelledby - whatever names it to a person or a screen reader."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields, self.form, self.label_for = [], None, {}
        self.labels = []        # open <label>s: [for_id, [markup], [fields inside]]
        self.groups = []        # open fieldsets / radiogroups: [[fields], legend markup or None, aria-labelledby id]
        self.named = {}         # id -> markup of that element (for aria-labelledby), recorded while it is open
        self.recording = []     # [id, [markup], depth]

    def _markup(self, text):
        for label in self.labels:
            label[1].append(text)
        for group in self.groups:
            if group[1] is not None:
                group[1].append(text)
        for item in self.recording:
            item[1].append(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._markup(self.get_starttag_text())
        for item in self.recording:
            item[2] += 1
        if a.get("id") and tag in ("span", "p", "div", "h2", "h3"):
            self.recording.append([a["id"], [], 1])
        if tag == "form":
            self.form = (a.get("method") or "get").lower()
        if tag == "label":
            self.labels.append([a.get("for"), [], []])
        if tag == "fieldset" or (a.get("role") == "radiogroup" and a.get("aria-labelledby")):
            self.groups.append([[], None, a.get("aria-labelledby"), tag, ""])     # [fields, legend being read, labelledby, tag, legend]
        if tag == "legend" and self.groups:
            self.groups[-1][1] = []
        if tag in ("input", "select", "textarea") and self.form == "post":
            kind = a.get("type", "text") if tag == "input" else tag
            if kind in ("hidden", "submit", "button") or "readonly" in a:
                return                                   # not something a person fills in
            field = {"id": a.get("id"), "name": a.get("name"), "label": "", "labelledby": []}
            self.fields.append(field)
            for label in self.labels:
                label[2].append(field)
            for group in self.groups:
                group[0].append(field)
                if group[2]:
                    field["labelledby"].append(group[2])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        for item in self.recording:
            item[2] -= 1

    def handle_endtag(self, tag):
        self._markup(f"</{tag}>")
        for item in list(self.recording):
            item[2] -= 1
            if item[2] == 0:
                self.named[item[0]] = "".join(item[1])
                self.recording.remove(item)
        if tag == "label" and self.labels:
            for_id, html, inside = self.labels.pop()
            for field in inside:                                  # <label><input ...> text</label>
                field["label"] += "".join(html)
            if for_id:                                            # <label for="id"> - the field may come later
                self.label_for[for_id] = self.label_for.get(for_id, "") + "".join(html)
        if tag == "legend" and self.groups and self.groups[-1][1] is not None:
            self.groups[-1][4] += "".join(self.groups[-1][1])
            self.groups[-1][1] = None
        if self.groups and tag == self.groups[-1][3]:
            fields, _, _, _, legend = self.groups.pop()
            for field in fields:                                  # the legend comes before the fields it names
                field["label"] += legend
        if tag == "form":
            self.form = None

    def handle_data(self, data):
        self._markup(data)

    def unmarked(self):
        marked = re.compile(r"chip-(required|optional)")
        missing = set()
        for field in self.fields:
            text = (field["label"] + self.label_for.get(field["id"] or "", "")
                    + "".join(self.named.get(i, "") for i in field["labelledby"]))
            if not marked.search(text):
                missing.add(field["name"])
        return sorted(missing)


class RequiredOptionalLabelTests(SharedPatientCase):
    def check(self, client, path):
        page = self.text(client.get(path))
        parser = Labels()
        parser.feed(page)
        self.assertTrue(parser.fields, f"{path}: no form fields found")
        self.assertEqual(parser.unmarked(), [], f"{path}: fields that do not say Required or Optional")

    def test_general_user_forms(self):
        self.check(self.client, "/login")
        self.check(self.client, "/register")
        self.check(self.signed_in(email="new@example.com"), "/screening")     # someone who can screen now
        self.check(self.patient, "/account")
        self.check(self.patient, "/reports")

    def test_healthcare_professional_forms(self):
        self.review(mode="note_follow_up", date=next_week(), time="09:30", purpose="Recheck")   # so the edit form shows too
        self.check(self.professional, self.history)
        self.check(self.professional, "/patient-records/new")
        self.check(self.professional, "/account")
