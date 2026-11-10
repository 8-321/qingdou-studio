import os
import uvicorn

os.environ.setdefault("MOCK_ASR", "1")
os.environ.setdefault("FREE_DAILY_QUOTA", "50")
os.environ.setdefault("DEV_MODE", "1")
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8788")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("ADMIN_SECRET", "local-admin-secret")
os.environ.setdefault("ADMIN_USER_IDS", "demo")

uvicorn.run("app.main:app", host="127.0.0.1", port=8788, reload=False)
