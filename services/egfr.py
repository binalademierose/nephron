"""
egfr.py - the CKD-EPI 2021 (race-free) creatinine equation for estimated glomerular filtration rate.

Nephron never asks a person for their eGFR. It is always CALCULATED from three values the person (or their lab report)
already gives: serum creatinine, age, and sex - the same way a real laboratory calculates it. This keeps the number
consistent with how eGFR is actually reported in practice, and means an OCR-scanned document only needs to yield a
creatinine value for eGFR to be available.

Reference: Inker LA et al., "New Creatinine- and Cystatin C-Based Equations to Estimate GFR without Race",
N Engl J Med 2021;385:1737-1749 (the CKD-EPI 2021 creatinine equation). This module reimplements the published
formula; it does not reproduce the paper's text.
"""
import math

_CONSTANTS = {
    "Female": {"kappa": 0.7, "alpha": -0.241, "sex_factor": 1.012},
    "Male": {"kappa": 0.9, "alpha": -0.302, "sex_factor": 1.0},
}
_SCALE = 142
_AGE_BASE = 0.9938
_UPPER_EXPONENT = -1.2


def estimate_gfr(serum_creatinine_mg_dl, age_years, sex, round_to=1):
    """
    eGFR in mL/min/1.73 m^2, from serum creatinine (mg/dL), age (years) and sex ("Female" or "Male").
    Raises ValueError for a creatinine or age that cannot give a real answer (zero or negative), or a sex
    this equation is not defined for - it never guesses or silently substitutes a default.
    """
    if sex not in _CONSTANTS:
        raise ValueError(f"the CKD-EPI equation needs sex to be 'Female' or 'Male', not {sex!r}")
    if not (isinstance(serum_creatinine_mg_dl, (int, float)) and serum_creatinine_mg_dl > 0):
        raise ValueError(f"serum creatinine must be a positive number, not {serum_creatinine_mg_dl!r}")
    if not (isinstance(age_years, (int, float)) and age_years > 0):
        raise ValueError(f"age must be a positive number, not {age_years!r}")

    constants = _CONSTANTS[sex]
    ratio = serum_creatinine_mg_dl / constants["kappa"]
    value = (_SCALE * min(ratio, 1.0) ** constants["alpha"] * max(ratio, 1.0) ** _UPPER_EXPONENT
            * _AGE_BASE ** age_years * constants["sex_factor"])
    return round(value, round_to) if round_to is not None else value
