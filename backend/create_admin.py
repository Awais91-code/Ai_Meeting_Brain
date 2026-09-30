"""Create an initial administrator interactively, without default credentials."""
from getpass import getpass
from pydantic import TypeAdapter, EmailStr
from app.database import SessionLocal
from app.models import User
from app.security.auth import hash_password

if __name__ == "__main__":
    name = input("Admin name: ").strip()
    email = str(TypeAdapter(EmailStr).validate_python(input("Admin email: ").strip()))
    password = getpass("Password (at least 12 characters): ")
    if not name or len(password) < 12 or password != getpass("Confirm password: "):
        raise SystemExit("Name/password invalid or confirmation did not match.")
    with SessionLocal() as db:
        if db.query(User).filter_by(email=email).first():
            raise SystemExit("That account already exists; no changes made.")
        db.add(User(name=name, email=email, password_hash=hash_password(password), role="admin"))
        db.commit()
    print("Admin created. Sign in at /login.")
