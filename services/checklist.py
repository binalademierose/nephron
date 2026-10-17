"""
checklist.py - turns a person's own current kidney-health tips (services/kidney_tips.py, matched from their
latest assessment) into a checklist: the same grouped tips, each now also carrying whether THIS person has
marked it done (services/checklist_store.py).

A checklist item only ever comes from a real, currently-matching tip - marking one complete never invents a
task, and a tip that no longer applies (because a newer assessment changed the picture) simply stops appearing,
taking its old completion record out of view with it (though the row itself is left alone in storage, in case
the same tip becomes relevant again later).
"""
from services import kidney_tips


def for_user(checklist_store, latest_inputs, latest_classification, user_id, day=None):
    """
    latest_inputs/latest_classification: the SAME two things services/kidney_tips.personalized_tips() itself
    takes - the caller already has these on hand (it just loaded the person's latest assessment to show
    something else), so this never reloads anything on its own.
    Returns the same grouped shape kidney_tips.personalized_tips() does, plus each tip's own "is_complete" and
    each group's own "done_count"/"total_count" for a simple progress readout.
    """
    grouped = kidney_tips.personalized_tips(latest_inputs, latest_classification)
    done = checklist_store.completed_tip_ids(user_id, day)
    for group in grouped:
        for tip in group["tips"]:
            tip["is_complete"] = tip["id"] in done
        group["done_count"] = sum(1 for tip in group["tips"] if tip["is_complete"])
        group["total_count"] = len(group["tips"])
    return grouped


def toggle(checklist_store, user_id, tip_id, is_complete, now, day=None):
    if is_complete:
        checklist_store.mark_complete(user_id, tip_id, now, day)
    else:
        checklist_store.mark_incomplete(user_id, tip_id, day)


def day_summary(checklist_store, latest_inputs, latest_classification, user_id, day):
    """(done, total) for one day - "you finished 5 of 14 yesterday". Counted against the tips that apply to the
    person now, so a tip that no longer applies is never counted against them."""
    tip_ids = {tip["id"] for group in kidney_tips.personalized_tips(latest_inputs, latest_classification) for tip in group["tips"]}
    return len(checklist_store.completed_tip_ids(user_id, day) & tip_ids), len(tip_ids)


def progress(grouped):
    """(done, total) across every group - for a single overall progress readout."""
    done = sum(group["done_count"] for group in grouped)
    total = sum(group["total_count"] for group in grouped)
    return done, total
