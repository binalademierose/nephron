"""
explanations.py - turns "how much each answer moved this person's estimate" into what the result page shows.

The numbers come from ModelService.explain(). This file only decides which factors are worth showing and finds the words.
It never invents a factor: everything shown is a question the person answered, with their own answer beside it.

The result page has TWO cards: what raised the estimate and what lowered it. Both use ONE scale (the biggest effect in
either direction = 100), so the length of a bar means the same thing in both cards.

Words to keep in mind:
  * "the estimate" is the Predicted Risk Probability. A factor "raised" or "lowered" it compared with an average person in the
    data the model learned from.
  * It explains how the MODEL calculated this result. It does not say what caused anyone's condition and it is not advice.
"""
from services import screening_contract as contract


def _describer(catalog_or_describe):
    """
    build()/explain_saved_result() accept either a Stage 1 catalog (dict, screening_contract.load_catalog()'s own
    shape) or a ready-made describe(name, inputs) function, for a stage whose answers do not all live in that one
    catalog (Enhanced Screening: see services.model_service_stage2.stage2_describer). describe(name, inputs) returns
    (label, answer, answer_brief) for a name that was actually saved, or None for one that was not - the SAME
    contract build() already relied on question_for()/answer_text() for.
    """
    if callable(catalog_or_describe):
        return catalog_or_describe
    catalog = catalog_or_describe

    def describe(name, inputs):
        question = contract.question_for(catalog, name)
        answer = contract.answer_text(question, inputs)
        if answer is None:
            return None
        return question["short"], answer, contract.answer_text(question, inputs, brief=True)
    return describe

MAX_FACTORS = 5                  # per card
SMALLEST_SHARE = 0.03            # a factor with less than 3% of the biggest effect is not worth a line
KINDS = ("raises", "lowers")

CAVEAT = ("Each bar compares a factor with the biggest effect on this result, in either direction. A factor that raised the estimate "
          "pushed this result up, and one that lowered it pushed it down, compared with an average person in the data the model learned "
          "from. This explains how the model calculated your result. It does not show what caused your health, and it is not medical advice.")

EMPTY = {
    "raises": "None of your answers raised the estimate by a meaningful amount.",
    "lowers": "None of your answers lowered the estimate by a meaningful amount.",
}

UNAVAILABLE = ("A step-by-step explanation is not available for this result. It can only be shown for a result made by the model that "
               "is running now, from the answers saved with it.")


def build(catalog_or_describe, effects, inputs, limit=MAX_FACTORS):
    """
    catalog_or_describe: a Stage 1 catalog, OR a describe(name, inputs) function for a stage with more than one
    catalog of answers (see _describer above).
    effects: [{"name", "effect"}] from a model's explain(), strongest first.
    inputs:  the answers saved with the result.
    Returns {"raises": [...], "lowers": [...], "summary": {"raises": [...], "lowers": [...]}, "empty": {...}, "caveat": text},
    or None when there is nothing honest to show at all. Each item is
    {"name", "label", "answer", "answer_brief", "direction", "share"}, with share = 100 for the biggest effect in EITHER card.
    """
    describe = _describer(catalog_or_describe)
    largest = max((abs(e["effect"]) for e in effects), default=0.0)
    if largest <= 0:
        return None
    lists = {"raises": [], "lowers": []}
    for effect in effects:
        share = abs(effect["effect"]) / largest
        if share < SMALLEST_SHARE:
            continue
        described = describe(effect["name"], inputs)
        if described is None:                                        # an answer that was not saved is never guessed
            continue
        label, answer, answer_brief = described
        kind = "raises" if effect["effect"] > 0 else "lowers"
        if len(lists[kind]) < limit:
            lists[kind].append({
                "name": effect["name"], "label": label, "answer": answer,
                "answer_brief": answer_brief,
                "direction": kind, "share": max(1, round(100 * share)),
            })
    if not lists["raises"] and not lists["lowers"]:
        return None
    return {"raises": lists["raises"], "lowers": lists["lowers"],
            "summary": {kind: _sentences(kind, lists[kind]) for kind in KINDS}, "empty": EMPTY, "caveat": CAVEAT}


def _sentences(kind, items):
    if not items:
        return []
    verb = "raised" if kind == "raises" else "lowered"
    top = items[0]
    sentences = [f"{top['label']} {verb} the estimate the most: your answer was {top['answer_brief']}."]
    others = items[1:3]
    if others:
        sentences.append("Next came " + " and ".join(f"{item['label']} ({item['answer_brief']})" for item in others) + ".")
    return sentences


def explain_saved_result(model, catalog_or_describe, row, tolerance=1e-4):
    """
    The explanation for a SAVED assessment, or None if it cannot be given honestly. It is worked out again from the answers saved
    with the result, and only when the model that is running now is the model that made it (same model_version). If the
    probability worked out now is not the probability that was saved, nothing is shown.
    catalog_or_describe: see build() above.
    """
    if not model.ready or not model.can_explain:
        return None
    if not row.get("model_version") or row["model_version"] != model.version or not row.get("inputs"):
        return None
    # .get(), not [] : a feature genuinely absent from the saved answers (an optional lab value nobody gave, for
    # Enhanced Screening) becomes None here, the same as it was when this result was first computed - never a
    # KeyError, and never guessed into something that was not actually saved.
    values = {name: row["inputs"].get(name) for name in model.metadata["features"]}
    try:
        result = model.explain(values)
    except Exception:                                               # any failure means "no explanation", never a wrong one
        return None
    if abs(result["probability"] - row["probability"]) > tolerance:
        return None
    return build(catalog_or_describe, result["effects"], row["inputs"])
