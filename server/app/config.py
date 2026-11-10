import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
WORK_DIR = DATA_DIR / "work"
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "app.db"
FILE_TTL_HOURS = int(os.getenv("FILE_TTL_HOURS", "24"))
FREE_DAILY_QUOTA = int(os.getenv("FREE_DAILY_QUOTA", "20"))
FREE_FEATURE_TRIES = int(os.getenv("FREE_FEATURE_TRIES", "2"))
MAX_DURATION_SEC = int(os.getenv("MAX_DURATION_SEC", "10800"))
FREE_MAX_SECONDS = int(os.getenv("FREE_MAX_SECONDS", "600"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "2048"))
COOKIES_DIR = Path(os.getenv("COOKIES_DIR", DATA_DIR / "cookies"))
COOKIES_DIR.mkdir(parents=True, exist_ok=True)

ASR_PROVIDER = os.getenv("ASR_PROVIDER", "auto")
MOCK_ASR = os.getenv("MOCK_ASR", "1") == "1"
HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or ""

SUBTITLE_LANGS = ["zh-Hans", "zh-CN", "zh", "zh-Hant", "en", "en-US"]
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


