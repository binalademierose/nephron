"""
lab_verification.py - signs, read from an uploaded lab report's own text, that it is a real report about the
right person: the name on it, how recent its date is, whether it is signed or attested by a lab professional, and
whether it names a laboratory or hospital.

These are SIGNS, never proof. A photo or PDF cannot prove that a report is genuine - a well-made fake would pass
every check here, and a real report photographed badly might fail some. So nothing here ever blocks an upload or
changes a value: the results are shown to the person beside the values (templates/lab/confirm.html), and the
person must still confirm that the report is theirs (or their patient's) before anything is analysed.
"""
import re
from datetime import date

RECENT_DAYS = 180          # a report older than about six months is flagged as old (still accepted)

NAME_LABELS = re.compile(r"(?:patient(?:'s)?\s*name|patient|name)\s*[:\-]\s*([A-Za-z][A-Za-z .,'\-]{1,60}?)(?=\s{2,}|\s+(?:date|age|sex|gender|dob|id|no\.?)\b|$)",
                         re.I | re.M)
DATE_LABEL = re.compile(r"(?:date|collected|reported|released|specimen)", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DATE_PATTERNS = (
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b"), "month_name"),
)
SIGNATURE_SIGNS = (
    ("Pathologist", r"\bpatholog(?:ist|y)\b"), ("Medical technologist", r"\bmed(?:ical)?\.?\s*tech(?:nologist)?\b|\bRMT\b"),
    ("Licence / PRC number", r"\b(?:lic(?:ense|ence)?\.?\s*(?:no|number|#)|PRC)\b"), ("Signature", r"\bsign(?:ature|ed)\b"),
    ("Verified / validated by", r"\b(?:verified|validated|certified|released)\s+by\b"), ("Physician (MD)", r"\bM\.?D\.?\b"),
)
FACILITY_SIGNS = r"\b(?:hospital|medical cent(?:er|re)|laborator(?:y|ies)|diagnostic|clinic)\b"


def _words(name):
    return [w for w in re.findall(r"[a-z]+", (name or "").lower()) if len(w) > 1]


def _check_name(text, expected_name):
    expected = set(_words(expected_name))
    labelled = NAME_LABELS.search(text)
    if labelled:
        found = labelled.group(1).strip(" .,")
        overlap = expected & set(_words(found))
        # Same person if at least two name words match (first + last), or the only word given matches.
        status = "match" if len(overlap) >= min(2, len(expected)) else "mismatch"
        return {"status": status, "found": found}
    if expected and expected <= set(_words(text)):
        return {"status": "match", "found": expected_name}
    return {"status": "missing", "found": None}


def _parse(match, kind):
    try:
        if kind == "ymd":
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if kind == "mdy":
            return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        month = MONTHS.get(match.group(1)[:3].lower())
        return date(int(match.group(3)), month, int(match.group(2))) if month else None
    except ValueError:
        return None


def _check_date(text, today):
    labelled, anywhere = [], []
    for line in text.splitlines():
        for pattern, kind in DATE_PATTERNS:
            for match in pattern.finditer(line):
                parsed = _parse(match, kind)
                if parsed is None or parsed.year < 1990:
                    continue
                (labelled if DATE_LABEL.search(line[:match.start()]) else anywhere).append(parsed)
    candidates = labelled or anywhere
    if not candidates:
        return {"status": "missing", "found": None, "age_days": None}
    found = max(d for d in candidates if d <= today) if any(d <= today for d in candidates) else min(candidates)
    age = (today - found).days
    status = "future" if age < 0 else "old" if age > RECENT_DAYS else "recent"
    return {"status": status, "found": found.isoformat(), "age_days": age}


def check(text, expected_name, today):
    """{"name": ..., "date": ..., "signature": ..., "facility": ...} - each a small dict with a "status"."""
    text = text or ""
    signs = [label for label, pattern in SIGNATURE_SIGNS if re.search(pattern, text, re.I)]
    facility = re.search(FACILITY_SIGNS, text, re.I)
    return {
        "name": _check_name(text, expected_name),
        "date": _check_date(text, today),
        "signature": {"status": "found" if signs else "missing", "found": signs},
        "facility": {"status": "found" if facility else "missing", "found": facility.group(0) if facility else None},
    }


def concerns(result):
    """How many checks did not pass - used to word the summary line."""
    if not result:
        return 0
    return sum(1 for key, good in (("name", "match"), ("date", "recent"), ("signature", "found"), ("facility", "found"))
               if result.get(key, {}).get("status") != good)
