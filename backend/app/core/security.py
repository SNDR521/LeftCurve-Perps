import base64
import hashlib
import json
import secrets

from cryptography.fernet import Fernet
from passlib.context import CryptContext

from app.config import get_settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(pw: str) -> str:
    return _pwd.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    return _pwd.verify(pw, hashed)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Only the hash is persisted."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def _fernet() -> Fernet:
    # Derive a stable 32-byte Fernet key from SECRET_KEY (no extra env var).
    # NOTE: rotating SECRET_KEY invalidates previously stored credentials.
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode("utf-8")).decode("utf-8")


def decrypt_credentials(token: str) -> dict:
    return json.loads(_fernet().decrypt(token.encode("utf-8")).decode("utf-8"))
