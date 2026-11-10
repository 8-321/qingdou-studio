import os, subprocess, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
env = os.environ.copy()
for k in ("SEC_CHECK", "SEC_MOCK", "SEC_CALLBACK_TOKEN"):
    if not os.getenv(k):
        env.pop(k, None)
log = open(BASE / "data" / "server.log", "ab")
flags = 0x00000008 | 0x00000200
p = subprocess.Popen([sys.executable, "start_dev.py"], cwd=str(BASE), env=env,
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     creationflags=flags, close_fds=True)
print("pid", p.pid)
