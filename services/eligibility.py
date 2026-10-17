"""
eligibility.py - the ONE place that decides whether a person may start a new screening.

The rule has three states:
  unavailable  there is no verified model, so nothing can be analysed (services/model_service.py)
  waiting      REASSESSMENT_DAYS is set and that many days have not yet passed since the person's last assessment
  available    anything else (including a person who has never been screened)

The waiting period is set by the ADMINISTRATOR (Re-assessment rule page, services/reassessment.py): a number of calendar
months, 3 by default (migration 023). Only if no administrator setting exists does REASSESSMENT_DAYS from .env apply
(a number of days; empty = no waiting period). The dashboard, the screening page and the history page all call the
functions below, so they can never disagree; and the screening page enforces the rule on the server, not only by
hiding a button.
Days are counted in the person's own time zone (see services/clock.py).

An OPEN follow-up request (services/followups.py) lets them screen again right away, however much of the waiting
period is left. It comes from a professional currently authorized for this person, or from the administrator approving
the person's own request (services/reassessment.py). It is used up by the next saved screening, so after that the
normal waiting period applies again. Pass follow_up_open=True for this; the functions
never look it up themselves, so the caller decides where that fact comes from.
"""
import calendar
from datetime import timedelta


class Period:
    """A waiting period: whole calendar months (the administrator's setting) or days (.env REASSESSMENT_DAYS)."""

    def __init__(self, months=None, days=None):
        if bool(months) == bool(days):
            raise ValueError("A waiting period is either months or days, and more than zero.")
        self.months, self.days = months, days

    def opens_on(self, last_date):
        if self.days:
            return last_date + timedelta(days=self.days)
        month_index = last_date.month - 1 + self.months
        year, month = last_date.year + month_index // 12, month_index % 12 + 1
        return last_date.replace(year=year, month=month, day=min(last_date.day, calendar.monthrange(year, month)[1]))

    @property
    def label(self):
        if self.months:
            return f"{self.months} month{'' if self.months == 1 else 's'}"
        return f"{self.days} day{'' if self.days == 1 else 's'}"

    def __eq__(self, other):
        return isinstance(other, Period) and (self.months, self.days) == (other.months, other.days)

    def __repr__(self):
        return f"Period(months={self.months}, days={self.days})"


def as_period(value):
    """None, a whole number of days (the old .env setting), or a Period."""
    if not value:
        return None
    return value if isinstance(value, Period) else Period(days=value)


def wait_status(last_date, today, reassessment_days, follow_up_open=False):
    """
    The waiting period alone: {"state": "available" | "waiting", "date": the day screening opens (or None),
    "days_left": whole days still to wait, "elapsed_share": how much of the waiting time has passed, 0 to 1 (or None)}.
    reassessment_days: a Period, a whole number of days, or None (no waiting period).
    """
    period = as_period(reassessment_days)
    if last_date is None or period is None or follow_up_open:
        return {"state": "available", "date": None, "days_left": 0, "elapsed_share": None}
    opens_on = period.opens_on(last_date)
    days_left = max(0, (opens_on - today).days)
    length = max(1, (opens_on - last_date).days)
    elapsed = min(1.0, max(0.0, (today - last_date).days / length))
    return {"state": "waiting" if days_left > 0 else "available", "date": opens_on, "days_left": days_left, "elapsed_share": elapsed}


def screening_status(last_date, today, reassessment_days, model_ready, follow_up_open=False):
    """Same shape as wait_status(), but "unavailable" comes first: with no verified model nobody can screen, whatever the dates (or a follow-up request) say."""
    status = wait_status(last_date, today, reassessment_days, follow_up_open)
    if not model_ready:
        status = dict(status, state="unavailable")
    return status
