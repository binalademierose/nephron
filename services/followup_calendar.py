"""
followup_calendar.py - the month-view calendar shared by the patient's own Follow-up page and the professional's
Follow-up section: which month to show (from ?year=&month=, falling back to this month), and the weeks of that
month with each day's appointments attached. Pure functions; nothing here reads or writes a store.
"""
import calendar as calendar_module
from datetime import date


def viewed_month(args, today):
    """(year, month) from request args, or today's month if they are missing or nonsensical."""
    try:
        year = int(args.get("year", today.year))
        month = int(args.get("month", today.month))
        date(year, month, 1)                                  # raises ValueError for anything nonsensical
    except (TypeError, ValueError):
        return today.year, today.month
    return year, month


def month_grid(year, month, appointments, today):
    """Weeks (Sunday first) for a plain month-view calendar. A day outside this month is None (a blank cell); each
    real day carries its date, whether it is today, and the appointments (already described, with scheduled_local)
    that fall on it."""
    by_day = {}
    for appt in appointments:
        by_day.setdefault(appt["scheduled_local"].date(), []).append(appt)
    weeks = []
    for week in calendar_module.Calendar(firstweekday=6).monthdayscalendar(year, month):
        days = []
        for day_number in week:
            if day_number == 0:
                days.append(None)
            else:
                this_date = date(year, month, day_number)
                days.append({"date": this_date, "day": day_number, "is_today": this_date == today,
                             "appointments": by_day.get(this_date, [])})
        weeks.append(days)
    return weeks


def neighbours(year, month):
    """((year, month) before, (year, month) after) for the Previous / Next links."""
    previous_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    return previous_month, next_month
