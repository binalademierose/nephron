"""
screening_contract.py - the questions of the preliminary screening, and the rules for the answers.

The questions live in ml/feature_catalog.json (one entry per model input). The screening form is built from that
file and every answer is checked against it here, on the server. Nothing here knows the model: model_service.py
compares this catalog with the model file before screening is switched on, so a question the model does not use
(or a model input nobody is asked) can never slip through.

Two rules keep the model honest:
  * EVERY input must be answered. A missing answer is an error shown to the person. It is never filled in,
    because the model's own preprocessing would silently fill it with the most common value.
  * An answer must be one the model knows: a listed choice, or a number inside the range seen in training.
"""
import json
import math
import os
import re

CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "feature_catalog.json")

KINDS = ("choice", "yesno", "number", "bmi", "derived")
NUMBER_PATTERN = re.compile(r"^\d{1,4}(\.\d{1,3})?$")
WHOLE_PATTERN = re.compile(r"^\d{1,4}$")


def load_catalog(path=CATALOG_PATH):
    with open(path, encoding="utf-8") as handle:
        catalog = json.load(handle)
    check_catalog(catalog)
    return catalog


def check_catalog(catalog):
    """Raise ValueError, in plain words, if the catalog file itself is malformed. (It is edited by people.)"""
    steps = [step["key"] for step in catalog.get("steps", [])]
    if not steps or len(set(steps)) != len(steps):
        raise ValueError("feature_catalog.json: the steps are missing or repeated")
    seen = set()
    for question in catalog.get("questions", []):
        name = question.get("name")
        if not name or name in seen:
            raise ValueError(f"feature_catalog.json: '{name}' is missing or listed twice")
        seen.add(name)
        if question.get("kind") not in KINDS:
            raise ValueError(f"feature_catalog.json: {name} has an unknown kind")
        if question["step"] not in steps:
            raise ValueError(f"feature_catalog.json: {name} is in a step that does not exist")
        kind = question["kind"]
        if kind == "choice":
            values = [option["value"] for option in question.get("options", [])]
            if len(values) < 2 or len(set(values)) != len(values) or not all(isinstance(v, str) and v for v in values):
                raise ValueError(f"feature_catalog.json: {name} needs two or more different text options")
        elif kind == "yesno":
            if [option["value"] for option in question.get("options", [])] != ["1", "0"]:
                raise ValueError(f"feature_catalog.json: {name} must offer exactly Yes (1) and No (0)")
        elif kind == "number":
            if not question["min"] < question["max"]:
                raise ValueError(f"feature_catalog.json: {name} has an empty range")
        elif kind == "bmi":
            for part in ("height", "weight"):
                if not question[part]["min"] < question[part]["max"]:
                    raise ValueError(f"feature_catalog.json: {name} {part} has an empty range")
        elif kind == "derived":
            if question.get("rule") != "bmi_at_least" or question.get("of") not in seen:
                raise ValueError(f"feature_catalog.json: {name} is derived by a rule this program does not know")
        if "asked_through" in question:
            _check_asked_through(question)
        if "derived_from" in question:
            _check_derived_from(question, catalog)


def _check_asked_through(question):
    """A choice asked THROUGH another question (Sex, asked through Gender): every Gender option either names the
    sex it implies (one of the question's own options) or names none, in which case the question is asked itself."""
    spec, name = question["asked_through"], question["name"]
    if question["kind"] != "choice" or not spec.get("field") or spec["field"] == name:
        raise ValueError(f"feature_catalog.json: {name} is asked through a field that is missing or is itself")
    values = [option.get("value") for option in spec.get("options", [])]
    if len(values) < 2 or len(set(values)) != len(values) or not all(isinstance(v, str) and v for v in values):
        raise ValueError(f"feature_catalog.json: {spec['field']} needs two or more different text options")
    own = {option["value"] for option in question["options"]}
    for option in spec["options"]:
        if "sex" in option and option["sex"] not in own:
            raise ValueError(f"feature_catalog.json: {spec['field']} option '{option['value']}' implies an answer {name} does not offer")


def feature_names(catalog):
    """The model inputs, in catalog order (a derived input such as Obesity counts: the model uses it)."""
    return [question["name"] for question in catalog["questions"]]


def question_for(catalog, name):
    return next(question for question in catalog["questions"] if question["name"] == name)


def _check_derived_from(question, catalog):
    """A choice worked out from a number (activity level from exercise hours): ascending bands, every value an option."""
    spec, name = question["derived_from"], question["name"]
    source = next((q for q in catalog["questions"] if q["name"] == spec.get("field")), None)
    if question["kind"] != "choice" or source is None or source["kind"] != "number" or spec.get("rule") != "hour_bands":
        raise ValueError(f"feature_catalog.json: {name} is derived from a field that is missing or not a number")
    bands, own = spec.get("bands") or [], {o["value"] for o in question["options"]}
    limits = [band["below"] for band in bands[:-1]]
    if not bands or bands[-1]["below"] is not None or limits != sorted(limits) or not all(isinstance(x, (int, float)) for x in limits) \
            or {band["value"] for band in bands} != own:
        raise ValueError(f"feature_catalog.json: {name}'s bands must rise, end open, and cover every option")


def derive_choice(question, number):
    """The option a number falls in ("2.5 hours" -> "Moderate"), by the question's bands. None if there is no number."""
    if number is None:
        return None
    for band in question["derived_from"]["bands"]:
        if band["below"] is None or number < band["below"]:
            return band["value"]
    return None


def asked_through(catalog, name="Sex"):
    """The question a model input is asked through ({field, label, options...}), or None. Sex is asked through
    Gender: the person's own answer is saved and shown, and the model gets the sex it implies."""
    question = next((q for q in catalog["questions"] if q["name"] == name), None)
    return None if question is None else question.get("asked_through")


def implied(spec, answer):
    """The answer a Gender option implies for the underlying question ("Gay man" -> "Male"), or None when it does
    not tell (Non-binary, Prefer not to say...) - then the underlying question is asked as well."""
    option = next((o for o in spec["options"] if o["value"] == answer), None)
    return None if option is None else option.get("sex")


def gender_label(catalog, value):
    """A saved Gender answer in words, or None."""
    spec = asked_through(catalog)
    if spec is None or value in (None, ""):
        return None
    return next((o["label"] for o in spec["options"] if o["value"] == value), str(value))


def model_values(question):
    """The answers the MODEL must accept for this input: text choices (an option's model_value when it has one - e.g.
    Philippines is shown and saved as itself but given to the model as Other), or 0 and 1 for yes/no. None otherwise."""
    if question["kind"] == "choice":
        return {option.get("model_value", option["value"]) for option in question["options"]}
    if question["kind"] == "yesno":
        return {0, 1}
    return None


def valid_range(spec):
    """(low, high) an answer is ACCEPTED within: the realistic limits when the catalog gives them, else the training range."""
    return spec.get("valid_min", spec["min"]), spec.get("valid_max", spec["max"])


def to_model_values(catalog, values):
    """The same answers with every choice translated to what the MODEL was trained on (Philippines -> Other).
    The saved answers keep the person's own choice; only the model sees the translation."""
    translated = dict(values)
    for question in catalog["questions"]:
        if question["kind"] != "choice" or question["name"] not in translated:
            continue
        for option in question["options"]:
            if "model_value" in option and translated[question["name"]] == option["value"]:
                translated[question["name"]] = option["model_value"]
    return translated


def outside_training(catalog, inputs):
    """[(label, value text, training range text), ...] for every saved answer the model never saw in training - a
    country it only knows as "Other", or a number outside the range it learned from. Shown on the result so an
    estimate built on an extrapolation is never presented as if it were not one."""
    flagged = []
    for question in catalog["questions"]:
        name, kind = question["name"], question["kind"]
        if name not in inputs or inputs[name] is None:
            continue
        value = inputs[name]
        if kind == "choice":
            option = next((o for o in question["options"] if o["value"] == value), None)
            if option and "model_value" in option:
                flagged.append((question["short"], option["label"], f'the model knows it only as "{option["model_value"]}"'))
        elif kind in ("number", "bmi") and isinstance(value, (int, float)):
            if not question["min"] <= value <= question["max"]:
                unit = (" " + question["unit"]) if question.get("unit") else ""
                flagged.append((question["short"], f"{_fmt(value)}{unit}", f"the model learned from {_fmt(question['min'])} to {_fmt(question['max'])}{unit}"))
    return flagged


def _fmt(number):
    return f"{number:g}"


def _parse_number(text, whole):
    if not (WHOLE_PATTERN if whole else NUMBER_PATTERN).match(text):
        return None
    value = float(text)
    return int(value) if whole else value


def _derive(question, values):
    if question["rule"] == "bmi_at_least":
        return 1 if values[question["of"]] >= question["value"] else 0


def validate_answers(catalog, form, fixed=None):
    """
    Check what the person sent. Returns (values, inputs, errors):
      values - {model input: value} exactly as the model needs it (complete only when errors is empty)
      inputs - values plus the height and weight they typed (and their Gender); this is what is saved
      errors - {field name: message}. Empty means every answer is present and valid.
    `form` is anything with .get(): the submitted form, or a plain dict.
    `fixed`: names whose answer the server already decided (services/fixed_answers.py) - a Gender that implies a
    different sex than a fixed Sex is refused rather than silently changing it.
    """
    values, extra, errors = {}, {}, {}
    fixed = fixed or ()

    def text(key):
        value = form.get(key)
        return value.strip() if isinstance(value, str) else ""

    for question in catalog["questions"]:
        name, kind = question["name"], question["kind"]
        if kind == "choice" and "asked_through" in question:
            spec = question["asked_through"]
            field, gender, own = spec["field"], text(spec["field"]), {o["value"] for o in question["options"]}
            sex = text(name)
            if not gender:
                errors[field] = "Choose one answer."
                continue
            if gender not in {o["value"] for o in spec["options"]}:
                errors[field] = "Choose one of the answers shown."
                continue
            extra[field] = gender
            implied_sex = implied(spec, gender)
            if implied_sex and name in fixed and sex and sex != implied_sex:
                errors[field] = "This does not match the sex kept from the first screening. Choose another answer."
            elif implied_sex:
                values[name] = implied_sex                  # the gender tells: what the page sent for Sex is not needed
            elif not sex:
                errors[name] = "Choose the sex you were assigned at birth."
            elif sex not in own:
                errors[name] = "Choose one of the answers shown."
            else:
                values[name] = sex
        elif kind == "choice" and "derived_from" in question:
            continue                                            # worked out below, from its source answer - never typed
        elif kind == "choice":
            answer = text(name)
            if not answer:
                errors[name] = "Choose one answer."
            elif answer not in {option["value"] for option in question["options"]}:     # what the FORM offers (incl. Philippines)
                errors[name] = "Choose one of the answers shown."
            else:
                values[name] = answer
        elif kind == "yesno":
            answer = text(name)
            if answer not in ("1", "0"):
                errors[name] = "Choose Yes or No."
            else:
                values[name] = int(answer)
        elif kind == "number":
            answer = text(name)
            number = _parse_number(answer, question.get("integer", False)) if answer else None
            if not answer:
                errors[name] = "Enter a number."
            elif number is None:
                errors[name] = "Enter a whole number, for example 48." if question.get("integer") else "Use digits and a dot only, for example 1.8."
            elif not valid_range(question)[0] <= number <= valid_range(question)[1]:
                errors[name] = f"That does not look right. Enter a value from {_fmt(valid_range(question)[0])} to {_fmt(valid_range(question)[1])}."
            else:
                values[name] = number
        elif kind == "bmi":
            parts, ok = {}, True
            for part in ("height", "weight"):
                spec = question[part]
                answer = text(spec["field"])
                number = _parse_number(answer, False) if answer else None
                if not answer:
                    errors[spec["field"]] = "Enter a number."
                    ok = False
                elif number is None:
                    errors[spec["field"]] = "Use digits and a dot only, for example 62.5."
                    ok = False
                elif not valid_range(spec)[0] <= number <= valid_range(spec)[1]:
                    errors[spec["field"]] = f"That does not look right. Enter a value from {_fmt(valid_range(spec)[0])} to {_fmt(valid_range(spec)[1])} {spec['unit']}."
                    ok = False
                else:
                    parts[part] = number
            if ok:
                bmi = round(parts["weight"] / (parts["height"] / 100) ** 2, 1)
                if not valid_range(question)[0] <= bmi <= valid_range(question)[1]:
                    errors[name] = "That height and weight together do not look right - please check both."
                else:
                    values[name] = bmi
                    extra[question["height"]["field"]] = parts["height"]
                    extra[question["weight"]["field"]] = parts["weight"]
        elif kind == "derived":
            if question["of"] in values:
                values[name] = _derive(question, values)
    for question in catalog["questions"]:
        if question["kind"] == "choice" and "derived_from" in question:
            source = question["derived_from"]["field"]
            if source in values:                                # a wrong or missing source already has its own error
                values[question["name"]] = derive_choice(question, values[source])
    inputs = {**values, **extra}
    return values, inputs, errors


def fields_of(question):
    """Every form field a question is answered through: its own name, a BMI's height and weight, Sex's Gender."""
    fields = {question["name"]}
    if question["kind"] == "bmi":
        fields |= {question["height"]["field"], question["weight"]["field"]}
    if "asked_through" in question:
        fields.add(question["asked_through"]["field"])
    return fields


def steps_with_errors(catalog, errors):
    """The step keys holding a question with an error, so the form can open on the first of them."""
    return {q["step"] for q in catalog["questions"] if fields_of(q) & set(errors)}


def answer_text(question, inputs, brief=False):
    """
    One saved answer in words ('Yes', '48 years', 'Other country'), or None if it was not saved.
    brief=True leaves out the height and weight behind a BMI, so the answer reads well inside a sentence.
    """
    name, kind = question["name"], question["kind"]
    if name not in inputs:
        return None
    value = inputs[name]
    if kind == "choice":
        return next((o["label"] for o in question["options"] if o["value"] == value), str(value))
    if kind in ("yesno", "derived"):
        return "Yes" if value == 1 else "No"
    if kind == "number":
        return f"{_fmt(value)} {question['unit']}"
    height, weight = inputs.get(question["height"]["field"]), inputs.get(question["weight"]["field"])
    return f"{_fmt(value)}" + ("" if brief else (f" (height {_fmt(height)} cm, weight {_fmt(weight)} kg)" if height and weight else ""))


def describe_inputs(catalog, inputs):
    """
    The saved answers as words for the person to read: [(step title, [(label, text), ...]), ...].
    Only what is in `inputs` is shown; nothing is filled in.
    """
    steps = {step["key"]: (step["title"], []) for step in catalog["steps"]}
    for question in catalog["questions"]:
        spec = question.get("asked_through")
        if spec and inputs.get(spec["field"]) not in (None, ""):
            steps[question["step"]][1].append((spec["short"], gender_label(catalog, inputs[spec["field"]])))
        text = answer_text(question, inputs)
        if text is not None:
            steps[question["step"]][1].append((question["short"], text))
    return [(title, rows) for title, rows in steps.values() if rows]


def reference_row(catalog):
    """A valid, ordinary set of answers. Used only to check that a model file runs; never shown to anyone."""
    values = {}
    for question in catalog["questions"]:
        kind = question["kind"]
        if kind == "choice":
            values[question["name"]] = question["options"][0]["value"]
        elif kind == "yesno":
            values[question["name"]] = 0
        elif kind == "number":
            values[question["name"]] = question["min"]
        elif kind == "bmi":
            values[question["name"]] = 25.0
        else:
            values[question["name"]] = _derive(question, values)
    return values
