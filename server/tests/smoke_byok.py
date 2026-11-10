import json, urllib.request, time
BASE="http://127.0.0.1:8788"
USER="byok_%d" % int(time.time())
H={"Content-Type":"application/json","X-User-Id":USER}
def call(m,p,b=None):
    d=json.dumps(b).encode() if b is not None else None
    r=urllib.request.Request(BASE+p,data=d,headers=H,method=m)
    try:
        with urllib.request.urlopen(r,timeout=30) as x: return x.status,json.loads(x.read().decode())
    except urllib.error.HTTPError as e: return e.code,json.loads(e.read().decode())

print("user:", USER)
print("features:", call("GET","/api/features"))
print("save llm:", call("POST","/api/keys",{"kind":"llm","provider":"deepseek","api_key":"sk-test-1234567890abcd","skip_test":True}))
print("keys:", call("GET","/api/keys"))
body={"text":"http://127.0.0.1:8791/sample_article.html","platform":"wechat_article"}
for i in range(3):
    c,r=call("POST","/api/parse",body)
    print("attempt",i+1,":",c, r.get("detail",{}).get("code") if c!=200 else "ok")
print("features after:", call("GET","/api/features"))
kid=call("GET","/api/keys")[1]["items"][0]["id"]
print("delete:", call("DELETE","/api/keys/"+kid))
print("keys after:", call("GET","/api/keys"))
