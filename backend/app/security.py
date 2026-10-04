import hashlib, hmac, os, secrets
from datetime import datetime, timedelta, timezone
import jwt

SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()


def verify_password(pw: str, stored: str) -> bool:
    salt, _, h = stored.partition("$")
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex(), h)


def make_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({"sub": str(user_id), "exp": exp}, SECRET, algorithm="HS256")


def read_token(token: str) -> int | None:
    try:
        return int(jwt.decode(token, SECRET, algorithms=["HS256"])["sub"])
    except Exception:
        return None
