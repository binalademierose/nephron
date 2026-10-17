"""
ckd_facts.py - the handful of CKD education statistics shown on the dashboard, about the PHILIPPINES.

The team and the people using Nephron are in the Philippines, so figures about US adults were taken out (panel
review): every number here is about Filipinos, or is general kidney physiology that holds anywhere.

This is reference content, not something that changes per-user or at runtime, so it is a plain Python module
(same spirit as ml/feature_catalog.json) rather than anything database-backed. Every figure here is a real,
sourced statistic - never invented, never a rounded-up "nicer" number - and every one carries its own source, so
a change to a figure means also updating the source it came from. Each source was read before it was added; the
date in the label is the date of the article that reported it.

Nothing here is a diagnosis or a personal risk number: these are population-level facts, framed as such, kept
separate from anything about the person's own saved results (and from Nephron's own community counts, which come
from services/community_stats.py and are labelled as Nephron's).
"""

PNA_2023 = "Philippine News Agency (2 June 2023), citing the Philippine Society of Nephrology"
PNA_2023_URL = "https://alpha.pna.gov.ph/articles/1202791"
PNA_IHME = "Philippine News Agency (2 June 2023), citing Institute for Health Metrics and Evaluation data for 2019"
NKTI_2025 = "National Kidney and Transplant Institute, reported by ABS-CBN News (19 June 2025)"
NKTI_2025_URL = "https://www.abs-cbn.com/news/health-science/2025/6/19/marcos-jr-orders-doh-to-address-rise-in-chronic-kidney-disease-cases-in-ph-1656"
NIDDK = "National Institute of Diabetes and Digestive and Kidney Diseases (NIDDK)"
NIDDK_URL = "https://www.niddk.nih.gov/health-information/kidney-disease"

PREVALENCE = {
    "eyebrow": "How common is CKD here?",
    "value": "7 million", "icon": "users", "short_caption": "Filipinos estimated to have CKD (2021)",
    "detail": "At least 7 million Filipinos were estimated to have chronic kidney disease as of 2021 - an extrapolation "
              "from National Kidney Institute data that its authors say may be an underestimate.",
    "source_label": PNA_2023, "source_url": PNA_2023_URL,
}

AWARENESS = {
    "eyebrow": "Why screening matters",
    "value": "1 in 10", "ring_percent": 10, "short_caption": "Filipinos with CKD may be diagnosed",
    "detail": "Only as few as 10 percent of Filipinos with CKD are diagnosed. Early-stage CKD often causes no "
              "noticeable symptoms, which is why screening matters.",
    "source_label": PNA_2023, "source_url": PNA_2023_URL,
}

KIDNEY_FAILURE = {
    "eyebrow": "Kidney failure",
    "value": "Every hour", "icon": "clock", "short_caption": "one Filipino develops chronic kidney failure",
    "detail": "The National Kidney and Transplant Institute estimates that one Filipino develops chronic kidney "
              "failure every hour - around 120 new cases per million people a year.",
    "source_label": NKTI_2025, "source_url": NKTI_2025_URL,
}

CAUSE_OF_DEATH = {
    "eyebrow": "A leading cause of death",
    "value": "4th", "icon": "heart", "short_caption": "most common cause of death in the Philippines (2019)",
    "detail": "Chronic kidney disease ranked as the fourth most common cause of death in the Philippines in 2019.",
    "source_label": PNA_IHME, "source_url": PNA_2023_URL,
}

SEX_DIFFERENCES = {
    "eyebrow": "Does sex make a difference?",
    "stats": [
        {"short": "More often progresses to kidney failure", "value": "Men", "icon": "user",
         "detail": "Progression to kidney failure is more common in men. Researchers have studied several possible "
                   "reasons, including hormonal differences - this is still an active area of research, not a settled, "
                   "single cause."},
    ],
    "source_label": "Ricardo et al., Journal of the American Society of Nephrology (sex-related differences in CKD progression)",
    "source_url": "https://journals.lww.com/jasn/",
}

AGE_DECLINE = {
    "eyebrow": "Kidneys and age",
    "value": "After 40", "icon": "activity", "short_caption": "kidney function slowly declines, about 1 point a year",
    "detail": "Kidney function tends to decline gradually with age even without CKD - on average by roughly "
              "1 mL/min/1.73m² a year after about age 40, though this varies a lot between individuals.",
    "source_label": f"{NIDDK}; peer-reviewed nephrology research on age-related decline", "source_url": NIDDK_URL,
}


def all_facts():
    return {"prevalence": PREVALENCE, "awareness": AWARENESS, "kidney_failure": KIDNEY_FAILURE,
            "cause_of_death": CAUSE_OF_DEATH, "sex_differences": SEX_DIFFERENCES, "age_decline": AGE_DECLINE}
