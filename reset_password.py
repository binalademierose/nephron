"""
reset_password.py - sets a new password for an account, from the terminal.

    python reset_password.py

Nephron has no "forgot my password" email yet, so whoever runs the system (you, during the demo) uses this
when someone is locked out. It asks for the email and the new password (typed without showing it), applies the
same password rules as the website, unlocks the account and signs it out everywhere.
It changes the database named in .env, so it is for the person who controls the server, never for the public.
"""
import getpass
import sys

from app import app
from services import auth_service, clock
from services.user_store import get_user_store
from services.validation import check_password, clean_email


def main():
    email = clean_email(input("Email of the account: "))
    with app.app_context():
        store = get_user_store()
        user = store.find_by_email(email)
        if user is None:
            print("There is no account with that email.")
            return 1
        password = getpass.getpass("New password (not shown): ")
        problem = check_password(password, email, user["full_name"])
        if problem:
            print(problem)
            return 1
        if getpass.getpass("Type it again: ") != password:
            print("The two passwords are not the same. Nothing was changed.")
            return 1
        auth_service.reset_password(store, email, password, clock.now_utc())
    print(f"Done. {user['full_name']} can now sign in with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
