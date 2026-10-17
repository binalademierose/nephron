"""
lab_contract.py - the rules for a Stage 2 (Enhanced Screening) lab-value submission. Mirrors screening_contract.py's
job for Stage 1, but for a different situation: every lab field except Serum_Creatinine is OPTIONAL (a person may not
have every test), yet anything they DO give is checked the same way Stage 1 checks every answer - a number outside a
plausible range is refused, never silently accepted or clamped. Nothing here decides what the model does with a gap;
that is the Stage 2 model's own trained handling (see services/model_service.py and ml/model_stage2/README.md).
"""
import json
import os

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
    text = f"{value:g}"
    return text


def answer_text(field, value):
    """One saved lab value in words ('1.1 mg/dL'), or None if it was not given."""
    if value is None:
        return None
    return f"{_fmt(value)} {field['unit']}" if field.get("unit") else _fmt(value)


def validate_lab_values(catalog, form):
    """
    Check what the person typed or an OCR step proposed. Returns (values, errors):
      values  {lab field name: float}, only for fields that were given (never guessed for one left blank)
      errors  {field name: message}. Empty means every field that WAS given is a valid number in range, and
              Serum_Creatinine (the one required field) is present.
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
        try:
            number = float(raw)
        except (TypeError, ValueError):
            errors[name] = f"{field['short']} must be a number."
            continue
        if not (field["min"] <= number <= field["max"]):
            errors[name] = f"{field['short']} must be between {_fmt(field['min'])} and {_fmt(field['max'])} {field.get('unit', '')}.".replace("  ", " ")
            continue
        values[name] = number
    return values, errors


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
