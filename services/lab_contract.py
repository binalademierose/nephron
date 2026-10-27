"""
lab_contract.py - the rules for a Stage 2 (Enhanced Screening) lab-value submission. Every lab field except
Serum_Creatinine is OPTIONAL (a person may not have every test).

Any real lab value is ACCEPTED, however abnormal: a failing kidney gives abnormal numbers, and those are exactly the
results a nephrologist needs to enter (a urine ACR of 8,000 mg/g, triglycerides of 1,200 mg/dL). Only what cannot be
a lab value at all is refused: something that is not a number, a negative number, and a creatinine of 0 (eGFR cannot
be worked out from it). A thousands separator is fine ("1,000").

Each field's "min"/"max" in ml/lab_catalog.json is the range Nephron normally EXPECTS for that test - no longer a
limit. A value outside it is still accepted, but the person is asked once to check it and its unit (a creatinine of
1000 is far more likely to be umol/L typed into the mg/dL box than a real mg/dL value) - see unusual_values() - and
the saved result says the value was outside that range (outside_usual_range()), so an estimate built on it is never
presented as an ordinary one. Nothing here decides what the model does with a gap; that is the Stage 2 model's own
trained handling (see services/model_service.py and ml/model_stage2/README.md).
"""
import json
import math
import os
import re

from services.egfr import estimate_gfr

_CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "lab_catalog.json")
_catalog_cache = None


def load_lab_catalog():
    global _catalog_cache
    if _catalog_cache is None:
        with open(_CATALOG_PATH, encoding="utf-8") as handle:
            catalog = json.load(handle)
        check_lab_catalog(catalog)
        _catalog_cache = catalog
    return _catalog_cache


def check_lab_catalog(catalog):
    """Raise ValueError, in plain words, if ml/lab_catalog.json itself is malformed. (It is edited by people.)"""
    groups = {g["key"] for g in catalog.get("groups", [])}
    if not groups:
        raise ValueError("lab_catalog.json: no groups are defined")
    seen = set()
    for field in catalog.get("fields", []):
        name = field.get("name")
        if not name:
            raise ValueError("lab_catalog.json: a field has no name")
        if name in seen:
            raise ValueError(f"lab_catalog.json: '{name}' is listed twice")
        seen.add(name)
        if field.get("group") not in groups:
            raise ValueError(f"lab_catalog.json: '{name}' has an unknown group {field.get('group')!r}")
        if field.get("min") is None or field.get("max") is None or field["min"] >= field["max"]:
            raise ValueError(f"lab_catalog.json: '{name}' needs a min below its max")
    if not any(f.get("required") for f in catalog["fields"]):
        raise ValueError("lab_catalog.json: no field is marked required (Serum_Creatinine must be)")


def field_names(catalog):
    return [f["name"] for f in catalog["fields"]]


def field_for(catalog, name):
    return next(f for f in catalog["fields"] if f["name"] == name)


def _fmt(value):
    """A lab number as people write it: '1.1', '45', '12,000', '1,250,000.5' - never '1.25e+06'."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def answer_text(field, value):
    """One saved lab value in words ('1.1 mg/dL'), or None if it was not given."""
    if value is None:
        return None
    return f"{_fmt(value)} {field['unit']}" if field.get("unit") else _fmt(value)


# "1000", "1000.5", ".5", and with thousands separators "1,000" / "1 000" / "12,500.75". Not "1e5", "nan" or "inf".
_PLAIN_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
_GROUPED_NUMBER = re.compile(r"[+-]?\d{1,3}(?:[, ]\d{3})+(?:\.\d*)?")


def parse_lab_number(raw):
    """A typed (or OCR-read, or JSON) lab value as a float, or None if it is not a real number."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        number = float(raw)
    else:
        text = str(raw).strip()
        if _GROUPED_NUMBER.fullmatch(text):
            text = text.replace(",", "").replace(" ", "")
        if not _PLAIN_NUMBER.fullmatch(text):
            return None
        number = float(text)
    return number if math.isfinite(number) else None


def validate_lab_values(catalog, form):
    """
    Check what the person typed or an OCR step proposed. Returns (values, errors):
      values  {lab field name: float}, only for fields that were given (never guessed for one left blank)
      errors  {field name: message}. Empty means every field that WAS given is a real lab value, and
              Serum_Creatinine (the one required field) is present.
    There is no upper limit (see the module docstring): a value outside the usual range is reported by
    unusual_values() for the person to check, not refused here.
    `form` values may be strings (from an HTML form) or numbers (from a confirmed-values JSON blob); a blank
    string is treated the same as an absent field.
    """
    values, errors = {}, {}
    for field in catalog["fields"]:
        name = field["name"]
        raw = form.get(name)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            if field.get("required"):
                errors[name] = f"{field['short']} is required."
            continue
        number = parse_lab_number(raw)
        if number is None:
            errors[name] = f"{field['short']} must be a number, for example 1.2 or 1,000."
            continue
        if number < 0:
            errors[name] = f"{field['short']} cannot be a negative number."
            continue
        if number == 0 and field.get("must_be_positive"):
            errors[name] = f"{field['short']} must be more than 0."
            continue
        values[name] = number
    return values, errors


def usual_range_text(field):
    unit = f" {field['unit']}" if field.get("unit") else ""
    return f"{_fmt(field['min'])} to {_fmt(field['max'])}{unit}"


def unusual_values(catalog, values):
    """The given values outside the range Nephron normally expects for their test - accepted, but worth a second look
    (a misplaced decimal point, or a value in another unit). [{name, short, value, usual}, ...] in form order."""
    flagged = []
    for field in catalog["fields"]:
        value = values.get(field["name"])
        if value is not None and not field["min"] <= value <= field["max"]:
            flagged.append({"name": field["name"], "short": field["short"], "value": answer_text(field, value),
                            "usual": usual_range_text(field)})
    return flagged


def unusual_signature(flagged):
    """What the person's "these values are correct" tick confirms: exactly THESE unusual values. Changing any of them
    (or adding another) asks again, so a confirmation never carries over to numbers that were not on the screen."""
    return ";".join(f"{item['name']}={item['value']}" for item in flagged)


def unusual_errors(flagged, form):
    """{} the first time these unusual values are shown; an error on the tick box if they were already shown (the form
    carries their signature back in "unusual_shown") and the box was still not ticked - so the person is told why
    the form came back, instead of seeing the same page again."""
    if form.get("unusual_shown") == unusual_signature(flagged):
        return {"confirm_unusual": "Tick this box to confirm the values are correct, or change them."}
    return {}


def outside_usual_range(catalog, inputs):
    """For a saved result: [(label, value text, note), ...] for every lab value outside its usual range, in the same
    shape as screening_contract.outside_training() so the result page shows both in one notice."""
    return [(item["short"], item["value"], f"Nephron usually expects {item['usual']} for this test")
            for item in unusual_values(catalog, inputs or {})]


def with_egfr(lab_values, age, sex):
    """
    lab_values plus a computed "eGFR", when Serum_Creatinine is present (it is the only field eGFR needs besides
    the person's own age and sex, which come from their Preliminary assessment). Never asked for directly; never
    guessed if creatinine is missing.
    """
    result = dict(lab_values)
    if "Serum_Creatinine" in lab_values:
        result["eGFR"] = estimate_gfr(lab_values["Serum_Creatinine"], age, sex)
    return result


def describe_lab_values(catalog, values):
    """The given lab values as words, grouped the way the form groups them: [(group title, [(label, text), ...]), ...]."""
    groups = {g["key"]: (g["title"], []) for g in catalog["groups"]}
    for field in catalog["fields"]:
        text = answer_text(field, values.get(field["name"]))
        if text is not None:
            groups[field["group"]][1].append((field["short"], text))
    return [(title, rows) for title, rows in groups.values() if rows]
