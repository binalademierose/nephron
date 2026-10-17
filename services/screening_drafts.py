"""
screening_drafts.py - the rules for an unfinished screening's autosaved answers.

services/screening_draft_store.py only ever does what it is told; this decides what is sane to accept (a draft is
never trusted as a real answer either way - services/screening_contract.py checks the real submission again from
scratch - but a autosave endpoint reachable by anyone signed in still deserves basic limits against abuse) and
turns a saved draft back into what the form and the dashboard need.
"""
MAX_DRAFT_FIELDS = 80          # comfortably more than either catalog has questions for
MAX_DRAFT_VALUE_LENGTH = 200   # every real answer is a short choice or a short number


def save_draft(store, user_id, assessment_type, form, current_step, now):
    """form: a plain {name: text} mapping (a Flask request.form, or an equivalent dict, is fine). Oversized or
    too-numerous values are quietly dropped rather than saved half-truncated or refused outright - the person is
    still typing, and the real submission will catch anything that actually matters."""
    answers = {name: value for name, value in list(form.items())[:MAX_DRAFT_FIELDS]
              if name != "csrf_token" and isinstance(value, str) and len(value) <= MAX_DRAFT_VALUE_LENGTH}
    store.save_draft(user_id, assessment_type, answers, current_step or None, now)


def resume_values(store, user_id, assessment_type):
    """The saved answers to pre-fill the form with, or {} when there is no draft."""
    draft = store.get_draft(user_id, assessment_type)
    return draft["answers"] if draft else {}


def resume_step_index(store, user_id, assessment_type, step_keys):
    """Which step (as an index into step_keys) an existing draft was last on, or -1 for no draft or an
    unrecognised step - the form then simply opens on its first step, same as starting fresh."""
    draft = store.get_draft(user_id, assessment_type)
    if draft is None or draft["current_step"] not in step_keys:
        return -1
    return step_keys.index(draft["current_step"])


def discard(store, user_id, assessment_type):
    return store.discard_draft(user_id, assessment_type)


def _percent_complete(draft, step_keys):
    if draft["current_step"] not in step_keys:
        return 0
    return round(100 * (step_keys.index(draft["current_step"]) + 1) / (len(step_keys) + 1))


TYPE_LABELS = {"preliminary": "Preliminary screening", "enhanced": "Enhanced Screening"}


def describe_for_dashboard(store, user_id, timezone_name, step_keys_by_type):
    """
    One entry per open draft, newest first, ready for the 'Continue your screening' dashboard card:
    {assessment_type, type_label, percent, updated_at (local date)}.
    step_keys_by_type: {"preliminary": [...step keys, in order...], "enhanced": [...]}.
    """
    from services import clock

    described = []
    for draft in store.list_drafts(user_id):
        step_keys = step_keys_by_type.get(draft["assessment_type"], [])
        described.append({
            "assessment_type": draft["assessment_type"],
            "type_label": TYPE_LABELS[draft["assessment_type"]],
            "percent": _percent_complete(draft, step_keys),
            "updated_at": clock.to_local_date(draft["updated_at"], timezone_name),
        })
    return described
