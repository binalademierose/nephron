"""
create_admin.py - make (or promote) an administrator account. Administrators are never created through the public
registration page; only someone with access to the server can run this.

    python create_admin.py admin@example.com "Admin Name"     # creates the account and asks for a password
    python create_admin.py existing@example.com --promote     # makes an existing account an administrator
"""
import getpass
import sys

from app import create_app
from services import clock, security
from services.user_store import get_user_store


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    email = argv[1].strip().lower()
    app = create_app()
    with app.app_context():
        store = get_user_store()
        existing = store.find_by_email(email)
        if "--promote" in argv:
            if existing is None:
                print(f"No account uses {email}.")
                return 1
            store.set_admin(existing["user_id"], True)
            print(f"{existing['full_name']} ({email}) is now an administrator.")
            return 0
        if existing is not None:
            print(f"{email} already has an account. Use --promote to make it an administrator.")
            return 1
        full_name = argv[2] if len(argv) > 2 else "Administrator"
        password = getpass.getpass("Password (at least 10 characters): ")
        if len(password) < 10:
            print("The password must have at least 10 characters.")
            return 1
        if getpass.getpass("Password again: ") != password:
            print("The two passwords do not match.")
            return 1
        user_id = store.create_user({"email": email, "full_name": full_name, "role": "general", "is_admin": True,
                                     "professional": None}, security.hash_password(password), clock.now_utc())
        store.set_admin(user_id, True)
        print(f"Administrator {full_name} ({email}) created. Sign in at /login.")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
