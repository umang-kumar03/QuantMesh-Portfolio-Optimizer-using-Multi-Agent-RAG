"""Provision accounts without secrets in command-line arguments or repository files."""
import argparse
import getpass
from pathlib import Path

from quantmesh.auth import USERNAME, password_record
from quantmesh.account_store import update_account


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--file", required=True, help="Private users JSON file, outside the checkout")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--revoke", action="store_true", help="Revoke sessions without changing password")
    actions.add_argument("--disable", action="store_true", help="Remove account access (never reuse usernames)")
    args = parser.parse_args()
    if not USERNAME.fullmatch(args.username) or args.username == "local":
        parser.error("Use a lowercase username of 1–64 safe characters; local is reserved.")
    target = Path(args.file).resolve()
    checkout = Path(__file__).resolve().parents[1]
    working_directory = Path.cwd().resolve()
    in_project = ((working_directory / "app.py").is_file()
                  and (working_directory / "pyproject.toml").is_file()
                  and target.is_relative_to(working_directory))
    if target.is_relative_to(checkout) or in_project:
        parser.error("Keep the credential file outside the project checkout.")
    if args.revoke or args.disable:
        update_account(target, args.username, action="revoke" if args.revoke else "disable")
    else:
        password = getpass.getpass("New password (12+ characters): ")
        if password != getpass.getpass("Confirm password: "):
            parser.error("Passwords do not match.")
        update_account(target, args.username, record=password_record(password))
    print("Account updated. Existing sessions for this user are revoked.")


if __name__ == "__main__":
    main()
