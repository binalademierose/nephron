"""
fixed_answers.py - screening answers that are facts about the person, not something to re-enter (and possibly
change) every time:

  - Age comes from the date of birth, so it only ever changes on a birthday;
  - Country comes from the account (asked once at registration);
  - once a first Preliminary screening exists, Sex, Ethnicity and Country are kept as answered then.

fixed_for() says which answers are fixed and why; apply() puts them into a submitted form, so the SERVER enforces
them - a changed value in the page's HTML is simply replaced, never trusted.
"""
from werkzeug.datastructures import MultiDict

LOCKED_AFTER_FIRST = ("Sex", "Ethnicity", "Country")


def age_on(date_of_birth, today):
    """Whole years on `today` - it changes only on the birthday itself."""
    years = today.year - date_of_birth.year
    if (today.month, today.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return years


def fixed_for(date_of_birth, country, first_inputs, today):
    """{field: {"value": ..., "reason": ...}} for every answer that is fixed for this person right now.
    first_inputs: the saved answers of this person's EARLIEST preliminary screening, or None."""
    fixed = {}
    if date_of_birth is not None:
        fixed["Age"] = {"value": age_on(date_of_birth, today), "reason": "Worked out from your date of birth."}
    if country:
        fixed["Country"] = {"value": country, "reason": "From your account."}
    if first_inputs:
        for name in LOCKED_AFTER_FIRST:
            if first_inputs.get(name) not in (None, ""):
                fixed[name] = {"value": first_inputs[name], "reason": "Kept as answered in your first screening."}
    return fixed


def apply(form, fixed):
    """The submitted form with every fixed answer put in place (whatever the page sent for it)."""
    merged = MultiDict(form)
    for name, item in fixed.items():
        merged.setlist(name, [str(item["value"])])
    return merged


def earliest_preliminary_inputs(store, user_id):
    """The saved answers of the person's first preliminary screening, or None."""
    rows = [r for r in store.list_assessments(user_id) if r["assessment_type"] == "preliminary"]
    if not rows:
        return None
    first = min(rows, key=lambda r: (r["assessed_at"], r["assessment_id"]))
    saved = store.get_assessment(user_id, first["assessment_id"])
    return saved["inputs"] if saved else None
