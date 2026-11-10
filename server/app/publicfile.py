import base64
import hashlib
import hmac
import os
import time
from pathlib import Path
from urllib.parse import quote

from .config import DATA_DIR

TTL_SEC = int(os.getenv("AUDIO_URL_TTL_SEC", "3600"))


def _secret() -> bytes:
    env = os.getenv("AUDIO_TOKEN_SECRET", "").strip()
    if env:
        return hashlib.sha256(env.encode()).digest()
    from .byok import _master_key
    return _master_key()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_path(path: Path) -> str:
    rel = path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    exp = int(time.time()) + TTL_SEC
    msg = f"{rel}|{exp}".encode()
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]
    return _b64(f"{rel}|{exp}|{sig}".encode())


def resolve_token(token: str) -> Path:
    try:
        rel, exp, sig = _unb64(token).decode().split("|")
        if int(exp) < int(time.time()):
            raise ValueError("EXPIRED")
        want = hmac.new(_secret(), f"{rel}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(want, sig):
            raise ValueError("BAD_SIGNATURE")
        path = (DATA_DIR / rel).resolve()
        if not str(path).startswith(str(DATA_DIR.resolve()) + os.sep) or not path.exists():
            raise ValueError("NOT_FOUND")
        return path
    except Exception as e:
        raise ValueError("BAD_TOKEN") from e


def public_url(path: Path) -> str:
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise ValueError("PUBLIC_BASE_URL_MISSING")
    return f"{base}/api/public/audio/{quote(sign_path(path))}"
