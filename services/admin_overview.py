"""
admin_overview.py - what the administrator side shows: account counts, professionals awaiting a licence check, and
system-wide assessment COUNTS. By design it never returns anyone's health information - no answers, probabilities
or results of a named person - only accounts (who can sign in) and totals (how much the system is used).
"""
from datetime import timedelta

ROLES = ("general", "professional", "admin")
STATUSES = ("active", "inactive")
VERIFICATION = ("pending", "verified", "rejected")


def role_of(account):
    return "admin" if account.get("is_admin") else account["role"]


def account_counts(accounts):
    counts = {"total": len(accounts), "active": 0, "inactive": 0, "pending_professionals": 0}
    counts.update({role: 0 for role in ROLES})
    for account in accounts:
        counts[role_of(account)] += 1
        counts["active" if account.get("is_active", True) else "inactive"] += 1
        if role_of(account) == "professional" and account.get("verification_status", "pending") == "pending":
            counts["pending_professionals"] += 1
    return counts


def assessment_counts(assessment_store, now, days=30):
    rows = assessment_store.totals(now - timedelta(days=days))
    summary = {"total": 0, "recent": 0, "days": days, "preliminary": 0, "enhanced": 0, "low": 0, "high": 0}
    for kind, level, total, recent in rows:
        summary["total"] += total
        summary["recent"] += recent
        summary[kind] = summary.get(kind, 0) + total
        summary[level] = summary.get(level, 0) + total
    return summary


def filter_accounts(accounts, term=None, role=None, status=None):
    term = (term or "").strip().lower()
    rows = accounts
    if term:
        rows = [a for a in rows if term in a["full_name"].lower() or term in a["email"].lower() or term in (a.get("username") or "").lower()]
    if role in ROLES:
        rows = [a for a in rows if role_of(a) == role]
    if status in STATUSES:
        rows = [a for a in rows if bool(a.get("is_active", True)) == (status == "active")]
    return rows


def professionals(accounts, status=None):
    rows = [a for a in accounts if role_of(a) == "professional"]
    if status in VERIFICATION:
        rows = [a for a in rows if a.get("verification_status", "pending") == status]
    return rows


AGE_GROUPS = (("Under 18", 0, 17), ("18-44", 18, 44), ("45-64", 45, 64), ("65+", 65, 200))


def user_kpis(accounts, now, days=30):
    """How many people use Nephron: everyone with an account, those who signed in recently, and this month's new ones."""
    since = now - timedelta(days=days)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    people = [a for a in accounts if not a.get("is_admin")]
    return {
        "users": len(people),
        "active_recently": sum(1 for a in people if a.get("last_login_at") and a["last_login_at"] >= since),
        "new_this_month": sum(1 for a in people if a["created_at"] >= month_start),
        "verified_professionals": sum(1 for a in people if a["role"] == "professional" and a.get("verification_status") == "verified"),
        "days": days,
    }


def risk_by_age(latest_results):
    """People screened, how many are higher risk by their LATEST result, and how that splits by age group.
    Built from (classification, age) pairs only - no person is identifiable from it."""
    groups = [{"label": label, "people": 0, "high": 0} for label, _, _ in AGE_GROUPS]
    unknown = {"label": "Age not recorded", "people": 0, "high": 0}
    high_total = 0
    for level, age in latest_results:
        is_high = level == "high"
        high_total += is_high
        target = unknown
        if age is not None:
            for group, (_, low, high) in zip(groups, AGE_GROUPS):
                if low <= age <= high:
                    target = group
                    break
        target["people"] += 1
        target["high"] += is_high
    rows = [g for g in groups] + ([unknown] if unknown["people"] else [])
    peak = max((g["high"] for g in rows), default=0)
    for g in rows:
        g["high_percent"] = round(g["high"] / g["people"] * 100) if g["people"] else 0
        g["bar"] = round(g["high"] / peak * 100) if peak else 0          # bar length, relative to the largest group
    people = len(latest_results)
    return {"people": people, "high": high_total, "high_percent": round(high_total / people * 100) if people else 0,
            "groups": rows, "most_high": max(rows, key=lambda g: g["high"])["label"] if high_total else None}
