"""
kidney_tips.py - personalized kidney-health tips, matched from the SAME answers already saved with a result
(services/screening_contract.py, services/lab_contract.py) - never a new question asked of the person.

Nephron is a screening and decision-support tool, not a physician: every tip here is general, guideline-based
education, phrased so it is clearly conditional ("if your doctor has told you...", "ask your doctor before...")
rather than a personal prescription, and NONE of them ever tells a person to start, stop, or change a dose of a
medication - only to raise it with their doctor. Sources are named plainly (KDIGO 2024 CKD Guideline unless noted)
rather than invented; where the evidence itself is nuanced (hydration, potassium, protein), the tip says so
instead of giving a single hard number.

A tip's `condition(inputs, classification)` reads directly from the assessment's own saved inputs - the exact
dict already used to explain and re-check that result - so a rule for an Enhanced-only field (a lab value)
simply never matches a Preliminary-only assessment, without any special-casing here.
"""

KDIGO_2024 = "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD"
KDIGO_DIABETES = "KDIGO 2022 Clinical Practice Guideline for Diabetes Management in CKD"
KDIGO_BP = "KDIGO 2021 Clinical Practice Guideline for the Management of Blood Pressure in CKD"

CATEGORY_LABELS = {
    "diet": "Diet", "hydration": "Hydration", "activity": "Physical activity",
    "lifestyle": "Lifestyle", "medication": "Medication", "follow_up": "Follow-up",
}


def _yes(inputs, key):
    return inputs.get(key) == 1


def _has(inputs, key):
    return inputs.get(key) is not None


TIPS = [
    # ---- diet ----
    {"id": "diet_general", "category": "diet", "always": True,
     "text": "Favor whole foods - vegetables, fruits, whole grains, and plant-based proteins - over processed and "
             "ultra-processed foods, which tend to be high in sodium, sugar, and additives.",
     "source": KDIGO_2024},
    {"id": "diet_sodium", "category": "diet",
     "condition": lambda i, c: _yes(i, "Hypertension") or c == "high",
     "text": "Aim to lower your salt intake - guidelines suggest under about 2 g of sodium (roughly 5 g of salt) a "
             "day for people with high blood pressure or kidney risk. Check food labels; most sodium comes from "
             "processed and packaged food, not the salt shaker.",
     "source": KDIGO_BP},
    {"id": "diet_processed_food", "category": "diet",
     "condition": lambda i, c: i.get("UltraProcessedFoodFrequency") in ("3-4 times/week", "5-6 times/week", "Daily"),
     "text": "You reported eating ultra-processed food often. These foods (instant noodles, packaged snacks, "
             "processed meats) are usually high in sodium and additives that add extra work for your kidneys - "
             "swapping even a few servings a week for a home-cooked alternative can help.",
     "source": KDIGO_2024},
    {"id": "diet_sugar", "category": "diet",
     "condition": lambda i, c: i.get("SugaryDrinksAddedSugar") in ("High", "Very High") or _yes(i, "Diabetes"),
     "text": "Cutting back on sugar-sweetened drinks and added sugar helps manage both blood sugar and weight, "
             "both of which matter for kidney health over time.",
     "source": KDIGO_DIABETES},
    {"id": "diet_potassium", "category": "diet",
     "condition": lambda i, c: _has(i, "Potassium") and i["Potassium"] > 5.0,
     "text": "Your potassium reading is on the higher side. Some foods (bananas, oranges, potatoes, tomatoes, "
             "many salt substitutes) are especially high in potassium - ask your doctor or a renal dietitian "
             "whether you personally need to watch these, since the right approach depends on your specific "
             "kidney function and medications.",
     "source": KDIGO_2024},
    {"id": "diet_protein", "category": "diet",
     "condition": lambda i, c: _has(i, "eGFR") and i["eGFR"] < 60,
     "text": "With reduced kidney function, very high protein intake (large amounts of meat, protein supplements) "
             "may add extra strain. This is individual - a doctor or renal dietitian can advise the right protein "
             "level for you; do not start a restrictive diet on your own.",
     "source": KDIGO_2024},
    {"id": "diet_phosphorus", "category": "diet",
     "condition": lambda i, c: _has(i, "Phosphorus") and i["Phosphorus"] > 4.5,
     "text": "Your phosphorus reading is on the higher side. Processed foods and colas often contain added "
             "phosphorus that the body absorbs easily - your doctor can advise whether you need to limit these.",
     "source": KDIGO_2024},

    # ---- hydration (deliberately no single universal number) ----
    {"id": "hydration_general", "category": "hydration", "always": True,
     "text": "Stay consistently hydrated with water through the day rather than large amounts at once. How much "
             "fluid is right for you varies by body size, climate, activity, and any heart or kidney condition - "
             "there is no one safe number for everyone, so ask your doctor what range fits you.",
     "source": KDIGO_2024},
    {"id": "hydration_heart_failure", "category": "hydration",
     "condition": lambda i, c: _yes(i, "Heart_Failure"),
     "text": "With a history of heart failure, drinking too much fluid can be harmful. If your doctor has given "
             "you a specific daily fluid limit, follow that rather than general hydration advice.",
     "source": KDIGO_2024},

    # ---- activity ----
    {"id": "activity_general", "category": "activity", "always": True,
     "text": "Aim for at least 150 minutes a week of moderate-intensity activity (e.g. brisk walking) - spread "
             "across most days - at a level that is comfortable for your own cardiovascular fitness.",
     "source": KDIGO_BP},
    {"id": "activity_sedentary", "category": "activity",
     "condition": lambda i, c: i.get("Physical_Activity_Level") == "Sedentary",
     "text": "You reported a mostly sedentary week. Start small and build up gradually - even short daily walks "
             "make a real difference - rather than jumping straight to an intense routine.",
     "source": KDIGO_2024},
    {"id": "activity_weight", "category": "activity",
     "condition": lambda i, c: _yes(i, "Obesity"),
     "text": "Combining regular activity with a balanced diet supports a healthier body weight, which in turn "
             "eases the load on your kidneys and heart. Aim for gradual, sustainable change rather than a rapid diet.",
     "source": KDIGO_2024},

    # ---- lifestyle ----
    {"id": "lifestyle_smoking", "category": "lifestyle",
     "condition": lambda i, c: i.get("Smoking_Status") == "Current",
     "text": "Stopping smoking is one of the most protective things you can do for both your kidneys and your "
             "heart. Ask your doctor about support and options for quitting - you do not have to do it alone.",
     "source": KDIGO_2024},
    {"id": "lifestyle_alcohol", "category": "lifestyle",
     "condition": lambda i, c: i.get("Alcohol_Consumption") == "Heavy",
     "text": "You reported heavy alcohol use. Cutting back reduces strain on the kidneys and liver alike, and "
             "your doctor can help if cutting down feels difficult.",
     "source": KDIGO_2024},
    {"id": "lifestyle_sleep", "category": "lifestyle",
     "condition": lambda i, c: _has(i, "Sleep_Duration_Hours") and i["Sleep_Duration_Hours"] < 6,
     "text": "You reported less than 6 hours of sleep on a usual night. Consistently short sleep is linked with "
             "higher blood pressure and blood sugar over time - both relevant to kidney health.",
     "source": KDIGO_2024},

    # ---- medication (never "stop" - only "ask your doctor") ----
    {"id": "medication_general", "category": "medication", "always": True,
     "text": "Never stop, start, or change the dose of any prescribed medication on your own - always talk to "
             "your doctor first, even if you feel well or have read something that concerns you.",
     "source": KDIGO_2024},
    {"id": "medication_nsaid", "category": "medication",
     "condition": lambda i, c: _yes(i, "NSAID_Usage"),
     "text": "You reported using NSAID pain relievers (like ibuprofen or naproxen). Frequent NSAID use can affect "
             "kidney function, especially alongside certain blood pressure medicines - ask your doctor or "
             "pharmacist whether an alternative pain reliever may be more suitable for you.",
     "source": KDIGO_2024},
    {"id": "medication_ace_arb_both", "category": "medication",
     "condition": lambda i, c: _yes(i, "ACE_Inhibitor") and _yes(i, "ARB"),
     "text": "You reported taking both an ACE inhibitor and an ARB. Guidelines generally advise against combining "
             "these two medicine types - this is worth confirming with your prescriber.",
     "source": KDIGO_BP},
    {"id": "medication_diabetes_adherence", "category": "medication",
     "condition": lambda i, c: _yes(i, "Diabetes_Medication"),
     "text": "Keeping up with your diabetes medication and regular blood sugar checks, alongside the lifestyle "
             "steps above, is one of the strongest ways to protect your kidneys over time.",
     "source": KDIGO_DIABETES},

    # ---- follow-up ----
    {"id": "follow_up_high", "category": "follow_up",
     "condition": lambda i, c: c == "high",
     "text": "This result places you in a higher-risk group. Consider discussing it with a doctor soon, especially "
             "if you have not had your kidney function checked recently.",
     "source": KDIGO_2024},
    {"id": "follow_up_egfr_low", "category": "follow_up",
     "condition": lambda i, c: _has(i, "eGFR") and i["eGFR"] < 60,
     "text": "Your estimated kidney filtration rate (eGFR) is below the typical adult range. This is worth "
             "reviewing with a doctor, who can check it against a full picture of your health.",
     "source": KDIGO_2024},
    {"id": "follow_up_general", "category": "follow_up", "always": True,
     "text": "However you are feeling, keep up with routine check-ups - kidney disease often has no symptoms "
             "in its early stages, which is exactly why regular screening matters.",
     "source": KDIGO_2024},
]


def personalized_tips(inputs, classification):
    """
    inputs: the assessment's own saved inputs dict (row["inputs"] - Preliminary answers, and Enhanced's lab
    values plus eGFR, when present). classification: "low" or "high".
    Returns an ordered list of {category, category_label, tips: [{text, source}]} - one entry per category that
    has at least one matching tip, skipping any category with none so the panel is never padded with an empty
    heading.
    """
    inputs = inputs or {}
    matched = [tip for tip in TIPS if tip.get("always") or (tip.get("condition") and tip["condition"](inputs, classification))]
    grouped = []
    for category, label in CATEGORY_LABELS.items():
        in_category = [{"id": tip["id"], "text": tip["text"], "source": tip["source"]} for tip in matched if tip["category"] == category]
        if in_category:
            grouped.append({"category": category, "category_label": label, "tips": in_category})
    return grouped
