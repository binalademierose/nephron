"""
error_handlers.py - friendly error pages.

Users see a short, calm message. The technical details (stack trace, SQL,
file paths) go to logs/nephron.log and are never shown on screen.
"""
import mysql.connector
from flask import render_template, request

# For each error: title, what happened, and what the person can do next.
ERROR_TEXT = {
    400: ("This form has expired",
          "For your security, the form could not be sent.",
          ["Go back, refresh the page, and try again."]),
    403: ("Access not allowed",
          "You don't have permission to open this page.",
          ["This page is for a different kind of account. Use the menu to go to your own home page."]),
    404: ("Page not found",
          "This page doesn't exist or has moved.",
          ["Check the address for typing mistakes.", "Use the menu to find the page you need."]),
    405: ("Action not allowed",
          "This page doesn't support that action.",
          ["Go back and use the page's own buttons and links."]),
    500: ("Something went wrong",
          "We couldn't complete your request. Please try again in a moment.",
          ["Wait a moment, then try again.",
           "If it keeps happening, tell your system administrator what you were doing."]),
    503: ("Nephron is temporarily unavailable",
          "We can't reach the database right now. Please try again shortly.",
          ["Wait a minute, then try again.",
           "If it keeps happening, contact your system administrator."]),
}


def _render_error(status_code):
    title, message, steps = ERROR_TEXT[status_code]
    page = render_template(
        "errors/error.html",
        page_title=title,
        status_code=status_code,
        error_title=title,
        error_message=message,
        error_steps=steps,
    )
    return page, status_code


def register_error_handlers(app):
    @app.errorhandler(400)
    def handle_bad_request(error):
        return _render_error(400)

    @app.errorhandler(403)
    def handle_forbidden(error):
        return _render_error(403)

    @app.errorhandler(503)
    def handle_unavailable(error):
        return _render_error(503)

    @app.errorhandler(404)
    def handle_not_found(error):
        return _render_error(404)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return _render_error(405)

    @app.errorhandler(500)
    def handle_server_error(error):
        # Flask has already written the full traceback to the log.
        return _render_error(500)

    @app.errorhandler(mysql.connector.Error)
    def handle_database_error(error):
        app.logger.error("Database error on %s: %s", request.path, error, exc_info=error)
        # 503 ("can't reach the database") is only honest for a real connectivity problem - the server was down,
        # dropped the connection, or a similar OperationalError/InterfaceError. Anything else caught by this same
        # broad handler (a bad query, a constraint violation, a driver misuse) is a bug in Nephron itself, not an
        # unreachable database, and saying so here would send someone chasing their MySQL server for a problem
        # that is actually in the code - the general "something went wrong" page is the honest one for those.
        if isinstance(error, (mysql.connector.OperationalError, mysql.connector.InterfaceError)):
            return _render_error(503)
        return _render_error(500)
