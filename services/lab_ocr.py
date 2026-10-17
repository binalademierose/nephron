"""
lab_ocr.py - best-effort extraction of lab values from an uploaded document (image or PDF).

This NEVER produces an authoritative answer. Per the project's design (and the blueprint's own words: "editable
values, human verification"), whatever this finds is only ever shown to the person as a SUGGESTED starting point on
the confirmation form (see routes/lab_routes.py); nothing here is saved to an assessment until the person reviews
and confirms it there, where lab_contract.validate_lab_values() checks it again from scratch, the same as anything
the person typed by hand. A field this cannot find, or a number that reads outside the field's plausible range (a
common sign of a misread), is simply left blank for the person to fill in - never guessed, never invented, and
never silently kept if it looks wrong.

Real print quality varies a lot, so this only aims to catch the common, clearly-labelled case (see tests for what
it does and does not attempt). Poor photos, unusual report layouts, or handwriting will legitimately find little
or nothing - that is the correct behaviour, not a bug to work around with guessing.
"""
import re

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}

# Each field: an ordered list of regex patterns to try (most specific / least ambiguous first). A pattern captures
# ONE number. Deliberately excludes bare single-letter chemistry symbols (Na, K, Ca, P) as a way to find a value -
# real reports print those, but matching on a single letter anywhere in noisy OCR text is far too likely to catch
# the wrong number, so those fields rely on their full name being present instead.
_PATTERNS = {
    "HbA1c": [r"Hb.{0,2}A.{0,2}1.{0,2}c\D{0,15}?(\d{1,2}\.\d)", r"(?:Hemoglobin|Glycated)\s*A1c\D{0,15}?(\d{1,2}\.\d)"],
    "Serum_Creatinine": [r"(?:Serum\s*)?Creatinine\D{0,15}?(\d{1,2}\.?\d*)"],
    "Blood_Urea_Nitrogen": [r"(?:Blood\s*Urea\s*Nitrogen|BUN)\D{0,15}?(\d{1,3}\.?\d*)"],
    "Urine_ACR": [r"(?:Urine\s*)?Albumin[- ]?(?:to|/)[- ]?Creatinine\s*Ratio\D{0,15}?(\d{1,4}\.?\d*)",
                 r"\bU?ACR\b\D{0,15}?(\d{1,4}\.?\d*)"],
    "Albumin": [r"\bAlbumin\b(?!\D{0,25}(?:creatinine|/creat|ratio))\D{0,15}?(\d{1,2}\.?\d*)"],
    "Urine_Protein": [r"Urine\s*Protein\D{0,15}?(\d{1,4}\.?\d*)", r"Proteinuria\D{0,15}?(\d{1,4}\.?\d*)"],
    "Fasting_Glucose": [r"Fasting\s*(?:Blood\s*)?(?:Glucose|Sugar|FBS)\D{0,15}?(\d{1,3}\.?\d*)"],
    "Hemoglobin": [r"\bHemoglobin\b(?!\D{0,10}A1c)\D{0,15}?(\d{1,2}\.?\d*)"],
    "Sodium": [r"\bSodium\b\D{0,15}?(\d{2,3}\.?\d*)"],
    "Potassium": [r"\bPotassium\b\D{0,15}?(\d\.?\d*)"],
    "Calcium": [r"\bCalcium\b(?!\D{0,15}(?:channel|score))\D{0,15}?(\d{1,2}\.?\d*)"],
    "Phosphorus": [r"\bPhosphorus\b\D{0,15}?(\d\.?\d*)", r"\bPhosphate\b\D{0,15}?(\d\.?\d*)"],
    "Uric_Acid": [r"Uric\s*Acid\D{0,15}?(\d{1,2}\.?\d*)"],
    "Total_Cholesterol": [r"Total\s*Cholesterol\D{0,15}?(\d{2,3}\.?\d*)", r"Cholesterol,?\s*Total\D{0,15}?(\d{2,3}\.?\d*)"],
    "HDL": [r"\bHDL\b(?:[- ]?Cholesterol|\s*\(HDL\))?\D{0,15}?(\d{1,3}\.?\d*)"],
    "LDL": [r"\bLDL\b(?:[- ]?Cholesterol|\s*\(LDL\))?\D{0,15}?(\d{1,3}\.?\d*)"],
    "Triglycerides": [r"Triglycerides\D{0,15}?(\d{1,3}\.?\d*)"],
    "CRP": [r"(?:C[- ]?Reactive\s*Protein|CRP)\D{0,15}?(\d{1,2}\.?\d*)"],
    "Systolic_BP": [r"Blood\s*Pressure\D{0,10}?(\d{2,3})\s*/\s*\d{2,3}", r"\bBP\D{0,10}?(\d{2,3})\s*/\s*\d{2,3}"],
    "Diastolic_BP": [r"Blood\s*Pressure\D{0,10}?\d{2,3}\s*/\s*(\d{2,3})", r"\bBP\D{0,10}?\d{2,3}\s*/\s*(\d{2,3})"],
}


class UnreadableDocument(ValueError):
    """The file could not be turned into text at all (not a supported type, or corrupt)."""


def extract_text(file_path, content_type, tesseract_cmd=None):
    """
    The raw OCR text of an uploaded lab document. Supports the same image types the upload form accepts, plus PDF
    (each page is rasterised, then read the same way). Raises UnreadableDocument for anything else, or a file that
    exists but cannot actually be opened as that type - never returns a guess at what the text might have said.
    tesseract_cmd: the full path to the tesseract program, only needed when it is not already on PATH (common on
    Windows) - pass current_app.config["TESSERACT_CMD"] when it is set; None (the default) uses PATH, same as
    pytesseract's own default.
    """
    import pytesseract
    from PIL import Image, UnidentifiedImageError

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    if content_type == "application/pdf":
        from pdf2image import convert_from_path
        try:
            pages = convert_from_path(file_path)
            return "\n".join(pytesseract.image_to_string(page) for page in pages)
        except Exception as error:
            # OCR is best-effort by design (see this module's own docstring): a problem running tesseract itself -
            # not installed, not on PATH, TESSERACT_CMD pointing at the wrong thing, no permission to run it, an
            # antivirus block - is treated exactly like a page that could not be read, never a crash of the upload.
            raise UnreadableDocument(f"could not read this PDF ({type(error).__name__}: {error})") from error
    if content_type in ALLOWED_CONTENT_TYPES:
        try:
            image = Image.open(file_path)
        except (UnidentifiedImageError, OSError) as error:
            raise UnreadableDocument(f"could not read this image ({type(error).__name__})") from error
        try:
            return pytesseract.image_to_string(image)
        except Exception as error:
            raise UnreadableDocument(f"could not run OCR on this image ({type(error).__name__}: {error})") from error
    raise UnreadableDocument(f"unsupported file type: {content_type}")


def extract_candidate_values(text, catalog):
    """
    {lab field name: number} for every field a plausible-looking value was found for. A match outside the field's
    own catalog range (a common sign of a misread digit) is left out rather than offered as a confident-looking
    wrong answer - the person then simply sees that field blank, the same as if nothing had been found at all.
    """
    from services import lab_contract

    fields = {f["name"]: f for f in catalog["fields"]}
    found = {}
    for name, patterns in _PATTERNS.items():
        field = fields[name]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            try:
                number = float(match.group(1))
            except ValueError:
                continue
            if field["min"] <= number <= field["max"]:
                found[name] = number
            break
    return found
