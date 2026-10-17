"""
professional_overview.py - everything the Professional Dashboard needs, gathered from what already exists
elsewhere: a professional's own patient records (services/patient_records.py), the patients who have shared
their history with them (services/authorizations.py), their assessments, clinical reviews, and follow-up
appointments. Nothing here is stored - it is worked out fresh, from those, every time the dashboard loads.

Two different kinds of patient sit behind one dashboard, and the difference matters for two of the stats:
  - a patient record's assessment was performed BY this professional - there is nothing to "review"
  - a shared assessment was performed by the person themselves, and needs the professional's own clinical review
"Pending reviews" and "review status" only ever apply to the second kind. A patient record's own assessment is
described as "Self-recorded", never as pending anything.
"""
from datetime import timedelta

from services import assessments, authorizations, clinical_reviews, clock, community_stats, followup_appointments


def patient_pool(patient_records_store, auth_store, user_store, professional_user_id):
    """Every patient this professional works with, either kind, as one list: {user_id, display_name, patient_code
    (None for a shared patient - only a patient record has one), source ('record' or 'shared'), age, sex (both
    None for a shared patient - a General User's account carries no such field of its own; see patient_insights()
    for how their most recent assessment's own answers fill this in instead, only where it is actually needed)."""
    pool = []
    for record in patient_records_store.list_for_professional(professional_user_id):
        pool.append({"user_id": record["user_id"], "display_name": record["full_name"], "patient_code": record["patient_code"],
                    "source": "record", "age": record["age"], "sex": record["sex"],
                    "gender": record.get("gender"), "country": record.get("country")})
    for row in auth_store.list_for_professional(professional_user_id, statuses=["accepted"]):
        patient = user_store.find_by_id(row["patient_user_id"])
        if patient is None:
            continue
        pool.append({"user_id": patient["user_id"], "display_name": patient["full_name"], "patient_code": None,
                    "source": "shared", "age": None, "sex": None, "gender": None, "country": None})
    return pool


CATEGORY_ALL, CATEGORY_PENDING, CATEGORY_REVIEWED, CATEGORY_FOLLOW_UP = "all", "pending", "reviewed", "follow_up"


def patient_list(patient_records_store, auth_store, user_store, assessment_store, review_store, followup_store,
                 professional_user_id, timezone_name, term=None, risk=None, category=CATEGORY_ALL):
    """The professional's own Patients page: every patient they work with, each carrying their own assessment
    count, latest result, and status - then narrowed by a name/code search, a risk filter ("low"/"high"), and a
    category:
      - pending: a patient record with no assessment yet (needs a first screening), or a shared patient whose
        latest assessment is still awaiting the professional's own clinical review
      - reviewed: has at least one assessment, and is not "pending" by the rule above
      - follow_up: has at least one currently scheduled follow-up appointment
    Category and risk narrow the SAME list search() and dashboard() already scope to this professional - a
    patient belonging to someone else is never in the pool to begin with."""
    pool = patient_pool(patient_records_store, auth_store, user_store, professional_user_id)

    scheduled_patient_ids = {appt["patient_user_id"] for appt in followup_store.list_for_professional(professional_user_id)
                             if appt["status"] == "scheduled"}

    described = []
    for patient in pool:
        rows = assessment_store.list_assessments(patient["user_id"])
        latest = assessments.to_record(rows[0], timezone_name) if rows else None
        is_pending = latest is None
        if latest is not None and patient["source"] == "shared":
            review_rows = clinical_reviews.for_assessment(review_store, latest["assessment_id"])
            is_pending = not review_rows
        described.append({**patient, "assessment_count": len(rows), "latest": latest,
                          "is_pending": is_pending, "has_follow_up": patient["user_id"] in scheduled_patient_ids})

    term = (term or "").strip().lower()
    if term:
        described = [row for row in described if term in row["display_name"].lower()
                    or (row["patient_code"] and term in row["patient_code"].lower())]
    if risk in ("low", "high"):
        described = [row for row in described if row["latest"] and row["latest"]["level"] == risk]
    if category == CATEGORY_PENDING:
        described = [row for row in described if row["is_pending"]]
    elif category == CATEGORY_REVIEWED:
        described = [row for row in described if not row["is_pending"] and row["latest"] is not None]
    elif category == CATEGORY_FOLLOW_UP:
        described = [row for row in described if row["has_follow_up"]]

    # Newest result first; a patient with no assessment yet sorts to the end, regardless of name.
    described.sort(key=lambda row: (row["latest"] is None, -row["latest"]["date"].toordinal() if row["latest"] else 0))
    return described


PERIOD_1_DAY, PERIOD_7_DAYS, PERIOD_30_DAYS, PERIOD_ALL = "1_day", "7_days", "30_days", "all"
_PERIOD_DAYS = {PERIOD_1_DAY: 1, PERIOD_7_DAYS: 7, PERIOD_30_DAYS: 30}


DATE_TODAY, DATE_THIS_WEEK, DATE_THIS_MONTH, DATE_ALL = "today", "this_week", "this_month", "all"


def _matches_date_period(day, today, period):
    if period == DATE_TODAY:
        return day == today
    if period == DATE_THIS_WEEK:
        start_of_week = today - timedelta(days=today.weekday())          # Monday
        return start_of_week <= day <= today
    if period == DATE_THIS_MONTH:
        return day.year == today.year and day.month == today.month
    return True


def shared_assessment_list(auth_store, user_store, assessment_store, review_store, professional_user_id, timezone_name,
                           term=None, risk=None, review_status=None, date_period=DATE_ALL):
    """Assessments belonging to this professional's ACCEPTED shared patients only - never a patient record, which
    has no "review" of this kind to begin with (see the module note above). Patient, assessment date/type/risk,
    and review status - narrowed by a name/patient-id search, risk, review status, and a calendar date period
    (today/this week/this month, not a rolling window - this list reads by calendar period on purpose, matching
    how a professional would ask "what came in this week")."""
    accepted = authorizations.describe_for_professional(auth_store, user_store, professional_user_id, statuses={"accepted"})
    rows = []
    for patient in accepted:
        for record in assessments.load_records(assessment_store, patient["patient_user_id"], timezone_name):
            rows.append({**record, "patient_user_id": patient["patient_user_id"], "patient_name": patient["patient_name"]})

    reviews_by_assessment = clinical_reviews.for_assessments(review_store, [row["assessment_id"] for row in rows])
    for row in rows:
        row["review_status"] = "reviewed" if reviews_by_assessment.get(row["assessment_id"]) else "awaiting_review"

    term = (term or "").strip().lower()
    if term:
        rows = [row for row in rows if term in row["patient_name"].lower() or term == str(row["assessment_id"])]
    if risk in ("low", "high"):
        rows = [row for row in rows if row["level"] == risk]
    if review_status in ("reviewed", "awaiting_review"):
        rows = [row for row in rows if row["review_status"] == review_status]
    if date_period in (DATE_TODAY, DATE_THIS_WEEK, DATE_THIS_MONTH):
        today = clock.local_today(timezone_name)
        rows = [row for row in rows if _matches_date_period(row["date"], today, date_period)]

    rows.sort(key=lambda row: (row["date"], row["assessment_id"]), reverse=True)
    return rows


def assessment_list(patient_records_store, auth_store, user_store, assessment_store, review_store,
                    professional_user_id, timezone_name, term=None, risk=None, period=PERIOD_ALL):
    """Every assessment across every patient this professional works with - Assessment ID, patient, date, mode,
    risk, and review status - narrowed by a time period, a search term (patient name, patient code, or a numeric
    assessment id), and a risk filter. The same "review status" rule as patient_list() and dashboard(): a patient
    record's own assessment is "self_recorded", never pending; only a shared patient's own assessment is ever
    "awaiting_review" or "reviewed"."""
    pool = patient_pool(patient_records_store, auth_store, user_store, professional_user_id)
    rows = []
    for patient in pool:
        for record in assessments.load_records(assessment_store, patient["user_id"], timezone_name):
            rows.append({**record, "patient": patient})

    shared_ids = [row["assessment_id"] for row in rows if row["patient"]["source"] == "shared"]
    reviews_by_assessment = clinical_reviews.for_assessments(review_store, shared_ids)
    for row in rows:
        if row["patient"]["source"] == "record":
            row["review_status"] = "self_recorded"
        else:
            row["review_status"] = "reviewed" if reviews_by_assessment.get(row["assessment_id"]) else "awaiting_review"

    term = (term or "").strip().lower()
    if term:
        rows = [row for row in rows if term in row["patient"]["display_name"].lower()
               or (row["patient"]["patient_code"] and term in row["patient"]["patient_code"].lower())
               or term == str(row["assessment_id"])]
    if risk in ("low", "high"):
        rows = [row for row in rows if row["level"] == risk]
    if period in _PERIOD_DAYS:
        cutoff = clock.local_today(timezone_name) - timedelta(days=_PERIOD_DAYS[period])
        rows = [row for row in rows if row["date"] >= cutoff]

    rows.sort(key=lambda row: (row["date"], row["assessment_id"]), reverse=True)
    return rows


FOLLOW_UP_PENDING, FOLLOW_UP_DUE, FOLLOW_UP_COMPLETED, FOLLOW_UP_CANCELLED = "pending", "due", "completed", "cancelled"


def _follow_up_status(appointment, now_utc):
    if appointment["status"] == "completed":
        return FOLLOW_UP_COMPLETED
    if appointment["status"] == "cancelled":
        return FOLLOW_UP_CANCELLED
    return FOLLOW_UP_DUE if appointment["scheduled_at"] <= now_utc else FOLLOW_UP_PENDING


def follow_up_list(patient_records_store, auth_store, user_store, followup_store, professional_user_id, timezone_name,
                   now_utc, term=None, status=None, date_period=DATE_ALL):
    """Every follow-up appointment this professional has scheduled, across every patient - Pending (in the
    future), Due (its own date has arrived and it is not yet completed), Completed, or Cancelled - narrowed by a
    name/patient-code search, a status, and a calendar date period matching its OWN scheduled date."""
    pool = patient_pool(patient_records_store, auth_store, user_store, professional_user_id)
    by_user_id = {patient["user_id"]: patient for patient in pool}

    rows = []
    for appointment in followup_appointments.for_professional(followup_store, professional_user_id, timezone_name):
        patient = by_user_id.get(appointment["patient_user_id"])
        if patient is None:                    # the patient record or the sharing itself is gone - nothing to show
            continue
        rows.append({**appointment, "patient": patient, "follow_up_status": _follow_up_status(appointment, now_utc)})

    term = (term or "").strip().lower()
    if term:
        rows = [row for row in rows if term in row["patient"]["display_name"].lower()
               or (row["patient"]["patient_code"] and term in row["patient"]["patient_code"].lower())]
    if status in (FOLLOW_UP_PENDING, FOLLOW_UP_DUE, FOLLOW_UP_COMPLETED, FOLLOW_UP_CANCELLED):
        rows = [row for row in rows if row["follow_up_status"] == status]
    if date_period in (DATE_TODAY, DATE_THIS_WEEK, DATE_THIS_MONTH):
        today = clock.local_today(timezone_name)
        rows = [row for row in rows if _matches_date_period(row["scheduled_local"].date(), today, date_period)]

    rows.sort(key=lambda row: row["scheduled_at"])
    return rows


AGE_BUCKETS = (("18-44", 18, 44), ("45-64", 45, 64), ("65+", 65, 130))


def _latest_inputs(assessment_store, user_id):
    rows = assessment_store.list_assessments(user_id)
    if not rows:
        return {}
    latest = assessment_store.get_assessment(user_id, rows[0]["assessment_id"])
    return (latest or {}).get("inputs") or {}


def _patient_profile(assessment_store, patient):
    """{age, sex, gender, country} for one pool entry. A patient record has its own age, sex, country (and gender,
    when it was made after Gender was asked); anything it lacks - and everything for a shared patient, whose account
    has no such fields - comes from the answers saved with their own most recent assessment."""
    profile = {key: patient.get(key) for key in ("age", "sex", "gender", "country")}
    if any(value is None for value in profile.values()):
        saved = _latest_inputs(assessment_store, patient["user_id"])
        for key, name in (("age", "Age"), ("sex", "Sex"), ("gender", "Gender"), ("country", "Country")):
            if profile[key] is None:
                profile[key] = saved.get(name)
    profile["gender"] = profile["gender"] or profile["sex"]           # saved before Gender was asked: Male/Female
    return profile


def _patient_age_sex(assessment_store, patient):
    """(age, sex) for one pool entry - kept for callers that need only those two."""
    profile = _patient_profile(assessment_store, patient)
    return profile["age"], profile["sex"]


def _age_bucket(age):
    for label, low, high in AGE_BUCKETS:
        if low <= age <= high:
            return label
    return None


def patient_insights(patient_records_store, auth_store, user_store, assessment_store, professional_user_id, timezone_name,
                     catalog=None):
    """Real, aggregate demographics and risk across THIS professional's own patients - never a population
    statistic, and always labelled as such (the templates that use this say "your patients", never "US adults").
    Returns None if there are fewer than 3 patients with a known risk result: with that little data, a
    distribution would be more misleading than informative - an honest empty state is shown instead.
    Besides overall risk and age: how many of their patients living in the Philippines are at higher risk, and a
    count plot by the gender each patient chose (their own patients, so every group is shown as it is)."""
    if catalog is None:
        from services import screening_contract
        catalog = screening_contract.load_catalog()
    pool = patient_pool(patient_records_store, auth_store, user_store, professional_user_id)

    high = 0
    age_counts = {label: 0 for label, _, _ in AGE_BUCKETS}
    with_result = 0
    profiles = []          # one per patient WITH a result: {level, gender, country} - what the gender and Philippines views use

    for patient in pool:
        rows = assessments.load_records(assessment_store, patient["user_id"], timezone_name)
        latest = rows[0] if rows else None
        profile = _patient_profile(assessment_store, patient)

        if latest is not None:
            with_result += 1
            high += latest["level"] == "high"
            profiles.append({"level": latest["level"], "gender": profile["gender"], "country": profile["country"]})

        if profile["age"] is not None:
            bucket = _age_bucket(profile["age"])
            if bucket:
                age_counts[bucket] += 1

    if with_result < 3:
        return None

    def pct(part, whole):
        return round(part / whole * 100) if whole else 0

    high_percent = pct(high, with_result)
    yours = "Your own patient records, not a general population statistic."

    risk = {
        "eyebrow": "Who is at risk, among your patients", "value": f"{high_percent}%", "ring_percent": high_percent,
        "short_caption": "of your patients are at higher risk",
        "detail": f"{high} of {with_result} patients with a result are at higher risk by their latest result.",
        "source_label": yours,
    }
    age = {
        "eyebrow": "Your patients, by age", "source_label": yours,
        "groups": [{"label": g["label"], "percent": g["percent"]} for g in
                  [{"label": label, "percent": pct(age_counts[label], with_result)} for label, _, _ in AGE_BUCKETS]],
        "detail": "The share of your patients with a known age falling in each age group.",
    }
    philippines = community_stats.risk_summary(community_stats.in_philippines(profiles), min_people=1)
    gender = community_stats.by_gender(profiles, catalog, min_group=None)
    return {"total_with_result": with_result, "risk": risk, "age": age, "philippines": philippines, "gender": gender,
            "source_label": yours}


def search(patient_records_store, auth_store, user_store, assessment_store, professional_user_id, term, timezone_name):
    """This professional's own patients and assessments, matched by patient name, patient code, or a numeric
    assessment id. Returns {"patients": [...], "assessments": [...]}, both already scoped to this professional -
    a name, code, or id belonging to someone else's patient never comes back, exactly as if it did not exist.
    Each assessment also carries its own "patient" (the same shape patient_pool gives every patient), so the
    template can build the right link (a patient record's own Risk Analysis page, or a shared patient's history
    page - the two kinds of patient still do not share one result page)."""
    term = (term or "").strip()
    if not term:
        return {"patients": [], "assessments": []}
    pool = patient_pool(patient_records_store, auth_store, user_store, professional_user_id)
    lower = term.lower()
    matching_patients = [patient for patient in pool if lower in patient["display_name"].lower()
                         or (patient["patient_code"] and lower in patient["patient_code"].lower())]

    found, seen_ids = [], set()
    if term.isdigit():
        owner_user_id = assessment_store.find_owner(int(term))
        owner_patient = next((patient for patient in pool if patient["user_id"] == owner_user_id), None) if owner_user_id else None
        if owner_patient is not None:
            row = assessment_store.get_assessment(owner_user_id, int(term))
            if row is not None:
                found.append({**assessments.to_record(row, timezone_name), "patient": owner_patient})
                seen_ids.add(row["assessment_id"])

    for patient in matching_patients:
        for record in assessments.load_records(assessment_store, patient["user_id"], timezone_name):
            if record["assessment_id"] not in seen_ids:
                found.append({**record, "patient": patient})
                seen_ids.add(record["assessment_id"])

    found.sort(key=lambda row: (row["date"], row["assessment_id"]), reverse=True)
    return {"patients": matching_patients, "assessments": found}


def dashboard(patient_records_store, auth_store, user_store, assessment_store, review_store, followup_store,
             professional_user_id, timezone_name, recent_limit=8):
    """Everything templates/account/professional_home.html shows, worked out fresh."""
    pool = patient_pool(patient_records_store, auth_store, user_store, professional_user_id)
    by_user_id = {patient["user_id"]: patient for patient in pool}

    all_rows = []            # every assessment across every patient, each tagged with its own patient's info
    latest_by_patient = {}   # user_id -> that patient's own latest assessment record (for the risk counts)
    for patient in pool:
        records = assessments.load_records(assessment_store, patient["user_id"], timezone_name)
        if records:
            latest_by_patient[patient["user_id"]] = records[0]
        for record in records:
            all_rows.append({**record, "patient": patient})

    low_risk = sum(1 for record in latest_by_patient.values() if record["level"] == "low")
    high_risk = sum(1 for record in latest_by_patient.values() if record["level"] == "high")

    all_rows.sort(key=lambda row: (row["date"], row["assessment_id"]), reverse=True)
    recent = all_rows[:recent_limit]

    # Review status only means anything for a shared patient's own assessment - see the module note above.
    shared_assessment_ids = [row["assessment_id"] for row in all_rows if row["patient"]["source"] == "shared"]
    reviews_by_assessment = clinical_reviews.for_assessments(review_store, shared_assessment_ids)
    for row in recent:
        if row["patient"]["source"] == "record":
            row["review_status"] = "self_recorded"
        else:
            row["review_status"] = "reviewed" if reviews_by_assessment.get(row["assessment_id"]) else "awaiting_review"
    pending_review_count = sum(1 for aid in shared_assessment_ids if not reviews_by_assessment.get(aid))

    appointments = followup_store.list_for_professional(professional_user_id)
    follow_up_count = sum(1 for appt in appointments if appt["status"] == "scheduled")

    return {
        "total_patients": len(pool),
        "recent_assessment_count": len(all_rows),
        "low_risk_count": low_risk,
        "high_risk_count": high_risk,
        "follow_up_count": follow_up_count,
        "pending_review_count": pending_review_count,
        "recent_assessments": recent,
        "has_any_patients": bool(pool),
    }
