"""
visuals.py - turns assessment records into the numbers and shapes the pages draw.

WHY THIS FILE EXISTS
  The rule for Nephron's interface is: never draw a number that did not come from
  a real assessment. So every metric and every chart is calculated here, from a list
  of assessment records, and the templates only draw what this file returns.
  * An empty list gives an "empty" result, and the pages then show an empty state.
  * Later phases will load the records from MySQL and pass them to the same functions.

  There is no Flask and no database in this file, so it is easy to test and to read.

AN ASSESSMENT RECORD is a dictionary like this (probability is 0 to 100):
    {"date": date(2026, 9, 20), "type": "Preliminary screening",
     "probability": 31.0, "level": "high"}          # level is "low" or "high"
"""
import math
from datetime import date, timedelta

from services import eligibility

LEVELS = ("low", "high")
LEVEL_LABELS = {("preliminary", "low"): "Low Preliminary Risk", ("preliminary", "high"): "High Preliminary Risk",
               ("enhanced", "low"): "Low Enhanced Screening", ("enhanced", "high"): "High Enhanced Screening"}

# The four steps of "Your path to better kidney health", in order.
PATH_STEPS = ("Screening", "Analysis", "Results", "Follow-up")

# Chart sizes. The pages scale the SVGs, so these are only drawing units.
RING_BOX = 100
TREND_WIDTH, TREND_HEIGHT = 340, 196          # about the size the chart is shown at, so its text stays readable
TREND_MARGINS = (40, 18, 10, 28)              # left, right, top, bottom (room for the axis labels)
MIN_LABEL_GAP = 60   # drawing units between two date labels, so they never overlap


# ---------------------------------------------------------------- words and dates
def level_label(level, assessment_type="preliminary"):
    """('low', 'preliminary') -> 'Low Preliminary Risk'; ('high', 'enhanced') -> 'High Enhanced Screening'.
    The only place these words are spelled out."""
    return LEVEL_LABELS[(assessment_type, level)]


def percent_text(value):
    """31.0 -> '31', 55.3894 -> '55.4', 64.7029 -> '64.7'. One decimal at most, never a trailing zero."""
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_date(day):
    """date(2026, 9, 5) -> 'Sep 5, 2026' (no leading zero, works on every OS)."""
    return f"{day:%b} {day.day}, {day.year}"


def format_datetime(moment):
    """A local datetime (already converted - see services/clock.to_local_datetime) -> 'Sep 5, 2026, 3:45 PM'."""
    hour = moment.hour % 12 or 12
    return f"{format_date(moment)}, {hour}:{moment:%M %p}"


def short_date(day):
    """date(2026, 9, 5) -> 'Sep 5'."""
    return f"{day:%b} {day.day}"


def relative_day_text(day, today):
    """'Today', 'Yesterday' or '5 days ago'."""
    days = (today - day).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


def _check_record(record):
    """Refuse nonsense early, so a bad record can never turn into a confident-looking chart."""
    if record["level"] not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, not {record['level']!r}")
    if not 0 <= record["probability"] <= 100:
        raise ValueError(f"probability must be between 0 and 100, not {record['probability']!r}")
    threshold = record.get("threshold")
    if threshold is not None and not 0 <= threshold <= 100:
        raise ValueError(f"threshold must be between 0 and 100, not {threshold!r}")


# ---------------------------------------------------------------- the summary
def summarize_assessments(assessments, today=None, reassessment_days=None, follow_up_open=False):
    """
    Everything the dashboard needs, worked out from real records.

    reassessment_days is the waiting time between screenings. Nephron has not fixed this
    value yet, so when it is None the next screening is simply "available".
    follow_up_open: True when a professional currently authorized for this person has an open follow-up request
    for them (services/followups.py) - lets them screen again right away regardless of reassessment_days.
    """
    today = today or date.today()
    for record in assessments:
        _check_record(record)
    newest_first = sorted(assessments, key=lambda record: record["date"], reverse=True)

    total = len(newest_first)
    latest = newest_first[0] if newest_first else None
    previous = newest_first[1] if total > 1 else None
    high_count = sum(1 for record in newest_first if record["level"] == "high")
    month_count = sum(1 for record in newest_first if (record["date"].year, record["date"].month) == (today.year, today.month))

    # Next screening: available now unless a waiting time is set and has not passed yet (the rule lives in services/eligibility.py).
    next_screening = eligibility.wait_status(latest["date"] if latest is not None else None, today, reassessment_days, follow_up_open)

    # Change since the previous assessment, in neutral words (never "better" or "worse").
    change = None
    if previous is not None:
        points = round(latest["probability"] - previous["probability"], 1)
        change = {
            "points": abs(points),
            "direction": "higher" if points > 0 else "lower" if points < 0 else "same",
            "previous": previous,
        }

    return {
        "total": total,
        "latest": latest,
        "previous": previous,
        "low_count": total - high_count,
        "high_count": high_count,
        "month_count": month_count,
        "newest_first": newest_first,
        "oldest_first": list(reversed(newest_first)),
        "next_screening": next_screening,
        "change": change,
        # A chart is only drawn when there is enough real data to answer its question.
        "has_distribution": total >= 1,   # "How have my results been classified?"
        "has_trend": total >= 2,          # "How has my probability changed?" needs two points
    }


def summary_message(low_count, high_count):
    """One plain sentence under the classification donut. None when there is nothing to say. The donut counts
    Preliminary AND Enhanced results together, so this never names one type's label for all of them."""
    if low_count + high_count == 0:
        return None
    if low_count > high_count:
        return "Most of your results are in the lower-risk group."
    if high_count > low_count:
        return "Most of your results are in the higher-risk group."
    return "Your results are evenly split between the lower- and higher-risk groups."


def activity_items(newest_first, limit=3):
    """
    The 'Recent Activity' list. In this phase the only real events are completed assessments,
    so that is all it can contain: nothing is added to make the list look busier.
    """
    return [
        {"title": "Assessment completed", "level": record["level"], "type": record["type"], "date": record["date"],
         "assessment_id": record.get("assessment_id"), "assessment_type": record.get("assessment_type", "preliminary")}
        for record in newest_first[:limit]
    ]


def screening_path(total, follow_up_count=0):
    """
    How many of the four steps on 'Your path to better kidney health' are done:
        Screening -> Analysis -> Results -> Follow-up
    0 = nothing yet (Screening is the current step); 3 = screened, analysed and a result exists
    (Follow-up is the current step); 4 = a follow-up record exists too.
    """
    if total == 0:
        return 0
    return 4 if follow_up_count > 0 else 3


# ---------------------------------------------------------------- shapes
def ring_geometry(percent, radius=42, stroke=9, threshold=None):
    """
    A full ring that fills clockwise from the top. `threshold` (optional) adds a tick across the ring
    at the same position, so the model's cut-off can be seen on the ring itself.
    """
    percent = min(100.0, max(0.0, float(percent)))
    centre = RING_BOX / 2
    circumference = 2 * math.pi * radius
    length = circumference * percent / 100
    geometry = {
        "box": RING_BOX, "centre": centre, "radius": radius, "stroke": stroke,
        "circumference": round(circumference, 2),
        "value_length": round(length, 2),
        "dasharray": f"{length:.2f} {circumference:.2f}",
        "tick": None,
    }
    if threshold is not None:
        angle = math.radians(-90 + 360 * (threshold / 100))
        inner, outer = radius - stroke / 2 - 3, radius + stroke / 2 + 3
        geometry["tick"] = {
            "x1": round(centre + inner * math.cos(angle), 2), "y1": round(centre + inner * math.sin(angle), 2),
            "x2": round(centre + outer * math.cos(angle), 2), "y2": round(centre + outer * math.sin(angle), 2),
        }
    return geometry


def donut_geometry(low_count, high_count, radius=34, stroke=22, gap=2):
    """Segments for a donut of Low / High counts. Empty when there are no assessments."""
    total = low_count + high_count
    circumference = 2 * math.pi * radius
    segments, used = [], 0.0
    for key, label, count in (("low", LEVEL_LABELS[("preliminary", "low")], low_count), ("high", LEVEL_LABELS[("preliminary", "high")], high_count)):
        if count == 0:
            continue
        share = count / total
        length = max(0.0, circumference * share - (gap if low_count and high_count else 0))
        segments.append({
            "key": key, "label": label, "count": count,
            "dasharray": f"{length:.2f} {circumference - length:.2f}",
            "dashoffset": f"{-used:.2f}",
        })
        used += circumference * share
    return {"total": total, "radius": radius, "stroke": stroke, "gap": gap,
            "circumference": round(circumference, 2), "segments": segments}


def _smooth_path(points):
    """
    A smooth SVG path through (x, y) points using a monotone cubic curve.
    'Monotone' matters for a health chart: the curve can never swing above the highest value
    or below the lowest value between two points, so it never invents a peak.
    """
    n = len(points)
    if n == 1:
        return f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    dx = [points[i + 1][0] - points[i][0] for i in range(n - 1)]
    slope = [(points[i + 1][1] - points[i][1]) / dx[i] if dx[i] else 0.0 for i in range(n - 1)]
    tangent = [slope[0]] + [0.0 if slope[i - 1] * slope[i] <= 0 else (slope[i - 1] + slope[i]) / 2 for i in range(1, n - 1)] + [slope[-1]]
    for i in range(n - 1):                      # Fritsch-Carlson: keep each segment monotone
        if slope[i] == 0:
            tangent[i] = tangent[i + 1] = 0.0
            continue
        a, b = tangent[i] / slope[i], tangent[i + 1] / slope[i]
        size = a * a + b * b
        if size > 9:
            scale = 3 / math.sqrt(size)
            tangent[i], tangent[i + 1] = scale * a * slope[i], scale * b * slope[i]
    path = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(n - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        if dx[i] == 0:                          # two records on one day: a straight step, never a curve
            path += f" L{x1:.1f} {y1:.1f}"
            continue
        third = dx[i] / 3
        path += f" C{x0 + third:.1f} {y0 + tangent[i] * third:.1f} {x1 - third:.1f} {y1 - tangent[i + 1] * third:.1f} {x1:.1f} {y1:.1f}"
    return path


def _x_by_date(records, left, width):
    """x for each record, by real date (a long gap looks like a long gap)."""
    first, last = records[0]["date"], records[-1]["date"]
    span = (last - first).days
    return [left + width * (((r["date"] - first).days / span) if span else i / (len(records) - 1)) for i, r in enumerate(records)]


def trend_frame(width=TREND_WIDTH, height=TREND_HEIGHT):
    """The empty frame of the trend chart: the size, the 0-100 percent scale and the vertical guides. No data in it.
    width/height should be about the size the chart is SHOWN at - the SVG scales to its container, text included,
    so a chart drawn at 340 wide and shown at 650 wide has text twice the size of the page around it."""
    left, right, top, bottom = TREND_MARGINS
    plot_w, plot_h = width - left - right, height - top - bottom
    return {
        "width": width, "height": height,
        "left": left, "right": width - right, "top": top, "baseline": top + plot_h,
        "ticks": [{"value": v, "y": round(top + plot_h * (1 - v / 100), 1)} for v in (0, 25, 50, 75, 100)],
        "columns": [round(left + plot_w * i / 4, 1) for i in range(5)],
    }


def trend_geometry(points_oldest_first, threshold=None, width=TREND_WIDTH, height=TREND_HEIGHT):
    """
    Coordinates for a line chart of predicted risk probability over time.
    The vertical axis is always 0 to 100 percent, so a small probability looks small.
    `threshold` (percent) is optional; without it there is simply no threshold height.
    Returns None when there are fewer than two points: one point is not a trend.
    """
    if len(points_oldest_first) < 2:
        return None
    frame = trend_frame(width, height)
    left, top, baseline = frame["left"], frame["top"], frame["baseline"]
    plot_w, plot_h = frame["right"] - left, baseline - top

    def y_for(value):
        return top + plot_h * (1 - value / 100)

    xs = _x_by_date(points_oldest_first, left, plot_w)
    points = []
    for x, record in zip(xs, points_oldest_first):
        points.append({
            "x": round(x, 1), "y": round(y_for(record["probability"]), 1),
            "date_full": format_date(record["date"]), "date_short": short_date(record["date"]),
            "probability": record["probability"], "level": record["level"], "assessment_type": record.get("assessment_type", "preliminary"),
        })
    # The first and last dates are always labelled. A middle date is labelled only if there is room on both sides.
    shown = [0]
    for index in range(1, len(points) - 1):
        if points[index]["x"] - points[shown[-1]]["x"] >= MIN_LABEL_GAP and points[-1]["x"] - points[index]["x"] >= MIN_LABEL_GAP:
            shown.append(index)
    shown.append(len(points) - 1)
    for index, point in enumerate(points):
        point["show_label"] = index in shown
    line = _smooth_path([(p["x"], p["y"]) for p in points])
    area = f"{line} L{points[-1]['x']} {baseline} L{points[0]['x']} {baseline} Z"
    return dict(frame, points=points, line=line, area=area, threshold_y=None if threshold is None else round(y_for(threshold), 1))


def sparkline_geometry(points_oldest_first, width=132, height=52, pad=6):
    """A tiny trend line for the 'Total Assessments' card. Real probabilities only; None below two points."""
    if len(points_oldest_first) < 2:
        return None
    values = [r["probability"] for r in points_oldest_first]
    low, high = min(values), max(values)
    xs = _x_by_date(points_oldest_first, pad, width - 2 * pad)
    inner_h = height - 2 * pad
    ys = [pad + inner_h * (1 - ((v - low) / (high - low) if high > low else 0.5)) for v in values]
    line = _smooth_path(list(zip(xs, ys)))
    return {"width": width, "height": height, "line": line,
            "area": f"{line} L{xs[-1]:.1f} {height} L{xs[0]:.1f} {height} Z",
            "last": {"x": round(xs[-1], 1), "y": round(ys[-1], 1)}}
