import sys
from app.database import SessionLocal, init_db
from app.core.models import User
from app.core.security import hash_password


def reset_password(email: str, password: str) -> None:
    email = email.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise ValueError(f"No user {email}")
        user.password_hash = hash_password(password)
        db.commit()
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: python -m app.core.reset_password <email> <new-password>")
        raise SystemExit(2)
    init_db()
    reset_password(sys.argv[1], sys.argv[2])
    print(f"Password reset for {sys.argv[1]}")


if __name__ == "__main__":
    main()
