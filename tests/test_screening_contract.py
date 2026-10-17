"""
Checks for services/screening_contract.py and ml/feature_catalog.json: the questions and the rules for the answers.
No model and no database are needed. Run everything with:   python -m unittest discover -s tests -v
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import screening_contract as contract  # noqa: E402

# The project's Stage 1 predictors (preliminary, no laboratory). If this list changes, it must be a decision, not an accident.
STAGE_1 = {
    "Country", "Sex", "Ethnicity", "Age", "BMI",
    "Smoking_Status", "Alcohol_Consumption", "Physical_Activity_Level", "Exercise_Hours_Per_Week", "Water_Intake_L",
    "Fast_Food_Frequency_Per_Week", "Sleep_Duration_Hours", "SugaryDrinksAddedSugar", "UltraProcessedFoodFrequency", "SaturatedFatDairyIntake",
    "Diabetes", "Cardiovascular_Disease", "Hyperlipidemia", "Recurrent_UTI", "Family_History_CKD", "Hypertension",
    "Heart_Failure", "Kidney_Stones", "Autoimmune_Disease", "Obesity",
    "ACE_Inhibitor", "Diabetes_Medication", "Diuretic", "ARB", "Statin", "NSAID_Usage",
}
LABORATORY = {"eGFR", "Serum_Creatinine", "Blood_Urea_Nitrogen", "Urine_ACR", "HbA1c", "Fasting_Glucose", "Hemoglobin",
              "Albumin", "Systolic_BP", "Diastolic_BP", "Frailty_Index", "Frailty_Category"}


def good_form(**changes):
    form = {"Country": "Other", "Gender": "Female", "Sex": "Female", "Ethnicity": "Asian", "Age": "48", "height_cm": "160", "weight_kg": "70",
            "Diabetes": "1", "Hypertension": "0", "Cardiovascular_Disease": "0", "Heart_Failure": "0", "Hyperlipidemia": "1",
            "Kidney_Stones": "0", "Recurrent_UTI": "0", "Autoimmune_Disease": "0", "Family_History_CKD": "1",
            "ACE_Inhibitor": "0", "ARB": "1", "Diabetes_Medication": "1", "Diuretic": "0", "Statin": "1", "NSAID_Usage": "0",
            "Smoking_Status": "Never", "Alcohol_Consumption": "None", "Physical_Activity_Level": "Light",
            "Exercise_Hours_Per_Week": "2.5", "Water_Intake_L": "1.8", "Fast_Food_Frequency_Per_Week": "2", "Sleep_Duration_Hours": "6.8",
            "SugaryDrinksAddedSugar": "None", "UltraProcessedFoodFrequency": "Never", "SaturatedFatDairyIntake": "Low"}
    form.update(changes)
    return form


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = contract.load_catalog()

    def test_it_is_exactly_the_31_stage_one_predictors_and_nothing_from_the_laboratory(self):
        names = set(contract.feature_names(self.catalog))
        self.assertEqual(names, STAGE_1)
        self.assertEqual(len(contract.feature_names(self.catalog)), 31)
        self.assertFalse(names & LABORATORY)                                   # a preliminary screening asks for no lab value

    def test_obesity_is_worked_out_and_not_asked(self):
        obesity = contract.question_for(self.catalog, "Obesity")
        self.assertEqual((obesity["kind"], obesity["rule"], obesity["value"]), ("derived", "bmi_at_least", 30))
        form = contract.validate_answers(self.catalog, good_form())[0]
        self.assertIn("Obesity", form)

    def test_every_question_belongs_to_a_step_and_the_file_passes_its_own_checks(self):
        contract.check_catalog(self.catalog)
        steps = {step["key"] for step in self.catalog["steps"]}
        self.assertTrue(all(q["step"] in steps for q in self.catalog["questions"]))
        self.assertTrue(all(q.get("label") and q.get("why") for q in self.catalog["questions"]))

    def test_the_answers_offered_are_the_ones_seen_in_the_data(self):
        countries = {o["value"] for o in contract.question_for(self.catalog, "Country")["options"]}
        self.assertEqual(countries, {"USA", "UK", "India", "Canada", "Australia", "Philippines", "Other"})
        # ...but what the MODEL receives is only ever a country it saw: Philippines is given to it as Other.
        self.assertEqual(contract.model_values(contract.question_for(self.catalog, "Country")), {"USA", "UK", "India", "Canada", "Australia", "Other"})
        self.assertEqual({o["value"] for o in contract.question_for(self.catalog, "Alcohol_Consumption")["options"]}, {"None", "Moderate", "Heavy"})
        self.assertEqual({o["value"] for o in contract.question_for(self.catalog, "Physical_Activity_Level")["options"]}, {"Sedentary", "Light", "Moderate", "Active"})

    def test_a_malformed_catalog_is_refused_with_a_plain_message(self):
        broken = copy.deepcopy(self.catalog)
        broken["questions"].append(dict(broken["questions"][0]))                # a duplicate name
        with self.assertRaisesRegex(ValueError, "twice"):
            contract.check_catalog(broken)
        broken = copy.deepcopy(self.catalog)
        contract.question_for(broken, "Sex")["options"] = [{"value": "Female", "label": "Female"}]
        with self.assertRaisesRegex(ValueError, "options"):
            contract.check_catalog(broken)
        broken = copy.deepcopy(self.catalog)
        contract.question_for(broken, "Diabetes")["options"] = [{"value": "Y", "label": "Yes"}, {"value": "N", "label": "No"}]
        with self.assertRaisesRegex(ValueError, "Yes"):
            contract.check_catalog(broken)


class ValidAnswerTests(unittest.TestCase):
    def setUp(self):
        self.catalog = contract.load_catalog()

    def test_a_complete_form_gives_every_model_input_with_the_right_types(self):
        values, inputs, errors = contract.validate_answers(self.catalog, good_form())
        self.assertEqual(errors, {})
        self.assertEqual(set(values), STAGE_1)
        self.assertEqual((values["Age"], values["Diabetes"], values["Sex"], values["Alcohol_Consumption"]), (48, 1, "Female", "None"))
        self.assertIsInstance(values["Age"], int)
        self.assertIsInstance(values["Water_Intake_L"], float)
        self.assertEqual(values["BMI"], round(70 / 1.6 ** 2, 1))

    def test_the_saved_snapshot_keeps_the_height_and_weight_that_were_typed(self):
        values, inputs, _ = contract.validate_answers(self.catalog, good_form())
        self.assertEqual((inputs["height_cm"], inputs["weight_kg"]), (160.0, 70.0))
        self.assertEqual({k: inputs[k] for k in values}, values)

    def test_obesity_switches_on_exactly_at_a_bmi_of_30(self):
        low = contract.validate_answers(self.catalog, good_form(height_cm="200", weight_kg="119.6"))[0]      # BMI 29.9
        high = contract.validate_answers(self.catalog, good_form(height_cm="200", weight_kg="120"))[0]       # BMI 30.0
        self.assertEqual((low["BMI"], low["Obesity"], high["BMI"], high["Obesity"]), (29.9, 0, 30.0, 1))
        for weight in ("55", "60", "90", "110"):                                                              # it always follows the BMI
            values = contract.validate_answers(self.catalog, good_form(weight_kg=weight))[0]
            self.assertEqual(values["Obesity"], 1 if values["BMI"] >= 30 else 0, weight)

    def test_spaces_around_answers_are_ignored_and_unknown_fields_are_not_used(self):
        values, _, errors = contract.validate_answers(self.catalog, good_form(Country="  USA ", Age=" 50 ", csrf_token="x", is_admin="1"))
        self.assertEqual(errors, {})
        self.assertEqual((values["Country"], values["Age"]), ("USA", 50))
        self.assertNotIn("is_admin", values)

    def test_the_answers_can_be_shown_back_in_words(self):
        _, inputs, _ = contract.validate_answers(self.catalog, good_form())
        shown = dict((title, dict(rows)) for title, rows in contract.describe_inputs(self.catalog, inputs))
        self.assertEqual(shown["About you"]["Age"], "48 years")
        self.assertEqual(shown["Health history"]["Diabetes"], "Yes")
        self.assertIn("height 160 cm", shown["About you"]["Body mass index"])
        self.assertEqual(shown["Lifestyle"]["Alcohol"], "None")
        self.assertEqual(contract.describe_inputs(self.catalog, {}), [])                  # nothing is invented

    def test_the_reference_row_is_valid(self):
        row = contract.reference_row(self.catalog)
        self.assertEqual(set(row), STAGE_1)
        self.assertEqual(row["Obesity"], 0)


class InvalidAnswerTests(unittest.TestCase):
    def setUp(self):
        self.catalog = contract.load_catalog()

    def errors(self, **changes):
        return contract.validate_answers(self.catalog, good_form(**changes))[2]

    def test_an_empty_form_reports_every_missing_answer_and_fills_none_in(self):
        values, _, errors = contract.validate_answers(self.catalog, {})
        self.assertEqual(len(errors), 30)                                                 # 29 askable questions (activity level is worked out), height and weight count as two
        self.assertEqual(values, {})                                                      # nothing is guessed

    def test_each_single_missing_answer_is_named(self):
        for field in good_form():
            if field in ("Sex", "Physical_Activity_Level"):
                continue                  # Gender tells the sex; the exercise hours tell the activity level - see their own tests
            form = good_form()
            del form[field]
            errors = contract.validate_answers(self.catalog, form)[2]
            self.assertIn(field, errors, field)

    def test_a_choice_must_be_one_of_the_offered_answers(self):
        self.assertIn("Country", self.errors(Country="Atlantis"))                         # not an answer the form offers
        self.assertNotIn("Country", self.errors(Country="Philippines"))                   # offered, given to the model as Other
        self.assertIn("Country", self.errors(Country="usa"))                              # exact, not approximately
        self.assertIn("Sex", self.errors(Gender="Non-binary", Sex="Other"))
        self.assertIn("Gender", self.errors(Gender="Martian"))
        self.assertIn("Alcohol_Consumption", self.errors(Alcohol_Consumption="none"))
        self.assertIn("Smoking_Status", self.errors(Smoking_Status=""))

    def test_yes_no_accepts_only_zero_and_one(self):
        for bad in ("2", "yes", "true", "-1", ""):
            self.assertIn("Diabetes", self.errors(Diabetes=bad), bad)

    def test_numbers_must_be_plain_and_inside_the_range_the_model_was_built_for(self):
        # Unrealistic or malformed answers are refused; answers merely outside the TRAINING range are not.
        for field, bad in (("Age", "0"), ("Age", "121"), ("Age", "48.5"), ("Age", "abc"), ("Age", "-3"), ("Age", "1e2"), ("Age", "4 8"),
                           ("Water_Intake_L", "-0.1"), ("Water_Intake_L", "10.5"), ("Water_Intake_L", "1,8"),
                           ("Exercise_Hours_Per_Week", "113"), ("Sleep_Duration_Hours", "24.5"), ("Sleep_Duration_Hours", "nan"),
                           ("Fast_Food_Frequency_Per_Week", "43"), ("Fast_Food_Frequency_Per_Week", "2.5")):
            self.assertIn(field, self.errors(**{field: bad}), f"{field}={bad}")
        for field, fine in (("Age", "17"), ("Age", "18"), ("Age", "95"), ("Age", "100"), ("Water_Intake_L", "0"), ("Water_Intake_L", "4.5"),
                            ("Exercise_Hours_Per_Week", "20"), ("Sleep_Duration_Hours", "11"), ("Sleep_Duration_Hours", "13"),
                            ("Fast_Food_Frequency_Per_Week", "14")):
            self.assertNotIn(field, self.errors(**{field: fine}), f"{field}={fine}")

    def test_height_and_weight_must_make_a_bmi_the_model_supports(self):
        self.assertIn("BMI", self.errors(height_cm="200", weight_kg="15"))                # BMI 3.8 - not a realistic body
        self.assertIn("BMI", self.errors(height_cm="140", weight_kg="200"))               # BMI 102
        self.assertNotIn("BMI", self.errors(height_cm="140", weight_kg="120"))            # BMI 61: outside training, still realistic
        self.assertIn("height_cm", self.errors(height_cm="44"))
        self.assertIn("weight_kg", self.errors(weight_kg="651"))
        self.assertIn("height_cm", self.errors(height_cm="tall"))
        self.assertNotIn("BMI", self.errors())

    def test_html_or_script_text_is_just_an_invalid_answer(self):
        errors = self.errors(Country="<script>alert(1)</script>", Age="48; DROP TABLE users")
        self.assertIn("Country", errors)
        self.assertIn("Age", errors)


if __name__ == "__main__":
    unittest.main()


class GenderTests(unittest.TestCase):
    """Sex is asked THROUGH Gender: the person's own answer is saved, the model gets Male or Female."""

    def setUp(self):
        self.catalog = contract.load_catalog()

    def check(self, fixed=None, **changes):
        return contract.validate_answers(self.catalog, good_form(**changes), fixed=fixed)

    def test_a_gender_that_tells_the_sex_gives_the_model_that_sex_and_saves_the_gender(self):
        for gender, sex in (("Male", "Male"), ("Female", "Female"), ("Gay man", "Male"), ("Lesbian woman", "Female"),
                            ("Bisexual man", "Male"), ("Bisexual woman", "Female")):
            values, inputs, errors = self.check(Gender=gender, Sex="")
            self.assertEqual(errors, {}, gender)
            self.assertEqual((values["Sex"], inputs["Sex"], inputs["Gender"]), (sex, sex, gender), gender)
            self.assertNotIn("Gender", values)                     # the model never sees Gender

    def test_what_the_page_sent_for_sex_cannot_override_a_gender_that_tells(self):
        values, _, errors = self.check(Gender="Gay man", Sex="Female")
        self.assertEqual((errors, values["Sex"]), ({}, "Male"))

    def test_a_gender_that_does_not_tell_asks_for_the_sex_assigned_at_birth(self):
        for gender in ("Transgender man", "Transgender woman", "Non-binary", "Queer or another identity", "Prefer not to say"):
            self.assertIn("Sex", self.check(Gender=gender, Sex="")[2], gender)
            values, inputs, errors = self.check(Gender=gender, Sex="Female")
            self.assertEqual((errors, values["Sex"], inputs["Gender"]), ({}, "Female", gender), gender)

    def test_a_missing_or_unknown_gender_is_an_error_and_nothing_is_guessed(self):
        values, _, errors = self.check(Gender="")
        self.assertIn("Gender", errors)
        self.assertNotIn("Sex", values)
        self.assertIn("Gender", self.check(Gender="gay man")[2])         # exact, not approximately

    def test_a_gender_that_contradicts_a_kept_sex_is_refused(self):
        errors = self.check(fixed={"Sex": {"value": "Female"}}, Gender="Gay man", Sex="Female")[2]
        self.assertIn("Gender", errors)
        values, _, errors = self.check(fixed={"Sex": {"value": "Female"}}, Gender="Non-binary", Sex="Female")
        self.assertEqual((errors, values["Sex"]), ({}, "Female"))

    def test_the_model_still_only_knows_male_and_female(self):
        self.assertEqual(contract.model_values(contract.question_for(self.catalog, "Sex")), {"Female", "Male"})

    def test_the_saved_answers_read_gender_first_then_sex_at_birth(self):
        _, inputs, _ = self.check(Gender="Lesbian woman", Sex="")
        rows = dict(contract.describe_inputs(self.catalog, inputs))["About you"]
        self.assertIn(("Gender", "Lesbian woman"), rows)
        self.assertIn(("Sex at birth", "Female"), rows)

    def test_an_errors_step_is_found_through_the_gender_field(self):
        self.assertEqual(contract.steps_with_errors(self.catalog, {"Gender": "x"}), {"about"})

    def test_a_catalog_whose_gender_implies_an_unknown_sex_is_refused(self):
        broken = copy.deepcopy(self.catalog)
        contract.question_for(broken, "Sex")["asked_through"]["options"][0]["sex"] = "Robot"
        with self.assertRaises(ValueError):
            contract.check_catalog(broken)


class ActivityFromHoursTests(unittest.TestCase):
    """Physical_Activity_Level is worked out from Exercise_Hours_Per_Week - the person is not asked twice."""

    def setUp(self):
        self.catalog = contract.load_catalog()

    def level(self, hours, sent="Active"):
        values, _, errors = contract.validate_answers(self.catalog, good_form(Exercise_Hours_Per_Week=hours, Physical_Activity_Level=sent))
        return values.get("Physical_Activity_Level"), errors

    def test_each_band_matches_the_cut_offs_read_from_the_training_data(self):
        for hours, expected in (("0", "Sedentary"), ("0.5", "Sedentary"), ("0.6", "Light"), ("2", "Light"), ("2.1", "Moderate"),
                                ("5", "Moderate"), ("5.1", "Active"), ("12", "Active"), ("40", "Active")):
            self.assertEqual(self.level(hours, sent="Sedentary")[0], expected, hours)

    def test_what_the_page_sent_for_the_level_is_ignored(self):
        self.assertEqual(self.level("1", sent="Active")[0], "Light")
        self.assertEqual(self.level("1", sent="")[0], "Light")

    def test_without_valid_hours_there_is_no_level_and_only_the_hours_error(self):
        level, errors = self.level("")
        self.assertIsNone(level)
        self.assertIn("Exercise_Hours_Per_Week", errors)
        self.assertNotIn("Physical_Activity_Level", errors)

    def test_the_hours_are_asked_before_the_level_and_the_bands_are_checked(self):
        names = [q["name"] for q in self.catalog["questions"]]
        self.assertLess(names.index("Exercise_Hours_Per_Week"), names.index("Physical_Activity_Level"))
        broken = copy.deepcopy(self.catalog)
        contract.question_for(broken, "Physical_Activity_Level")["derived_from"]["bands"][0]["value"] = "Lazy"
        with self.assertRaises(ValueError):
            contract.check_catalog(broken)

    def test_the_model_still_gets_one_of_its_four_known_levels(self):
        question = contract.question_for(self.catalog, "Physical_Activity_Level")
        self.assertEqual(contract.model_values(question), {"Sedentary", "Light", "Moderate", "Active"})
