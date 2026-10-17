"""
Checks for the screening pages: the form, the analysis, the saved result, and what happens when the model is not ready.

They use a STAND-IN model (tests/model_fixtures.py), not Nephron's model, and in-memory stores. They prove the
plumbing and the rules: nothing is analysed without a verified model, a result is never invented, every result is saved
once with its answers, and people only ever see their own results.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from html.parser import HTMLParser
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import PASSWORD, AppTestCase, ready_model_service  # noqa: E402
import model_fixtures  # noqa: E402

from services import explanations, model_service, screening_contract  # noqa: E402

NEEDS_ML = unittest.skipUnless(model_fixtures.libraries_available(), "needs scikit-learn, pandas, numpy and joblib (see requirements.txt)")
NOW = datetime(2026, 9, 20, 4, 0, 0)


def at(moment):
    return mock.patch("services.clock.now_utc", return_value=moment)


def answers(**changes):
    form = {"Country": "Other", "Gender": "Female", "Sex": "Female", "Ethnicity": "Asian", "Age": "48", "height_cm": "160", "weight_kg": "70",
            "Diabetes": "1", "Hypertension": "0", "Cardiovascular_Disease": "0", "Heart_Failure": "0", "Hyperlipidemia": "1",
            "Kidney_Stones": "0", "Recurrent_UTI": "0", "Autoimmune_Disease": "0", "Family_History_CKD": "1",
            "ACE_Inhibitor": "0", "ARB": "1", "Diabetes_Medication": "1", "Diuretic": "0", "Statin": "1", "NSAID_Usage": "0",
            "Smoking_Status": "Never", "Alcohol_Consumption": "None", "Physical_Activity_Level": "Light",
            "Exercise_Hours_Per_Week": "2.5", "Water_Intake_L": "1.8", "Fast_Food_Frequency_Per_Week": "2", "Sleep_Duration_Hours": "6.8",
            "SugaryDrinksAddedSugar": "None", "UltraProcessedFoodFrequency": "Never", "SaturatedFatDairyIntake": "Low"}
    form.update(changes)
    return form


class Fields(HTMLParser):
    """The names of the form fields, and any links."""

    def __init__(self):
        super().__init__()
        self.names, self.required_marked = set(), 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("input", "select") and a.get("name") and a.get("type") != "hidden":
            self.names.add(a["name"])


class WithoutAModelTests(AppTestCase):
    """The normal state until a model has been verified: screening says so, and nothing can be analysed or saved."""

    def test_the_form_is_not_offered_and_the_page_says_nothing_was_saved(self):
        member = self.signed_in()
        response = member.get("/screening")
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", self.text(response))
        self.assertIn("nothing has been saved", self.text(response))
        self.assertNotIn('name="Age"', self.text(response))

    def test_a_posted_form_is_not_analysed_and_nothing_is_saved(self):
        member = self.signed_in()
        response = self.post("/screening", answers(), client=member, token_from="/account")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.app.extensions["assessment_store"].list_assessments(self.store.find_by_email("ana@example.com")["user_id"]), [])

    def test_the_dashboard_and_the_rail_do_not_offer_a_screening_that_cannot_run(self):
        page = self.text(self.signed_in().get("/dashboard"))
        self.assertIn("Screening is not available yet", page)
        self.assertNotIn("/screening", page)
        self.assertIn("Coming soon", page)

    def test_the_reason_is_available_to_whoever_runs_the_server(self):
        service = self.app.extensions["model_service"]
        self.assertFalse(service.ready)
        self.assertIn("No model has been installed", service.reason)

    def test_visitors_and_professionals_cannot_use_the_screening_pages(self):
        self.assertEqual(self.client.get("/screening").status_code, 302)
        doctor = self.signed_in(**self.professional_details())
        self.assertEqual(doctor.get("/screening").status_code, 403)
        self.assertEqual(doctor.get("/results/1").status_code, 403)


@NEEDS_ML
class ScreeningTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.assessments = self.app.extensions["assessment_store"]

    def submit(self, browser=None, **changes):
        return self.post("/screening", answers(**changes), client=browser or self.member, token_from="/screening")

    # ---- the form ----
    def test_the_form_asks_exactly_the_questions_in_the_catalog_and_nothing_else(self):
        page = self.text(self.member.get("/screening"))
        fields = Fields()
        fields.feed(page)
        catalog = screening_contract.load_catalog()
        expected = {q["name"] for q in catalog["questions"] if q["kind"] not in ("derived", "bmi") and "derived_from" not in q} | {"height_cm", "weight_kg", "Gender"}
        fixed = {"Age", "Country"}                    # from the account: sent as fixed hidden answers, never typed
        self.assertEqual(fields.names, expected - fixed)
        for name in fixed:
            self.assertIn(f'<input type="hidden" name="{name}"', page)
        self.assertIn('<input type="hidden" name="Physical_Activity_Level"', page)   # worked out from the exercise hours, shown locked
        self.assertLess(page.index('name="Exercise_Hours_Per_Week"'), page.index('name="Physical_Activity_Level"'))   # the hours come first
        self.assertNotIn('name="Obesity"', page)                              # worked out from the BMI, never asked
        for lab in ("eGFR", "HbA1c", "Hemoglobin", "Creatinine"):
            self.assertNotIn(lab, page)                                       # a preliminary screening asks for no laboratory value

    def test_it_is_a_guided_form_with_a_step_for_each_group_and_a_review(self):
        page = self.text(self.member.get("/screening"))
        for title in ("About you", "Health history", "Medicines", "Lifestyle", "Review"):
            self.assertIn(title, page)
        self.assertIn('name="csrf_token"', page)
        self.assertIn("screening.js", page)

    def test_the_rail_offers_new_assessment_as_a_real_link_when_the_model_is_ready(self):
        page = self.text(self.member.get("/dashboard"))
        self.assertIn('href="/screening"', page)
        self.assertNotIn("Screening is not available yet", page)
        self.assertIn("Start Assessment", page)

    # ---- analysing ----
    def test_a_complete_form_is_analysed_saved_once_and_leads_to_the_result(self):
        with at(NOW):
            response = self.submit()
        self.assertEqual(response.status_code, 302)
        match = re.search(r"/results/(\d+)$", response.headers["Location"])
        self.assertTrue(match, response.headers["Location"])
        rows = self.assessments.list_assessments(self.user_id)
        self.assertEqual(len(rows), 1)
        row = self.assessments.get_assessment(self.user_id, int(match.group(1)))
        service = ready_model_service()
        self.assertEqual((row["assessment_type"], row["model_version"]), ("preliminary", service.version))
        self.assertAlmostEqual(row["threshold_used"], service.threshold, places=6)
        self.assertEqual(row["classification"], "high" if row["probability"] >= round(service.threshold, 6) else "low")
        self.assertEqual(row["assessed_at"], NOW)

    def test_the_saved_result_is_exactly_what_the_model_says_for_those_answers(self):
        values, inputs, _ = screening_contract.validate_answers(screening_contract.load_catalog(), answers())
        expected = ready_model_service().predict(values)
        self.submit()
        row = self.assessments.list_assessments(self.user_id)[0]
        self.assertAlmostEqual(row["probability"], expected["probability"], places=6)

    def test_the_answers_are_saved_with_the_result_including_height_and_weight(self):
        self.submit()
        saved = self.assessments.get_assessment(self.user_id, self.assessments.list_assessments(self.user_id)[0]["assessment_id"])["inputs"]
        self.assertEqual((saved["Age"], saved["Country"], saved["Diabetes"], saved["height_cm"], saved["weight_kg"]), (48, "Other", 1, 160.0, 70.0))
        self.assertEqual(saved["Obesity"], 1 if saved["BMI"] >= 30 else 0)
        self.assertEqual(len(saved), 34)                                      # 31 model inputs plus the height, weight and gender
        self.assertEqual((saved["Gender"], saved["Sex"]), ("Female", "Female"))

    def test_an_incomplete_or_invalid_form_shows_messages_saves_nothing_and_keeps_the_answers(self):
        response = self.submit(Sleep_Duration_Hours="30", Ethnicity="Martian", Diabetes="")   # unrealistic, not offered, missing
        page = self.text(response)
        self.assertEqual(response.status_code, 200)
        for field in ("Sleep_Duration_Hours", "Ethnicity", "Diabetes"):
            self.assertIn(f'id="{field}-error"', page)
        self.assertIn("Please check your answers", page)
        self.assertIn('value="160"', page)                                    # what was typed is kept
        self.assertEqual(self.assessments.list_assessments(self.user_id), [])
        self.assertEqual(re.search(r'data-first-error-step="(-?\d+)"', page).group(1), "0")

    def test_the_form_opens_on_the_first_step_that_has_a_problem(self):
        page = self.text(self.submit(Smoking_Status=""))
        self.assertEqual(re.search(r'data-first-error-step="(-?\d+)"', page).group(1), "3")     # Lifestyle is the fourth step

    def test_a_missing_answer_is_never_filled_in_for_the_person(self):
        for name in answers():
            if name in ("Age", "Country", "Sex", "Physical_Activity_Level"):
                continue                                  # Age and Country come from the account; Gender "Female" tells the Sex
            form = answers()
            del form[name]
            response = self.post("/screening", form, client=self.member, token_from="/screening")
            self.assertEqual(response.status_code, 200, name)
        self.assertEqual(self.assessments.list_assessments(self.user_id), [])

    def test_the_question_reads_gender_and_sex_at_birth_waits_until_it_is_needed(self):
        page = self.text(self.member.get("/screening"))
        self.assertIn("<legend>Gender</legend>", page)
        self.assertIn('name="Gender" value="Gay man" data-sex="Male"', page)
        self.assertIn('name="Gender" value="Non-binary" data-sex=""', page)
        self.assertRegex(page, r'data-sex-follow-up hidden>')                # nothing chosen yet: not asked
        self.assertNotIn("<legend>Sex</legend>", page)

    def test_a_gay_man_is_screened_as_male_and_his_own_answer_is_kept(self):
        self.submit(Gender="Gay man", Sex="")
        saved = self.assessments.get_assessment(self.user_id, self.assessments.list_assessments(self.user_id)[0]["assessment_id"])["inputs"]
        self.assertEqual((saved["Gender"], saved["Sex"]), ("Gay man", "Male"))

    def test_a_gender_that_does_not_tell_needs_the_sex_assigned_at_birth(self):
        response = self.submit(Gender="Prefer not to say", Sex="")
        self.assertEqual(response.status_code, 200)
        page = self.text(response)
        self.assertIn('id="Sex-error"', page)
        self.assertNotRegex(page, r'data-sex-follow-up hidden>')              # shown, since it is now needed
        self.assertEqual(self.assessments.list_assessments(self.user_id), [])
        self.submit(Gender="Prefer not to say", Sex="Male")
        saved = self.assessments.get_assessment(self.user_id, self.assessments.list_assessments(self.user_id)[0]["assessment_id"])["inputs"]
        self.assertEqual((saved["Gender"], saved["Sex"]), ("Prefer not to say", "Male"))

    def test_the_form_is_refused_without_the_secret_token(self):
        response = self.member.post("/screening", data=answers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.assessments.list_assessments(self.user_id), [])

    def test_sending_the_same_answers_twice_quickly_saves_one_assessment(self):
        with at(NOW):
            first = self.submit()
            second = self.submit()
        self.assertEqual(first.headers["Location"], second.headers["Location"])
        self.assertEqual(len(self.assessments.list_assessments(self.user_id)), 1)

    def test_a_later_screening_with_the_same_answers_is_a_new_permanent_assessment(self):
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=40)):
            self.submit()
        self.assertEqual(len(self.assessments.list_assessments(self.user_id)), 2)     # history is never overwritten

    def test_different_answers_a_moment_later_are_a_new_assessment(self):
        with at(NOW):
            self.submit()
            self.submit(Diabetes="0")                     # a changeable answer (Age now comes from the birthday)
        self.assertEqual(len(self.assessments.list_assessments(self.user_id)), 2)

    def test_if_the_model_fails_while_analysing_nothing_is_saved_and_no_technical_detail_is_shown(self):
        service = ready_model_service()
        with mock.patch.object(model_service.ModelService, "predict", side_effect=RuntimeError("secret internal detail")):
            response = self.submit()
        page = self.text(response)
        self.assertEqual(response.status_code, 503)
        self.assertIn("could not analyse", page)
        self.assertNotIn("secret internal detail", page)
        self.assertEqual(self.assessments.list_assessments(self.user_id), [])

    def test_the_waiting_period_blocks_a_new_screening_but_not_the_old_result(self):
        app = self.app
        app.config["REASSESSMENT_DAYS"] = 30
        with at(NOW):
            first = self.submit()
        with at(NOW + timedelta(days=5)):
            page = self.text(self.member.get("/screening"))
            blocked = self.submit(Age="70")
        self.assertIn("is not open yet", page)
        self.assertIn("25 days left", page)
        self.assertEqual(len(self.assessments.list_assessments(self.user_id)), 1)
        self.assertNotIn('name="Age"', page)
        self.assertEqual(blocked.status_code, 200)
        with at(NOW + timedelta(days=31)):
            self.assertIn('name="Age"', self.text(self.member.get("/screening")))
        self.assertEqual(self.member.get(first.headers["Location"]).status_code, 200)


@NEEDS_ML
class ResultTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]
        with at(NOW):
            self.first = self.post("/screening", answers(), client=self.member, token_from="/screening").headers["Location"]
        self.page = self.text(self.member.get(self.first))

    def test_the_result_uses_the_agreed_words_and_never_claims_a_diagnosis(self):
        for words in ("Risk Classification", "Predicted Risk Probability", "Preliminary Risk", "not a diagnosis" if "High" in self.page else "does not mean you are free"):
            self.assertIn(words, self.page)
        for forbidden in ("confidence", "you have ckd", "diagnosed with", "Moderate Risk", "moderate risk"):   # "Moderate" alone is an activity answer
            self.assertNotIn(forbidden, self.page.lower() if forbidden.islower() else self.page)

    def test_the_result_shows_the_saved_probability_classification_and_threshold(self):
        row = self.app.extensions["assessment_store"].list_assessments(self.user_id)[0]
        service = ready_model_service()
        self.assertIn(f"{row['probability'] * 100:.4g}".split("e")[0][:3], self.page)
        self.assertIn(">High Preliminary Risk<" if row["classification"] == "high" else ">Low Preliminary Risk<", self.page)
        self.assertIn("Validated threshold:", self.page)
        from services.visuals import percent_text
        self.assertIn(percent_text(service.threshold * 100), self.page.replace(" ", ""))     # the same formatter the page uses
        self.assertIn("Sep 20, 2026", self.page)                                   # local date, in words

    def test_the_tips_panel_shows_tips_matching_this_persons_own_answers(self):
        # the default answers() include Diabetes=1 and Diabetes_Medication=1
        self.assertIn("Kidney health tips for you", self.page)
        self.assertIn("diabetes medication", self.page.lower())
        self.assertIn("Never stop, start, or change", self.page)          # an "always" tip
        self.assertNotIn("Stopping smoking", self.page)                   # Smoking_Status is "Never" by default

    def test_a_different_persons_answers_change_which_tips_show(self):
        with at(NOW):
            location = self.post("/screening", answers(Diabetes="0", Diabetes_Medication="0", Smoking_Status="Current"),
                                 client=self.member, token_from="/screening").headers["Location"]
        page = self.text(self.member.get(location))
        self.assertIn("Stopping smoking", page)
        self.assertNotIn("diabetes medication", page.lower())

    def test_the_source_note_button_is_present_for_a_tip(self):
        self.assertIn("source-note-button", self.page)
        self.assertIn("KDIGO", self.page)

    def test_a_model_that_cannot_explain_a_single_result_gets_an_honest_empty_state_not_model_wide_factors(self):
        # (this stand-in is an ordinary gradient-boosting model, so it cannot explain one result)
        self.assertIn("No explanation for this result", self.page)
        self.assertNotIn("explain-card", self.page)
        self.assertNotIn("factor-rank", self.page)
        self.assertNotIn("relies on most", self.page)
        self.assertNotIn("Model-wide", self.page)

    def test_the_answers_behind_the_result_can_be_read(self):
        self.assertIn("Your answers", self.page)
        self.assertIn("48 years", self.page)
        self.assertIn("Diabetes", self.page)
        self.assertIn("height 160 cm", self.page)

    def test_sharing_and_downloading_are_both_real_links_not_placeholders(self):
        self.assertIn('href="/share"', self.page)
        self.assertIn('action="/reports/download"', self.page)
        self.assertNotIn("Coming soon", self.page)
        self.assertNotIn('href="#"', self.page)

    def test_a_second_result_is_compared_with_the_first_without_judging_it(self):
        with at(NOW + timedelta(days=40)):
            second = self.post("/screening", answers(Age="70", Diabetes="0"), client=self.member, token_from="/screening").headers["Location"]
        page = self.text(self.member.get(second))
        self.assertIn("Compared with previous", page)
        self.assertRegex(page, r"(\d+(\.\d+)? points (higher|lower)|No change)")
        self.assertNotIn("better", page.lower().replace("better kidney", ""))
        self.assertNotIn("Compared with previous", self.page)                     # the first result has nothing to compare with

    def test_the_dashboard_now_shows_the_result_and_links_to_it(self):
        with at(NOW):
            dashboard = self.text(self.member.get("/dashboard"))
        self.assertIn('data-count-to="1"', dashboard)
        self.assertIn(f'href="{self.first}"', dashboard)
        self.assertIn("View result", dashboard)
        self.assertNotIn("No assessments yet", dashboard)


@NEEDS_ML
class ExplainedResultTests(AppTestCase):
    """The result page for a model that CAN explain a single result: one card for what raised the estimate, one for what lowered it."""
    model = "explainable"
    CARD = re.compile(r'<section class="card explain-card explain-(raises|lowers) reveal".*?</section>', re.S)
    ITEM = re.compile(r'<li class="factor factor-explained factor-(up|down)">.*?<span class="factor-name">(.*?)<small class="factor-answer">Your answer: (.*?)</small>', re.S)

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.assessments = self.app.extensions["assessment_store"]
        self.service = self.app.extensions["model_service"]
        self.catalog = screening_contract.load_catalog()

    def result(self, **changes):
        client = self.member
        if "Age" in changes:            # age now comes from the birthday: a person of that age is a new account with that birthday
            age = int(changes["Age"])
            client = self.signed_in(email=f"age{age}-{uuid.uuid4().hex[:6]}@example.com", date_of_birth=f"{2026 - age}-01-15")
        location = self.post("/screening", answers(**changes), client=client, token_from="/screening").headers["Location"]
        return location, self.text(client.get(location))

    def cards(self, page):
        """{'raises': [(label, answer), ...], 'lowers': [...]} read from the two cards."""
        found = {}
        for match in self.CARD.finditer(page):
            found[match.group(1)] = [(label.strip(), answer.strip()) for _, label, answer in self.ITEM.findall(match.group(0))]
        return found

    def expected(self, **changes):
        values, inputs, _ = screening_contract.validate_answers(self.catalog, answers(**changes))
        return explanations.build(self.catalog, self.service.explain(values)["effects"], inputs)

    def test_the_page_has_two_cards_one_for_what_raised_and_one_for_what_lowered_the_estimate(self):
        _, page = self.result()
        self.assertEqual(page.count("explain-card"), page.count("explain-card") and 2 * (page.count("explain-card") // 2))
        self.assertIn("What raised your estimate", page)
        self.assertIn("What lowered your estimate", page)
        self.assertLess(page.index("What raised your estimate"), page.index("What lowered your estimate"))
        cards = self.cards(page)
        self.assertEqual(set(cards), {"raises", "lowers"})
        for kind in cards:
            self.assertLessEqual(len(cards[kind]), 5)

    def test_every_answer_shown_in_a_card_is_in_the_right_card_and_the_page_has_no_other_list_of_factors(self):
        _, page = self.result()
        for match in self.CARD.finditer(page):
            expected_class = "factor-up" if match.group(1) == "raises" else "factor-down"
            classes = re.findall(r'<li class="factor factor-explained (factor-\w+)">', match.group(0))
            self.assertTrue(classes)
            self.assertEqual(set(classes), {expected_class})                                # never a lowering factor in the raising card
        self.assertEqual(page.count("Your answer:"), sum(len(v) for v in self.cards(page).values()))

    def test_the_old_model_wide_list_and_the_old_single_card_are_gone(self):
        _, page = self.result()
        for gone in ("relies on most", "Model-wide", "the model overall", "What affected your result most", "factor-effect"):
            self.assertNotIn(gone, page)

    def test_the_cards_are_what_the_model_says_for_those_exact_answers(self):
        _, page = self.result()
        expected = self.expected()
        cards = self.cards(page)
        self.assertEqual(cards["raises"], [(i["label"], i["answer"]) for i in expected["raises"]])
        self.assertEqual(cards["lowers"], [(i["label"], i["answer"]) for i in expected["lowers"]])

    def test_each_card_has_its_own_short_explanation_and_one_shared_caveat_sits_below_both(self):
        _, page = self.result()
        expected = self.expected()
        for kind in ("raises", "lowers"):
            for sentence in expected["summary"][kind]:
                self.assertIn(sentence, page)
        self.assertEqual(page.count("not medical advice"), 1)                              # shown once, below both cards
        self.assertGreater(page.index("not medical advice"), page.index("What lowered your estimate"))
        self.assertIn("in either direction", page)

    def test_every_factor_is_a_question_they_answered_and_shows_what_they_answered(self):
        _, page = self.result(Age="61", Diabetes="1", Smoking_Status="Former")
        _, inputs, _ = screening_contract.validate_answers(self.catalog, answers(Age="61", Diabetes="1", Smoking_Status="Former"))
        words = {q["short"]: screening_contract.answer_text(q, inputs) for q in self.catalog["questions"]}
        for items in self.cards(page).values():
            for label, answer in items:
                self.assertEqual(answer, words[label], label)

    def test_two_different_people_get_different_cards_and_age_moves_between_them(self):
        _, young = self.result(Age="22", Diabetes="0", Hypertension="0", Family_History_CKD="0", ACE_Inhibitor="0", ARB="0")
        _, old = self.result(Age="82", Diabetes="1", Hypertension="1", Family_History_CKD="1", ACE_Inhibitor="1", ARB="1")
        young_cards, old_cards = self.cards(young), self.cards(old)
        self.assertNotEqual(young_cards, old_cards)
        in_card = lambda cards, label: [kind for kind, items in cards.items() if any(l == label for l, _ in items)]
        self.assertEqual(in_card(young_cards, "Age"), ["lowers"])                         # being young lowered the estimate
        self.assertEqual(in_card(old_cards, "Age"), ["raises"])                           # being old raised it

    def test_the_result_is_explained_the_same_way_every_time_it_is_opened(self):
        location, page = self.result()
        self.assertEqual(self.cards(self.text(self.member.get(location))), self.cards(page))

    def test_a_card_with_nothing_in_it_says_so_instead_of_disappearing(self):
        # Make the model's estimate depend on nothing that lowers it: patch the explanation to raise-only effects.
        location, _ = self.result()
        raising_only = {"probability": self.assessments.list_assessments(self.user_id)[0]["probability"],
                        "effects": [{"name": "Diabetes", "label": "Diabetes", "effect": 1.0}, {"name": "Age", "label": "Age", "effect": 0.4}]}
        with mock.patch.object(type(self.service), "explain", return_value=raising_only):
            page = self.text(self.member.get(location))
        self.assertIn("What lowered your estimate", page)
        self.assertIn("None of your answers lowered the estimate", page)
        self.assertEqual(self.cards(page)["lowers"], [])
        self.assertEqual([label for label, _ in self.cards(page)["raises"]], ["Diabetes", "Age"])

    # ---- every case where showing an explanation would not be honest ----
    def result_after(self, change):
        location, _ = self.result()
        change()
        return self.text(self.member.get(location))

    def assertNoExplanation(self, page, has_answers=True):
        self.assertIn("No explanation for this result", page)
        self.assertNotIn("explain-card", page)
        self.assertEqual("Your answers" in page, has_answers)                              # the rest of the result is still there
        self.assertIn("Risk Classification", page)

    def test_a_result_made_by_another_model_version_is_not_explained(self):
        self.assertNoExplanation(self.result_after(lambda: self.assessments._rows[0].update(model_version="some-older-model")))

    def test_a_result_whose_saved_probability_does_not_match_is_not_explained(self):
        self.assertNoExplanation(self.result_after(lambda: self.assessments._rows[0].update(probability=self.assessments._rows[0]["probability"] * 0.5)))

    def test_nothing_is_explained_when_the_model_cannot_explain_right_now(self):
        with mock.patch.object(type(self.service), "can_explain", False, create=True), mock.patch.object(self.service, "can_explain", False):
            location, _ = self.result()
            self.assertNoExplanation(self.text(self.member.get(location)))

    def test_a_result_saved_without_answers_is_not_explained(self):
        from services import assessments
        values, _, _ = screening_contract.validate_answers(self.catalog, answers())
        answer = self.service.predict(values)
        saved_id = assessments.record_assessment(self.assessments, self.user_id, {
            "assessment_type": "preliminary", "probability": answer["probability"], "classification": answer["classification"],
            "threshold_used": answer["threshold"], "model_version": answer["model_version"], "assessed_at": NOW})
        self.assertNoExplanation(self.text(self.member.get(f"/results/{saved_id}")), has_answers=False)

    def test_the_form_promises_the_new_thing_and_not_the_old_one(self):
        page = self.text(self.member.get("/screening"))
        self.assertIn("What raised and lowered your estimate", page)
        self.assertNotIn("relies on most", page)


@NEEDS_ML
class PrivacyOfResultsTests(AppTestCase):
    model = True

    def test_one_person_cannot_open_another_persons_result_and_gets_the_same_answer_as_for_a_missing_one(self):
        ana = self.signed_in()
        ben = self.signed_in(email="ben@example.com", full_name="Ben Lim")
        location = self.post("/screening", answers(), client=ana, token_from="/screening").headers["Location"]
        self.assertEqual(ana.get(location).status_code, 200)
        ben.get("/dashboard")                                                           # (shows and clears the welcome message first)
        stolen, missing = ben.get(location), ben.get("/results/987654")
        self.assertEqual((stolen.status_code, missing.status_code), (404, 404))
        self.assertEqual(self.text(stolen), self.text(missing))                          # nothing tells the two cases apart
        self.assertNotIn("Diabetes", self.text(stolen))
        self.assertEqual(self.client.get(location).status_code, 302)                    # a visitor is sent to sign in

    def test_each_person_only_ever_sees_their_own_results_on_their_dashboard(self):
        ana = self.signed_in()
        ben = self.signed_in(email="ben@example.com", full_name="Ben Lim")
        self.post("/screening", answers(), client=ana, token_from="/screening")
        self.assertIn("No assessments yet", self.text(ben.get("/dashboard")))


if __name__ == "__main__":
    unittest.main()



class RealisticRangeTests(AppTestCase):
    """Answers outside the model's TRAINING range are accepted (so the model can be checked against people it was not
    trained on), flagged honestly on the result, and still refused when they are not realistic at all."""
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.browser = self.signed_in()
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]

    def _submit(self, **changes):
        return self.post("/screening", answers(**changes), client=self.browser, token_from="/screening")

    def test_an_age_below_the_training_range_is_accepted_and_flagged_on_the_result(self):
        # A 16-year-old patient record (a professional enters the birthday); the age comes from that birthday.
        pro = self.signed_in(**self.professional_details())
        code = self.post("/patient-records/new", {"full_name": "Teen Patient", "date_of_birth": "2010-01-15", "country": "Other", "gender": "Female", "sex": "Female"},
                         client=pro, token_from="/patient-records/new").headers["Location"].split("/")[-2]
        response = self.post(f"/patient-records/{code}/screening", answers(), client=pro, token_from=f"/patient-records/{code}/screening")
        self.assertEqual(response.status_code, 302)
        page = self.text(pro.get(response.headers["Location"]))
        self.assertIn("Some answers are outside what the model learned from", page)
        self.assertIn("Age: 16 years", page)

    def _unused_age_override(self):
        response = self._submit(Age="16")
        self.assertEqual(response.status_code, 302)
        page = self.text(self.browser.get(response.headers["Location"]))
        self.assertIn("Some answers are outside what the model learned from", page)
        self.assertIn("Age: 16 years", page)

    def test_lifestyle_numbers_outside_training_are_accepted(self):
        response = self._submit(Sleep_Duration_Hours="13", Water_Intake_L="5", Exercise_Hours_Per_Week="20", Fast_Food_Frequency_Per_Week="14")
        self.assertEqual(response.status_code, 302)

    def test_unrealistic_numbers_are_still_refused(self):
        for field, value in (("Sleep_Duration_Hours", "30"), ("Water_Intake_L", "40"), ("height_cm", "400")):
            page = self.text(self._submit(**{field: value}))
            self.assertIn(f'id="{field}-error"', page, field)
        self.assertEqual(self.app.extensions["assessment_store"].list_assessments(self.user_id), [])

    def test_philippines_is_offered_saved_as_itself_and_flagged_as_unknown_to_the_model(self):
        self.assertIn('<option value="Philippines"', self.text(self.new_browser().get("/register")))
        self.browser = self.signed_in(email="ph@example.com", country="Philippines", province_code="1300000000")
        self.user_id = self.store.find_by_email("ph@example.com")["user_id"]
        response = self._submit()
        self.assertEqual(response.status_code, 302)
        rows = self.app.extensions["assessment_store"].list_assessments(self.user_id)
        saved = self.app.extensions["assessment_store"].get_assessment(self.user_id, rows[0]["assessment_id"])
        self.assertEqual(saved["inputs"]["Country"], "Philippines")
        page = self.text(self.browser.get(response.headers["Location"]))
        self.assertIn("the model knows it only as &#34;Other&#34;", page)

    def test_an_ordinary_answer_shows_no_flag(self):
        response = self._submit()
        page = self.text(self.browser.get(response.headers["Location"]))
        self.assertNotIn("Some answers are outside what the model learned from", page)



class FixedAnswerTests(AppTestCase):
    """Age from the birthday, Country from the account, and Sex/Ethnicity/Country kept from the first screening -
    shown locked, and enforced by the server even if the page is tampered with."""
    model = True

    def setUp(self):
        super().setUp()
        self.browser = self.signed_in(country="Philippines", province_code="1300000000")   # helper birthday 1978-05-14 -> 48
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]

    def _saved(self, n=0):
        store = self.app.extensions["assessment_store"]
        return store.get_assessment(self.user_id, store.list_assessments(self.user_id)[n]["assessment_id"])["inputs"]

    def test_age_and_country_are_shown_locked(self):
        page = self.text(self.browser.get("/screening"))
        self.assertIn('<input type="hidden" name="Age" value="48">', page)
        self.assertIn('<input type="hidden" name="Country" value="Philippines">', page)
        self.assertIn("Worked out from your date of birth.", page)

    def test_a_tampered_age_or_country_is_replaced_by_the_server(self):
        self.post("/screening", answers(Age="20", Country="USA"), client=self.browser, token_from="/screening")
        self.assertEqual((self._saved()["Age"], self._saved()["Country"]), (48, "Philippines"))

    def test_sex_and_ethnicity_are_locked_after_the_first_screening(self):
        self.assertNotIn('<input type="hidden" name="Sex"', self.text(self.browser.get("/screening")))   # not yet
        self.post("/screening", answers(Sex="Female", Ethnicity="Asian"), client=self.browser, token_from="/screening")
        page = self.text(self.browser.get("/screening"))
        self.assertIn('<input type="hidden" name="Sex" value="Female">', page)
        self.assertIn('<input type="hidden" name="Ethnicity" value="Asian">', page)
        self.assertIn("Kept as answered in your first screening.", page)
        with at(datetime.now() + timedelta(days=60)):
            self.post("/screening", answers(Sex="Male", Ethnicity="White", Diabetes="0"), client=self.browser, token_from="/screening")
        newest = self._saved(0)
        self.assertEqual((newest["Sex"], newest["Ethnicity"]), ("Female", "Asian"))

    def test_after_the_first_screening_only_genders_that_match_the_kept_sex_are_offered(self):
        self.post("/screening", answers(Gender="Female"), client=self.browser, token_from="/screening")
        page = self.text(self.browser.get("/screening"))
        self.assertIn('name="Gender" value="Lesbian woman"', page)
        self.assertIn('name="Gender" value="Non-binary"', page)
        self.assertNotIn('name="Gender" value="Gay man"', page)
        with at(datetime.now() + timedelta(days=60)):
            response = self.post("/screening", answers(Gender="Gay man"), client=self.browser, token_from="/screening")
        self.assertEqual(response.status_code, 200)                       # refused, not silently changed
        self.assertIn('id="Gender-error"', self.text(response))
        with at(datetime.now() + timedelta(days=60)):
            self.post("/screening", answers(Gender="Non-binary", Diabetes="0"), client=self.browser, token_from="/screening")
        self.assertEqual((self._saved(0)["Gender"], self._saved(0)["Sex"]), ("Non-binary", "Female"))
