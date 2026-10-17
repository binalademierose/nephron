"""
community_stats.py - what Nephron's own screenings show about people living in the Philippines: how many are at
higher risk, and how that compares between the genders people chose.

Built only from each person's LATEST result with three answers kept (assessment_store.latest_profiles(): level,
age, country, gender) - never a name, an id, a date or any other answer. These are Nephron's own counts, not a
national statistic, and every page that shows them says so.

Small groups are a privacy risk: if only one person chose a gender, a bar showing "1 person, 1 at higher risk" is
that person's result. So for anything shown to people other than the professional's own patients, a group with
fewer than MIN_GROUP people is folded into "Other answers", and if even that is too small it is left out and the
page says how many people are not shown. The whole picture waits until MIN_PEOPLE people have a result.
"""
PHILIPPINES = "Philippines"
MIN_GROUP = 3          # smallest group shown on its own (or folded together) on a shared/community view
MIN_PEOPLE = 5         # the community picture is shown once this many people in the Philippines have a result
OTHER_LABEL = "Other answers"


def gender_order(catalog):
    """[(value, label), ...] - the Gender answers in the order the form offers them."""
    sex = next((q for q in catalog["questions"] if q["name"] == "Sex"), {})
    spec = sex.get("asked_through") or {"options": sex.get("options", [])}
    return [(option["value"], option["label"]) for option in spec["options"]]


def in_philippines(profiles):
    return [profile for profile in profiles if profile.get("country") == PHILIPPINES]


def _pct(part, whole):
    return round(part / whole * 100) if whole else 0


def risk_summary(profiles, min_people=MIN_PEOPLE):
    """How many people (by their latest result) are at higher risk. `enough` is False below min_people."""
    people = len(profiles)
    high = sum(1 for profile in profiles if profile.get("level") == "high")
    return {"people": people, "high": high, "low": people - high, "high_percent": _pct(high, people),
            "enough": people >= min_people, "min_people": min_people}


def by_gender(profiles, catalog, min_group=MIN_GROUP):
    """A count plot: people and higher-risk people per Gender answer, in the form's own order.
    min_group=None shows every group as it is (a professional's own patients, whom they already know)."""
    counts = {}
    for profile in profiles:
        gender = profile.get("gender") or "Not recorded"
        people, high = counts.get(gender, (0, 0))
        counts[gender] = (people + 1, high + (profile.get("level") == "high"))

    labels = dict(gender_order(catalog))
    ordered = [value for value, _ in gender_order(catalog) if value in counts]
    ordered += sorted(value for value in counts if value not in labels)          # an answer no longer offered
    rows = [{"label": labels.get(value, value), "people": counts[value][0], "high": counts[value][1]} for value in ordered]

    hidden = 0
    if min_group:
        small = [row for row in rows if row["people"] < min_group]
        rows = [row for row in rows if row["people"] >= min_group]
        folded = {"label": OTHER_LABEL, "people": sum(r["people"] for r in small), "high": sum(r["high"] for r in small),
                  "folded": len(small)}
        if len(small) == 1 or folded["people"] < min_group:
            hidden = folded["people"]          # one small group alone, or too few together: still identifiable
        elif small:
            rows.append(folded)

    peak = max((row["people"] for row in rows), default=0)
    for row in rows:
        row["low"] = row["people"] - row["high"]
        row["high_percent"] = _pct(row["high"], row["people"])
        row["bar"] = _pct(row["people"], peak)                      # bar length, relative to the largest group
        row["high_bar"] = _pct(row["high"], peak)                   # the higher-risk part, on the same scale
    shown = sum(row["people"] for row in rows)
    most = max(rows, key=lambda row: (row["high_percent"], row["people"])) if any(row["high"] for row in rows) else None
    return {"rows": rows, "people": shown, "hidden": hidden, "highest_share": most["label"] if most else None,
            "min_group": min_group}


def philippines(profiles, catalog, min_people=MIN_PEOPLE, min_group=MIN_GROUP):
    """Everything the community cards show, for people living in the Philippines."""
    local = in_philippines(profiles)
    summary = risk_summary(local, min_people)
    return {"risk": summary, "gender": by_gender(local, catalog, min_group) if summary["enough"] else None,
            "everyone": len(profiles)}
