"""
decorators.py - the two "guards" placed above a route to protect it.

    @account_bp.route("/account")
    @login_required                      # only signed-in people
    def settings(): ...

    @account_bp.route("/professional")
    @role_required("professional")       # only signed-in people with this role (implies login_required)
    def professional_home(): ...

A guard runs BEFORE the page's own code, so a protected page can never be reached by leaving the guard out
of the page's logic. Who is signed in is decided in routes/auth_hooks.py, not in the URL or the form.
"""
from functools import wraps

from flask import abort, g, redirect, request, url_for


def login_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        if g.get("user_lookup_failed"):
            abort(503)                      # the database is down, so we cannot tell who this is
        if g.get("user") is None:
            # Send them to sign in and, afterwards, back to the page they wanted.
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return guarded


def role_required(*roles):
    def decorator(view):
        @login_required
        @wraps(view)
        def guarded(*args, **kwargs):
            if g.user["role"] not in roles:
                abort(403)                  # signed in, but this page is for another role
            return view(*args, **kwargs)
        return guarded
    return decorator
