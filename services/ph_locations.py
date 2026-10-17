"""
ph_locations.py - where in the Philippines a person lives, for the administrator's (LGU's) heatmap.

Anyone living in the Philippines is asked their province. Anyone in Pangasinan is also asked their municipality or
city, and their barangay. Everything is saved as an official PSGC code (Philippine Standard Geographic Code), so it
lines up with an LGU's own records and with the map; barangay names repeat between towns, codes never do.

The lists come from data/ph_locations.json (built by scripts/build_ph_locations.py from the PSGC boundaries as of
31 December 2023). Nothing here is typed in by hand.
"""
import functools
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, "data", "ph_locations.json")
MAP_FILE = os.path.join(ROOT, "data", "maps", "pangasinan.json")
PHILIPPINES = "Philippines"
PANGASINAN = "105500000"
FIELDS = ("province_code", "municipality_code", "barangay_code")


@functools.lru_cache(maxsize=1)
def _data():
    with open(DATA_FILE, encoding="utf-8") as handle:
        return json.load(handle)


@functools.lru_cache(maxsize=1)
def map_data():
    with open(MAP_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def source():
    return _data()["source"]


def provinces():
    """[{code, name}], A to Z."""
    return _data()["provinces"]


def municipalities():
    """Pangasinan's municipalities and cities: [{code, name, kind}]."""
    return _data()["pangasinan"]["municipalities"]


def barangays(municipality_code):
    """The barangays of one Pangasinan municipality or city: [{code, name}] ([] for an unknown code)."""
    return _data()["pangasinan"]["barangays"].get(str(municipality_code or ""), [])


@functools.lru_cache(maxsize=1)
def _names():
    names = {p["code"]: p["name"] for p in provinces()}
    names.update({m["code"]: m["name"] for m in municipalities()})
    for town, rows in _data()["pangasinan"]["barangays"].items():
        names.update({b["code"]: b["name"] for b in rows})
    return names


def name_of(code):
    return _names().get(str(code)) if code else None


def describe(person):
    """'Caaringayan, Laoac, Pangasinan' (smallest place first), or None when no location is saved."""
    parts = [name_of(person.get(field)) for field in reversed(FIELDS)]
    parts = [part for part in parts if part]
    return ", ".join(parts) or None


def validate(country, form):
    """(values, errors) for the three location fields.
    Only someone living in the Philippines is asked; only someone in Pangasinan is asked the town and barangay.
    Anything not asked is saved as None, so a stale answer can never stay behind."""
    values, errors = dict.fromkeys(FIELDS), {}
    if country != PHILIPPINES:
        return values, errors

    def text(key):
        value = form.get(key)
        return value.strip() if isinstance(value, str) else ""

    province = text("province_code")
    if province not in {p["code"] for p in provinces()}:
        errors["province_code"] = "Choose the province where you live."
        return values, errors
    values["province_code"] = province
    if province != PANGASINAN:
        return values, errors
    town = text("municipality_code")
    if town not in {m["code"] for m in municipalities()}:
        errors["municipality_code"] = "Choose your municipality or city."
        return values, errors
    values["municipality_code"] = town
    barangay = text("barangay_code")
    if barangay not in {b["code"] for b in barangays(town)}:
        errors["barangay_code"] = "Choose your barangay."
        return values, errors
    values["barangay_code"] = barangay
    return values, errors
