"""
validation.py - checks what a person typed into a form.

Everything here is a plain function with no Flask and no database, so it is easy to read and to test.
Each check returns an error message for the person to read, or None when the value is fine.
The messages say what to do next and never reveal anything about other accounts.
"""
import re
from datetime import date

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LICENSE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./-]*$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
MIN_REGISTRATION_AGE = 18
MAX_REGISTRATION_AGE = 120
ADDRESS_MAX_LENGTH = 255

ROLES = ("general", "professional")          # there is no administrator role in this version
ROLE_LABELS = {"general": "General User", "professional": "Healthcare Professional", "admin": "Administrator"}
PROFESSIONS = ("Nephrologist", "Physician", "Nurse", "Other health professional")

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128

# Passwords that are guessed first. Only ones of 10+ characters matter, because shorter ones are refused anyway.
COMMON_PASSWORDS = frozenset({
    "1234567890", "0123456789", "12345678910", "123456789012", "1234567890123",
    "password123", "password1234", "passw0rd123", "password12345", "qwertyuiop", "qwerty12345", "qwerty123456",
    "1q2w3e4r5t", "1qaz2wsx3edc", "iloveyou123", "welcome123", "welcome1234", "letmein1234", "administrator",
    "abcdefghij", "abc1234567", "changeme123", "admin123456", "internet123", "football123", "monkey12345",
    "dragon12345", "sunshine123", "princess123", "superman123", "baseball123", "trustno1234", "asdfghjkl1",
    "nephron123", "nephron1234", "nephron2026", "kidneyhealth",
})


def clean_email(value):
    """Trim the spaces and use lower case, so 'Ana@Mail.com ' and 'ana@mail.com' are the same address."""
    return (value or "").strip().lower()


def clean_text(value):
    """Trim the ends and squeeze repeated spaces into one."""
    return " ".join((value or "").split())


def check_email(email):
    if not email:
        return "Enter your email address."
    if len(email) > 254 or not EMAIL_PATTERN.match(email):
        return "Enter a complete email address, such as name@example.com."
    return None


def check_full_name(name):
    if not name:
        return "Enter your full name."
    if len(name) < 2 or len(name) > 120:
        return "Use between 2 and 120 characters."
    if not name.isprintable() or not any(character.isalpha() for character in name):
        return "Enter your name using letters."
    return None


def check_username(username):
    if not username:
        return "Choose a username."
    if len(username) < USERNAME_MIN_LENGTH or len(username) > USERNAME_MAX_LENGTH:
        return f"Use {USERNAME_MIN_LENGTH} to {USERNAME_MAX_LENGTH} characters."
    if not USERNAME_PATTERN.match(username):
        return "Start with a letter, then use only letters, numbers or underscores."
    return None


def check_confirm_password(password, confirm_password):
    if not confirm_password:
        return "Type your password again to confirm it."
    if password != confirm_password:
        return "The passwords do not match."
    return None


def _country_options():
    """The screening's own Country answers (value, label) - one list for registration and the screening, so a
    country chosen at sign-up is always one the screening understands."""
    import json, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "feature_catalog.json")
    with open(path, encoding="utf-8") as handle:
        catalog = json.load(handle)
    question = next(q for q in catalog["questions"] if q["name"] == "Country")
    return [(option["value"], option["label"]) for option in question["options"]]


COUNTRY_OPTIONS = _country_options()
COUNTRY_VALUES = {value for value, _ in COUNTRY_OPTIONS}


def _gender_options():
    """The screening's own Gender answers (value, label, the sex it implies or ""), for the patient-record form."""
    import json, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "feature_catalog.json")
    with open(path, encoding="utf-8") as handle:
        catalog = json.load(handle)
    spec = next(q for q in catalog["questions"] if q["name"] == "Sex").get("asked_through", {"options": []})
    return [(option["value"], option["label"], option.get("sex", "")) for option in spec["options"]]


GENDER_OPTIONS = _gender_options()
GENDER_SEX = {value: sex for value, _, sex in GENDER_OPTIONS}


def check_date_of_birth(value, today=None):
    """value: the exact text typed into the date field. Returns (error, parsed_date) - parsed_date is None
    whenever there is an error, so a caller can never accidentally use a half-valid date."""
    today = today or date.today()
    if not value:
        return "Enter your date of birth.", None
    try:
        year, month, day = (int(part) for part in value.split("-"))
        parsed = date(year, month, day)
    except (ValueError, TypeError):
        return "Enter a valid date.", None
    if parsed > today:
        return "Date of birth cannot be in the future.", None
    age = (today.year - parsed.year) - ((today.month, today.day) < (parsed.month, parsed.day))
    if age < MIN_REGISTRATION_AGE:
        return f"You must be at least {MIN_REGISTRATION_AGE} years old to create an account.", None
    if age > MAX_REGISTRATION_AGE:
        return "Enter a valid date of birth.", None
    return None, parsed


def check_address(address):
    if address and len(address) > ADDRESS_MAX_LENGTH:
        return f"Use no more than {ADDRESS_MAX_LENGTH} characters."
    return None


AVATARS = tuple(f"avatar-{n}" for n in range(1, 9))


def check_avatar(avatar):
    if avatar not in AVATARS:
        return "Choose a profile picture."
    return None


def check_password(password, email="", full_name=""):
    """
    Length matters far more than tricks, so the rules are few: long enough, not a well-known password,
    and not built from the person's own email address.
    """
    if not password:
        return "Enter a password."
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Use no more than {PASSWORD_MAX_LENGTH} characters."
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) <= 2:
        return "That password is too easy to guess. Choose something less common."
    local_part = email.split("@")[0]
    if email and (lowered == email or (len(local_part) >= 4 and local_part in lowered)):
        return "Do not use your email address in your password."
    return None


def validate_registration(form):
    """
    Check the register form. Returns (values, errors):
      values - the cleaned input, ready to use if there are no errors
      errors - {field name: message}. Empty means everything is fine.
    """
    errors = {}
    role = (form.get("role") or "").strip()
    email = clean_email(form.get("email"))
    full_name = clean_text(form.get("full_name"))
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""
    username = clean_text(form.get("username")).replace(" ", "")
    address = clean_text(form.get("address"))
    avatar = (form.get("avatar") or "").strip()

    if role not in ROLES:
        errors["role"] = "Choose how you will use Nephron."
    for field, message in (("email", check_email(email)), ("full_name", check_full_name(full_name)),
                           ("password", check_password(password, email, full_name)),
                           ("confirm_password", check_confirm_password(password, confirm_password)),
                           ("username", check_username(username)), ("address", check_address(address)),
                           ("avatar", check_avatar(avatar))):
        if message:
            errors[field] = message

    dob_error, date_of_birth = check_date_of_birth(form.get("date_of_birth"))
    if dob_error:
        errors["date_of_birth"] = dob_error
    country = (form.get("country") or "").strip()
    if role == "general" and country not in COUNTRY_VALUES:
        errors["country"] = "Choose the country you live in."
    from services import ph_locations
    location, location_errors = ph_locations.validate(country if role == "general" else None, form)
    errors.update(location_errors)

    professional = None
    if role == "professional":
        profession = clean_text(form.get("profession_title"))
        institution = clean_text(form.get("institution"))
        license_number = clean_text(form.get("license_number"))
        if profession not in PROFESSIONS:
            errors["profession_title"] = "Choose your profession from the list."
        if len(institution) > 120:
            errors["institution"] = "Use no more than 120 characters."
        if license_number and (len(license_number) > 50 or not LICENSE_PATTERN.match(license_number)):
            errors["license_number"] = "Use letters, numbers, spaces, dots, dashes or slashes (up to 50)."
        professional = {"profession_title": profession, "institution": institution or None,
                        "license_number": license_number or None}

    values = {"role": role, "email": email, "full_name": full_name, "password": password, "username": username or None,
              "date_of_birth": date_of_birth, "address": address or None, "avatar": avatar or None, "professional": professional,
              "country": country if country in COUNTRY_VALUES else None, **location}
    return values, errors


def validate_password_change(current_password, new_password, email, full_name):
    """Check the change-password form. Returns {field name: message}."""
    errors = {}
    if not current_password:
        errors["current_password"] = "Enter your current password."
    message = check_password(new_password, email, full_name)
    if message:
        errors["new_password"] = message
    elif new_password == current_password:
        errors["new_password"] = "Choose a password that is different from your current one."
    return errors


# Titles at the front of a name. They are not part of the name a person is greeted by or the letters on their avatar.
TITLES = frozenset({"dr", "dra", "mr", "mrs", "ms", "mx", "miss", "engr", "atty", "prof", "sir", "madam", "nurse", "rn", "fr", "rev"})


def _name_parts(full_name):
    """The words of a name without the titles in front: 'Dr. Luis Cruz' -> ['Luis', 'Cruz']."""
    parts = full_name.split()
    while len(parts) > 1 and parts[0].rstrip(".").lower() in TITLES:
        parts = parts[1:]
    return parts


def first_name(full_name):
    """
    The name used to greet someone: 'Dr. Luis Cruz' -> 'Luis'.
    'Ma.' is short for Maria and is only half a name, so it keeps the next word: 'Ma. Cristina Dela Cruz' -> 'Ma. Cristina'.
    """
    parts = _name_parts(full_name)
    if not parts:
        return ""
    if parts[0].lower() in ("ma.", "ma") and len(parts) > 1:
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def initials(full_name):
    """'Ana Reyes' -> 'AR', 'Dr. Luis Cruz' -> 'LC'.  A single name gives one letter."""
    letters = [part[0].upper() for part in _name_parts(full_name) if part[0].isalpha()]
    return (letters[0] + letters[-1]) if len(letters) > 1 else "".join(letters)
