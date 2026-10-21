"""
result_details.py - what a professional sees about ONE saved assessment beyond its risk number: the answers behind
it, what raised and lowered the estimate, and any answer outside the range the model was trained on.

Used by both professional pages that open a single saved result, so they always show exactly the same thing:
  * a patient the professional recorded themselves  (routes/patient_records_routes.py risk_analysis)
  * a person who shared their history with them      (routes/authorization_routes.py shared_result)

Nothing is recalculated as a new result: the explanation is worked out from the assessment's own saved answers by
services/explanations.py, and an assessment saved without answers simply has none to show. Both pages are read by a
professional, so the explanation is worded about "the" answers (explanations.for_professional).
"""
from services import explanations, lab_contract, screening_contract
from services.model_service_stage2 import stage2_describer


def describe(row, catalog, model_service, model_service_stage2):
    """
    row: an assessment from assessment_store.get_assessment() (it carries "inputs" - the saved answers).
    catalog: the Preliminary Screening question catalog (current_app.extensions["catalog"]).
    Returns {"answers": [(group title, [(label, value), ...]), ...], "explanation": dict or None, "outside": [...]}.
    """
    inputs = row.get("inputs")
    if row["assessment_type"] == "enhanced":
        lab_catalog = lab_contract.load_lab_catalog()
        model, describer = model_service_stage2, stage2_describer(lab_catalog)
        answers = (screening_contract.describe_inputs(catalog, inputs) + lab_contract.describe_lab_values(lab_catalog, inputs)) if inputs else []
    else:
        model, describer = model_service, catalog
        answers = screening_contract.describe_inputs(catalog, inputs) if inputs else []
    return {
        "answers": answers,
        # Worded for the professional reading it ("the answer was ..."), not for the patient ("your answer was ...").
        "explanation": explanations.for_professional(explanations.explain_saved_result(model, describer, row)),
        "outside": screening_contract.outside_training(catalog, inputs) if inputs else [],
    }
