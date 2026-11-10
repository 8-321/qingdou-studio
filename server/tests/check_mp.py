"""小程序静态自检：WXML 事件处理器存在、JS 语法、包体积。"""
import json
import re
import subprocess
import sys
from pathlib import Path

MP = Path(__file__).resolve().parents[2] / "miniprogram"
NODE = r"C:\Users\34137\tools\node-v24.19.0-win-x64\node.exe"
EVENT = re.compile(r'(?:bind|catch):?([a-zA-Z]+)\s*=\s*"([^"{}]+)"', re.I)

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS " + name + (" | " + detail if detail else ""))
    else:
        fail += 1
        print("FAIL " + name + (" | " + detail if detail else ""))


def main():
    app = json.loads((MP / "app.json").read_text(encoding="utf-8"))
    total = 0
    missing = []
    for page in app["pages"]:
        js = MP / (page + ".js")
        wxml = MP / (page + ".wxml")
        check("存在 " + page, js.exists() and wxml.exists())
        code = js.read_text(encoding="utf-8")
        if NODE and Path(NODE).exists():
            r = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True)
            check("语法 " + page, r.returncode == 0, (r.stderr or "").strip().splitlines()[-1:] and r.stderr.strip().splitlines()[-1] or "")
        markup = wxml.read_text(encoding="utf-8")
        handlers = {m.group(2) for m in EVENT.finditer(markup)}
        for h in sorted(handlers):
            if not re.search(r"(^|[\s,{])" + re.escape(h) + r"\s*[\(:]", code, re.M):
                missing.append(page + ":" + h)
    check("事件处理器齐全", not missing, ",".join(missing) if missing else "0 缺失")

    files = [p for p in MP.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    total = len(files)
    print("包体积: %d 个文件 / %.1f KB" % (total, size / 1024))
    check("包体积 < 2MB", size < 2 * 1024 * 1024, "%.1f KB" % (size / 1024))
    print()
    print("MP_PASS" if fail == 0 else "MP_FAIL")
    print("pass=%d fail=%d" % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())