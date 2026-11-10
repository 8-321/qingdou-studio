import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE = "http://127.0.0.1:8788"


def call(method, path, body=None, user="matrix"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json", "X-User-Id": user},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"detail": {"code": "HTTP_%d" % e.code}}


def load_links(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.DictReader(f) if (r.get("url") or "").strip()]
    else:
        rows = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        url = (r.get("url") or "").strip()
        if not url or url.startswith("#"):
            continue
        out.append({"platform": (r.get("platform") or "").strip(), "url": url,
                    "note": (r.get("note") or "").strip()})
    return out


def run_one(row: dict, timeout: int) -> dict:
    url = row["url"]
    user = "matrix_" + hashlib.sha1(url.encode()).hexdigest()[:12]
    started = time.time()
    body = {"text": url}
    if row.get("platform"):
        body["platform"] = row["platform"]
    code, res = call("POST", "/api/parse", body, user)
    item = {"platform": row.get("platform") or "auto", "url": url, "note": row.get("note", ""),
            "http": code, "status": "parse_failed", "error": "", "title": "",
            "segments": 0, "seconds": 0.0}
    if code != 200:
        item["error"] = (res.get("detail") or {}).get("code") or str(res)[:120]
        item["seconds"] = round(time.time() - started, 1)
        return item
    task_id = res["task_id"]
    item["platform"] = res.get("platform") or item["platform"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        c, t = call("GET", "/api/tasks/" + task_id, user=user)
        if c != 200:
            item["status"] = "query_failed"
            item["error"] = (t.get("detail") or {}).get("code", "")
            break
        item["status"] = t.get("status", "")
        item["title"] = t.get("title") or ""
        if t.get("status") in ("done", "failed"):
            item["error"] = t.get("error_code") or ""
            break
    if item["status"] == "done":
        c, r = call("GET", "/api/tasks/" + task_id + "/result", user=user)
        if c == 200:
            item["segments"] = len(r.get("segments") or [])
    item["seconds"] = round(time.time() - started, 1)
    return item


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(Path(__file__).with_name("links.json")))
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(Path(__file__).with_name("links_result")))
    args = ap.parse_args()
    rows = load_links(Path(args.file))
    if args.limit:
        rows = rows[:args.limit]
    print("links:", len(rows))
    results = []
    for i, row in enumerate(rows, 1):
        print("[%d/%d] %s" % (i, len(rows), row["url"]))
        item = run_one(row, args.timeout)
        results.append(item)
        print("   ", item["status"], item["error"], item["seconds"], "s", item["segments"], "seg")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with out.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()) if results else ["url"])
        w.writeheader()
        w.writerows(results)
    stats = defaultdict(lambda: [0, 0])
    for r in results:
        stats[r["platform"]][1] += 1
        if r["status"] == "done":
            stats[r["platform"]][0] += 1
    print("\nplatform  success/total")
    for k, (ok, total) in sorted(stats.items()):
        print("%-12s %d/%d" % (k, ok, total))
    ok = sum(1 for r in results if r["status"] == "done")
    print("\nTOTAL %d/%d = %.1f%%" % (ok, len(results), (ok / len(results) * 100) if results else 0))
    print("saved:", out.with_suffix(".json"), out.with_suffix(".csv"))


if __name__ == "__main__":
    main()
