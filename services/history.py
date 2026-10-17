"""
history.py - the rules behind the history page and the comparison of two assessments. No Flask and no database.

Everything here is worked out from a person's OWN saved assessments (the routes only ever ask the store for that user's rows).
Nothing is invented: a comparison of answers is only made when both assessments saved their answers.
Words stay neutral. A result that is "higher" or "lower" is not "better" or "worse", and a difference can come from different
answers, from a different version of the model, or from both.
"""
import math

from services import assessments, screening_contract

PER_PAGE = 10


def paginate(items, page, per_page=PER_PAGE):
    """One page of a list. A page number that is too low or too high is moved to the nearest real page."""
    total = len(items)
    pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    return {
        "items": items[start:start + per_page], "page": page, "pages": pages, "total": total,
        "has_previous": page > 1, "has_next": page < pages,
        "first_number": start + 1 if total else 0, "last_number": min(start + per_page, total),
    }


def _model_note(earlier, later):
    """Are the two results from the same version of the model? Only then are the probabilities like for like."""
    a, b = earlier["model_version"], later["model_version"]
    if not a or not b:
        return "unknown"
    return "same" if a == b else "different"


def compare(catalog, first_row, second_row, timezone_name):
    """
    Compare two of one person's assessments (rows from the assessment store, with their saved answers).
    The older one is always called "earlier", whichever order they were given in.
    """
    earlier_row, later_row = sorted([first_row, second_row], key=lambda row: (row["assessed_at"], row["assessment_id"]))
    earlier, later = assessments.to_record(earlier_row, timezone_name), assessments.to_record(later_row, timezone_name)
    points = round(later["probability"] - earlier["probability"], 1)

    before, after = earlier_row["inputs"], later_row["inputs"]
    changes, unchanged = [], 0
    if before and after:
        for question in catalog["questions"]:
            name = question["name"]
            if question["kind"] == "derived" or name not in before or name not in after:
                continue                                    # Obesity follows the BMI; only real answers are compared
            if before[name] == after[name]:
                unchanged += 1
            else:
                changes.append({"label": question["short"], "earlier": screening_contract.answer_text(question, before),
                                "later": screening_contract.answer_text(question, after)})
    return {
        "earlier": earlier, "later": later,
        "points": abs(points), "direction": "higher" if points > 0 else "lower" if points < 0 else "same",
        "level_changed": earlier["level"] != later["level"],
        "model": _model_note(earlier_row, later_row),
        "same_threshold": earlier["threshold"] == later["threshold"],
        "answers_available": bool(before and after),
        "changes": changes, "unchanged": unchanged,
    }
