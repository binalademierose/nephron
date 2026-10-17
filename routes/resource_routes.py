"""
resource_routes.py - the PhilHealth accredited centers directory. Read-only reference data (services/philhealth_centers.py);
no sign-in is required, same as the other Resources pages.
"""
from flask import Blueprint, current_app, render_template, request

from routes.decorators import login_required
from services import philhealth_centers

resource_bp = Blueprint("resources", __name__)


def _params():
    return {
        "term": request.args.get("q", "").strip(),
        "region": request.args.get("region", "").strip() or None,
        "sector": request.args.get("sector", "").strip() or None,
    }


@resource_bp.route("/philhealth-centers")
@login_required
def philhealth_directory():
    params = _params()
    matches, total = philhealth_centers.search(term=params["term"], region=params["region"], sector=params["sector"])
    return render_template("resources/philhealth_centers.html", page_title="PhilHealth Accredited Centers",
                           results=matches, total=total, regions=philhealth_centers.regions(), **params)


@resource_bp.route("/philhealth-centers/search")
@login_required
def philhealth_search():
    """The live-search endpoint: the same search, as JSON, for the page's own script to call while the person types."""
    try:
        params = _params()
        matches, total = philhealth_centers.search(term=params["term"], region=params["region"], sector=params["sector"])
    except Exception as error:                              # a search box must never surface a raw error
        current_app.logger.error("PhilHealth centers search failed: %s: %s", type(error).__name__, error)
        return {"error": "Search is temporarily unavailable."}, 503
    return {"results": matches, "total": total, "shown": len(matches)}
