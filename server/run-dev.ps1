$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:MOCK_ASR = "1"
$env:FREE_DAILY_QUOTA = "50"
$env:DEV_MODE = "1"
$env:PUBLIC_BASE_URL = "http://127.0.0.1:8788"
$env:ADMIN_PASSWORD = "dev-password-change-me"
$env:ADMIN_SECRET = "dev-secret-change-me"
$env:ADMIN_USER_IDS = "demo"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8788
