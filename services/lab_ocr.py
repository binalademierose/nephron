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
# One lab number as printed on a report: "1.2", "112", or with thousands separators "12,000" / "1,250.5" - with no
# cap on its size, because an abnormal result (a urine ACR of 12,000 mg/g) is exactly what a kidney patient's report
# may show. Grouped digits are tried first, so "12,000" is never cut short to "12".
_NUMBER = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"

_PATTERNS = {
    "HbA1c": [r"Hb.{0,2}A.{0,2}1.{0,2}c\D{0,15}?(\d{1,2}\.\d)", r"(?:Hemoglobin|Glycated)\s*A1c\D{0,15}?(\d{1,2}\.\d)"],
    # not the "...Creatinine Ratio" of a urine ACR, and not urine creatinine (a different test)
    "Serum_Creatinine": [r"(?<!Urine )(?:Serum\s*)?Creatinine(?!\s*Ratio)\D{0,15}?" + _NUMBER],
    "Blood_Urea_Nitrogen": [r"(?:Blood\s*Urea\s*Nitrogen|BUN)\D{0,15}?" + _NUMBER],
    "Urine_ACR": [r"(?:Urine\s*)?Albumin[- ]?(?:to|/)[- ]?Creatinine\s*Ratio\D{0,15}?" + _NUMBER,
                 r"\bU?ACR\b\D{0,15}?" + _NUMBER],
    "Albumin": [r"\bAlbumin\b(?!\D{0,25}(?:creatinine|/creat|ratio))\D{0,15}?" + _NUMBER],
    "Urine_Protein": [r"Urine\s*Protein\D{0,15}?" + _NUMBER, r"Proteinuria\D{0,15}?" + _NUMBER],
    "Fasting_Glucose": [r"Fasting\s*(?:Blood\s*)?(?:Glucose|Sugar|FBS)\D{0,15}?" + _NUMBER],
    "Hemoglobin": [r"\bHemoglobin\b(?!\D{0,10}A1c)\D{0,15}?" + _NUMBER],
    "Sodium": [r"\bSodium\b\D{0,15}?" + _NUMBER],
    "Potassium": [r"\bPotassium\b\D{0,15}?" + _NUMBER],
    "Calcium": [r"\bCalcium\b(?!\D{0,15}(?:channel|score))\D{0,15}?" + _NUMBER],
    "Phosphorus": [r"\bPhosphorus\b\D{0,15}?" + _NUMBER, r"\bPhosphate\b\D{0,15}?" + _NUMBER],
    "Uric_Acid": [r"Uric\s*Acid\D{0,15}?" + _NUMBER],
    "Total_Cholesterol": [r"Total\s*Cholesterol\D{0,15}?" + _NUMBER, r"Cholesterol,?\s*Total\D{0,15}?" + _NUMBER],
    "HDL": [r"\bHDL\b(?:[- ]?Cholesterol|\s*\(HDL\))?\D{0,15}?" + _NUMBER],
    "LDL": [r"\bLDL\b(?:[- ]?Cholesterol|\s*\(LDL\))?\D{0,15}?" + _NUMBER],
    "Triglycerides": [r"Triglycerides\D{0,15}?" + _NUMBER],
    "CRP": [r"(?:C[- ]?Reactive\s*Protein|CRP)\D{0,15}?" + _NUMBER],
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
    {lab field name: number} for every field a value was found for. A reading outside the field's usual range is
    KEPT (an abnormal result is exactly what a kidney patient's report may show), never dropped: the confirm page
    marks it as unusual and asks the person to check it against the report before anything is analysed
    (services/lab_contract.unusual_values), so a misread digit is caught by a person, not silently thrown away.
    """
    from services import lab_contract

    found = {}
    for name, patterns in _PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            number = lab_contract.parse_lab_number(match.group(1))
            if number is not None and number >= 0:
                found[name] = number
            break
    return found
