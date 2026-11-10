$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:MOCK_ASR = "1"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8788 --reload
