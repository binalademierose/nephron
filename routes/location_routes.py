"""
location_routes.py - the barangay list for one Pangasinan municipality or city, for the location questions
(registration, account settings, new patient). Public, read-only reference data: PSGC names and codes only.
"""
from flask import Blueprint, jsonify

from services import ph_locations

location_bp = Blueprint("locations", __name__)


@location_bp.route("/locations/pangasinan/<municipality_code>/barangays")
def barangays(municipality_code):
    rows = ph_locations.barangays(municipality_code)
    if not rows:
        return jsonify({"error": "Unknown municipality or city."}), 404
    response = jsonify({"municipality": ph_locations.name_of(municipality_code), "barangays": rows})
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response
