"""
patient_records.py - the rules for a patient a professional is managing directly (see migration 015's own
comment for the "why" of the shadow-account design). Every function here is scoped to ONE professional; nothing
here ever looks across professionals.
"""
import secrets
import uuid

from services import security

MIN_AGE, MAX_AGE = 18, 95
SEX_OPTIONS = ("Female", "Male")


def _check_full_name(name):
    name = (name or "").strip()
    if not name:
        return "Enter the patient's full name."
    if len(name) < 2 or len(name) > 120:
        return "Use between 2 and 120 characters."
    if not name.isprintable() or not any(character.isalpha() for character in name):
        return "Enter the name using letters."
    return None


def _check_age(age_text):
    try:
        age = int(age_text)
    except (TypeError, ValueError):
        return None, "Enter a whole number for age."
    if age < MIN_AGE or age > MAX_AGE:
        return None, f"Enter an age between {MIN_AGE} and {MAX_AGE}."
    return age, None


def _check_sex(sex):
    return None if sex in SEX_OPTIONS else "Choose a sex."


def validate_new_patient(form, today=None):
    """(values, errors). values has clean full_name/date_of_birth/age/sex/country only once errors is empty.
    Age is worked out from the date of birth, never typed - see services/fixed_answers.py."""
    from datetime import date
    from services import fixed_answers
    from services.validation import COUNTRY_VALUES, GENDER_SEX
    today = today or date.today()
    errors = {}
    full_name = (form.get("full_name") or "").strip()
    if error := _check_full_name(full_name):
        errors["full_name"] = error
    date_of_birth, age = None, None
    try:
        date_of_birth = date.fromisoformat((form.get("date_of_birth") or "").strip())
    except ValueError:
        errors["date_of_birth"] = "Enter the patient's date of birth."
    else:
        age = fixed_answers.age_on(date_of_birth, today)
        if date_of_birth > today:
            errors["date_of_birth"] = "The date of birth cannot be in the future."
        elif not 1 <= age <= 120:
            errors["date_of_birth"] = "Check the date of birth - it gives an age outside 1 to 120."
    # Gender is saved as chosen; the sex the model needs comes from it (Gay man -> Male), and is asked as "sex
    # assigned at birth" only when it does not tell - the same rule as the screening (services/screening_contract.py).
    gender = (form.get("gender") or "").strip()
    sex = (form.get("sex") or "").strip()
    if gender not in GENDER_SEX:
        errors["gender"] = "Choose the patient's gender."
    elif GENDER_SEX[gender]:
        sex = GENDER_SEX[gender]
    elif error := _check_sex(sex):
        errors["sex"] = "Choose the sex the patient was assigned at birth."
    country = (form.get("country") or "").strip()
    if country not in COUNTRY_VALUES:
        errors["country"] = "Choose the country the patient lives in."
    from services import ph_locations
    location, location_errors = ph_locations.validate(country, form)
    errors.update(location_errors)
    return {"full_name": full_name, "date_of_birth": date_of_birth, "age": age, "sex": sex, "gender": gender, "country": country,
            "location": location}, errors


def register_patient(store, professional_user_id, full_name, age, sex, now, date_of_birth=None, country=None, gender=None, location=None):
    """Creates the patient record (and its shadow account) and returns (user_id, patient_code) - patient_code
    reads like "NPH-0001". The shadow account's email is never shown anywhere and its password is a random
    secret nobody is ever told - see services/auth_service.py, which also refuses to sign one in regardless."""
    shadow_email = f"patient-record-{uuid.uuid4().hex}@patient-records.nephron.invalid"
    password_hash = security.hash_password(secrets.token_urlsafe(24))
    return store.create(professional_user_id, full_name, age, sex, shadow_email, password_hash, now,
                        date_of_birth=date_of_birth, country=country, gender=gender, location=location)


def for_professional(store, professional_user_id, term=None):
    """This professional's own patient records, newest first, optionally narrowed to a name or patient code."""
    records = store.list_for_professional(professional_user_id)
    term = (term or "").strip().lower()
    if not term:
        return records
    return [r for r in records if term in r["full_name"].lower() or term in r["patient_code"].lower()]


def get_owned(store, user_id, professional_user_id):
    """The patient record, only if it is this professional's own - None otherwise, as if it did not exist."""
    if not store.owned_by(user_id, professional_user_id):
        return None
    return store.get_by_user_id(user_id)
