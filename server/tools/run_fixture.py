import os, subprocess, sys
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
log = open(BASE / "data" / "fixture.log", "ab")
p = subprocess.Popen([sys.executable, "-m", "http.server", "8791",
                      "--directory", str(BASE / "tests" / "fixtures")],
                     cwd=str(BASE), stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200, close_fds=True)
print("fixture pid", p.pid)