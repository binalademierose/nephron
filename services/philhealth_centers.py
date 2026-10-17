"""
philhealth_centers.py - the PhilHealth-accredited dialysis/kidney-care facility directory.

This is reference data, not something any user creates or changes, so it lives in one file
(data/philhealth_centers.json, built once from the PhilHealth-provided FDC_073126.xlsx by
scripts/build_philhealth_centers.py) rather than a database table - loaded once and cached, same pattern as
ml/feature_catalog.json and ml/lab_catalog.json.

Every facility, region, address and accreditation detail here comes directly from that file - nothing is invented,
guessed, or filled in. A phone number written two different ways in the source spreadsheet (with or without a
leading 0) is shown exactly as the source gives it, never "corrected" by a guess.
"""
import json
import os
import re
import unicodedata

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "philhealth_centers.json")
_cache = None


def _fold(text):
    """Lowercase, and with accents removed, so a search for 'Pinamalayan' also finds 'Pinamalayan' spelled with a
    stray accent in the source data, and vice versa - a search box should not care."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def load_directory():
    """{"source": "...", "centers": [...]}, cached after the first read - this file never changes while the app
    is running."""
    global _cache
    if _cache is None:
        with open(_PATH, encoding="utf-8") as handle:
            _cache = json.load(handle)
    return _cache


def regions():
    """Every region that has at least one facility, in the order the source file lists them (already the
    standard Philippine region order)."""
    seen = []
    for center in load_directory()["centers"]:
        if center["region"] not in seen:
            seen.append(center["region"])
    return seen


MAX_RESULTS = 50


def search(term=None, region=None, sector=None, limit=MAX_RESULTS):
    """
    Every facility matching ALL of the given filters (each one optional): term against the facility's name,
    province/city or municipality; region and sector as an exact match. No filters at all returns everything
    (still capped at `limit`) - the caller decides whether that is what a blank search box should do.
    Results are sorted by name. Returns (matches, total_before_limit) so the caller can say "showing 50 of 214".
    """
    centers = load_directory()["centers"]
    folded_term = _fold(term.strip()) if term and term.strip() else None
    matches = []
    for center in centers:
        if region and center["region"] != region:
            continue
        if sector and center["sector"] != sector:
            continue
        if folded_term and folded_term not in _fold(center["name"]) and folded_term not in _fold(center["province_or_city"]) \
                and folded_term not in _fold(center["municipality"]):
            continue
        matches.append(center)
    matches.sort(key=lambda c: c["name"])
    return matches[:limit], len(matches)
