"""Provision accounts without secrets in command-line arguments or repository files."""
import argparse
import getpass
import json
import os
import tempfile
from pathlib import Path

from quantmesh.auth import USERNAME, load_users, password_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--file", required=True, help="Private users JSON file, outside the checkout")
    args = parser.parse_args()
    if not USERNAME.fullmatch(args.username) or args.username == "local":
        parser.error("Use a lowercase username of 1–64 safe characters; local is reserved.")
    target = Path(args.file).resolve()
    checkout = Path(__file__).resolve().parents[1]
    if target.is_relative_to(checkout):
        parser.error("Keep the credential file outside the project checkout.")
    users = load_users(str(target)) if target.exists() else {}
    password = getpass.getpass("New password (12+ characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match.")
    users[args.username] = password_record(password)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".quantmesh-users-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(users, output)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Account provisioned. Existing sessions for this user are revoked.")


if __name__ == "__main__":
    main()
