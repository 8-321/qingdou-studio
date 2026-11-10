import json, sys, time, urllib.request
BASE="http://127.0.0.1:8788"; H={"Content-Type":"application/json","X-User-Id":"smokelink_%d"%int(time.time())}
def call(m,p,b=None):
    d=json.dumps(b).encode() if b is not None else None
    r=urllib.request.Request(BASE+p,data=d,headers=H,method=m)
    try:
        with urllib.request.urlopen(r,timeout=120) as x: return x.status,json.loads(x.read().decode())
    except urllib.error.HTTPError as e: return e.code,json.loads(e.read().decode())
print("signin:", call("POST","/api/signin"))
code,b=call("POST","/api/parse",{"text":"https://www.bilibili.com/video/BV1GJ411x7h7"})
print("parse:",code,b)
if code==200:
    tid=b["task_id"]
    for _ in range(240):
        c,t=call("GET","/api/tasks/"+tid)
        if t["status"] in ("done","failed"):
            print("final:",t["status"],t["progress"],t.get("title"),t.get("error_code"),t.get("error_msg")); break
        time.sleep(1)
    c,r=call("GET","/api/tasks/"+tid+"/result")
    print("result:",c,"segments:",len(r.get("segments",[])),"chars:",len(r.get("full_text","")))
    if c==200: print("first:",r["segments"][0]["text"][:60])
