"""
Rail Nirdeshak - CLI Controller / Administrator Account Provisioning Tool
Usage:
    python backend/create_controller.py --username controller --password YourPassword123! --role controller
    python backend/create_controller.py --interactive
"""

import sys
import os
import argparse
import getpass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine, Base, upgrade_database_schema
import models
from auth import hash_password

def provision_user(username: str, password: str, role: str = "controller", email: str = None, full_name: str = None, railway_id: str = None):
    upgrade_database_schema(engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Check if username or email exists
        existing = db.query(models.User).filter(
            (models.User.username == username) | (models.User.email == (email or f"{username}@railnirdeshak.in"))
        ).first()

        if existing:
            existing.hashed_password = hash_password(password)
            existing.role = role
            existing.is_active = True
            if email:
                existing.email = email
            if full_name:
                existing.full_name = full_name
            if railway_id:
                existing.railway_id = railway_id
            db.commit()
            print(f"[SUCCESS] Updated existing user '{existing.username}' with role '{role}' and new password.")
            return

        user = models.User(
            username=username,
            railway_id=railway_id or "123456789012",
            email=email or f"{username}@railnirdeshak.in",
            full_name=full_name or f"{username.capitalize()} Officer",
            hashed_password=hash_password(password),
            role=role,
            is_active=True
        )
        db.add(user)
        db.commit()
        print(f"[SUCCESS] Created authorized {role} account: '{username}' (ID: {user.id})")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to provision user: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser(description="Rail Nirdeshak - Controller/Admin Account Provisioning")
    parser.add_argument("--username", "-u", type=str, help="Username for the new controller")
    parser.add_argument("--password", "-p", type=str, help="Password for the new controller")
    parser.add_argument("--role", "-r", type=str, default="controller", choices=["controller", "admin", "passenger"], help="Account role")
    parser.add_argument("--email", "-e", type=str, help="Official Email Address")
    parser.add_argument("--name", "-n", type=str, help="Full Name of the official")
    parser.add_argument("--railway-id", type=str, help="12-digit Railway ID")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive prompt")

    args = parser.parse_args()

    if args.interactive or (not args.username and not args.password):
        print("=== Rail Nirdeshak - Controller Provisioning Wizard ===")
        username = input("Enter Controller Username: ").strip()
        while not username:
            username = input("Username cannot be empty. Enter Controller Username: ").strip()

        password = getpass.getpass("Enter Secure Password: ")
        while len(password) < 6:
            password = getpass.getpass("Password must be at least 6 characters. Enter Password: ")

        role = input("Enter Role [controller/admin] (default: controller): ").strip().lower() or "controller"
        email = input("Enter Official Email (default: auto-generated): ").strip() or None
        name = input("Enter Full Name (default: auto-generated): ").strip() or None
        railway_id = input("Enter 12-digit Railway ID (default: 123456789012): ").strip() or None

        provision_user(username, password, role, email, name, railway_id)
    else:
        if not args.username or not args.password:
            parser.error("Both --username and --password are required when not running interactively.")
        provision_user(args.username, args.password, args.role, args.email, args.name, args.railway_id)

if __name__ == "__main__":
    main()
