"""
location_heatmap.py - the administrator's (LGU's) map of Pangasinan: how many people were screened in each
municipality/city or barangay, how many are at higher risk, and what share that is.

People counted: General Users who said where they live, and the patients professionals registered (a patient record
has its own location). Each person once, by their LATEST result. Only totals per place leave this module - never a
name or an id - and a place with fewer than MIN_CELL people screened shows no risk figure, so no one's result can
be picked out of a small barangay.

The outlines come from data/maps/pangasinan.json (PSGC boundaries as of 31 December 2023), drawn on the server as
SVG: no map service, no API key, no internet needed.
"""
import re

from services import ph_locations

MIN_CELL = 3
METRICS = {
    "screened": {"label": "People screened", "ramp": "count"},
    "high": {"label": "People at higher risk", "ramp": "risk"},
    "share": {"label": "Share at higher risk", "ramp": "risk"},
}
RAMPS = {   # validated sequential ramps (dataviz validator, ordinal mode: one hue, light to dark, light end >= 2:1)
    "count": ["#ABA4F2", "#8D84EC", "#6E64DF", "#5047C4", "#30298F"],
    "risk": ["#EC93A5", "#E06C86", "#CF4767", "#AF2A4C", "#7A1430"],
}
NONE_FILL = "#ECEEF5"          # nobody screened there yet
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def people(user_store, patient_records_store, assessment_store):
    """[{province, municipality, barangay, level or None}] - one entry per person, ids dropped after the join."""
    levels = assessment_store.latest_levels()
    rows = []
    for account in user_store.list_accounts():
        if account.get("role") != "general" or account.get("is_admin") or account.get("is_patient_record"):
            continue
        rows.append((account["user_id"], account.get("province_code"), account.get("municipality_code"), account.get("barangay_code")))
    rows += list(patient_records_store.locations())
    return [{"province": province, "municipality": town, "barangay": barangay, "level": levels.get(user_id)}
            for user_id, province, town, barangay in rows]


def _tally(entries):
    screened = [e for e in entries if e["level"]]
    high = sum(1 for e in screened if e["level"] == "high")
    shown = len(screened) >= MIN_CELL
    return {"registered": len(entries), "screened": len(screened), "high": high if shown else None,
            "share": round(high / len(screened) * 100) if shown and screened else None, "suppressed": 0 < len(screened) < MIN_CELL}


def _bins(metric, values):
    """Five legend bins: fixed 20-point steps for a share; even steps up to the largest count otherwise."""
    if metric == "share":
        return [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    top = max(values, default=0)
    if top <= 0:
        return []
    step = max(1, -(-top // 5))                             # ceil(top / 5)
    return [(1 + i * step if i else 1, (i + 1) * step + 1) for i in range(5)]


def _fill(metric, value, bins):
    if value is None:
        return None
    if metric != "share" and value == 0:
        return None
    for index, (low, high) in enumerate(bins):
        if low <= value < high:
            return RAMPS[METRICS[metric]["ramp"]][index]
    return RAMPS[METRICS[metric]["ramp"]][-1]


def _bbox(path):
    numbers = [float(n) for n in NUMBER.findall(path)]
    xs, ys = numbers[0::2], numbers[1::2]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def view(entries, metric="share", level="municipality", town=None):
    """Everything the map page draws. level: 'municipality' (whole province) or 'barangay' (every barangay, or one
    town's barangays when `town` is given)."""
    metric = metric if metric in METRICS else "share"
    level = level if level in ("municipality", "barangay") else "municipality"
    geo = ph_locations.map_data()
    towns = {m["code"]: m for m in ph_locations.municipalities()}
    if town not in towns:
        town = None
    in_pangasinan = [e for e in entries if e["province"] == ph_locations.PANGASINAN]

    if level == "municipality":
        shapes, key = geo["municipalities"], "municipality"
    else:
        shapes, key = [b for b in geo["barangays"] if town is None or b["town"] == town], "barangay"
    by_area = {}
    for e in in_pangasinan:
        by_area.setdefault(e[key], []).append(e)
    names = {s["code"]: s["name"] for s in shapes}
    areas = []
    for shape in shapes:
        tally = _tally(by_area.get(shape["code"], []))
        areas.append({**tally, "code": shape["code"], "name": shape["name"], "path": shape["path"], "cx": shape.get("cx"), "cy": shape.get("cy"),
                      "town": shape.get("town"), "town_name": towns[shape["town"]]["name"] if shape.get("town") in towns else None})
    if level == "barangay" and town is None:                # every barangay: list rows only where someone lives
        listed = [a for a in areas if a["registered"]]
    else:
        listed = areas
    bins = _bins(metric, [a[metric] for a in areas if isinstance(a[metric], (int, float))])
    for a in areas:
        a["fill"] = _fill(metric, a[metric], bins)
        a["state"] = "suppressed" if a["suppressed"] and metric != "screened" else ("value" if a["fill"] else "none")

    viewbox = (0, 0, geo["width"], geo["height"])
    if town:
        boxes = [_bbox(a["path"]) for a in areas if a["path"]]
        boxes = [b for b in boxes if b]
        if boxes:
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            pad = max(x1 - x0, y1 - y0) * 0.04
            viewbox = (round(x0 - pad, 1), round(y0 - pad, 1), round(x1 - x0 + 2 * pad, 1), round(y1 - y0 + 2 * pad, 1))
    legend = [{"fill": RAMPS[METRICS[metric]["ramp"]][i],
               "label": (f"{low}-{high - 1}%" if metric == "share" and high <= 100 else f"{low}-100%") if metric == "share"
               else (f"{low}" if high - 1 == low else f"{low}-{high - 1}")} for i, (low, high) in enumerate(bins)]
    totals = _tally(in_pangasinan)
    return {"metric": metric, "metric_label": METRICS[metric]["label"], "level": level, "town": town,
            "town_name": towns[town]["name"] if town else None, "areas": areas,
            "rows": sorted(listed, key=lambda a: (-(a[metric] if isinstance(a[metric], (int, float)) else -1), a["name"])),
            "legend": legend, "none_fill": NONE_FILL, "viewbox": viewbox, "min_cell": MIN_CELL,
            "town_outlines": geo["municipalities"] if level == "barangay" else [], "totals": totals,
            "no_outline": [a["name"] for a in areas if not a["path"]], "source": geo["source"],
            "towns": sorted(towns.values(), key=lambda t: t["name"]), "scale_unit": round(geo["width"] / 1000, 3),
            "label_size": round(viewbox[2] * (0.017 if town else 0.0098), 2) if (town or level == "municipality") else 0}


def other_provinces(entries):
    """People in the Philippines outside Pangasinan, by province: [{name, registered, screened, high, share}]."""
    groups = {}
    for e in entries:
        if e["province"] and e["province"] != ph_locations.PANGASINAN:
            groups.setdefault(e["province"], []).append(e)
    rows = [{"name": ph_locations.name_of(code) or code, **_tally(items)} for code, items in groups.items()]
    return sorted(rows, key=lambda r: (-r["screened"], r["name"]))
