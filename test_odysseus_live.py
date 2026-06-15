"""
Odysseus Live Integration Tests (final)
Usage: python test_odysseus_live.py --password YOUR_PASSWORD_HERE
"""
import urllib.request, urllib.error, json, sys, argparse, http.cookiejar, urllib.parse

BASE   = "http://localhost:7000"
ENDPOINT_ID  = "0ccae342"
ENDPOINT_URL = "https://ollama.com/api/chat"
MODEL        = "gemma3:4b"

jar    = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
results = []

def req_json(method, path, body=None):
    url  = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with opener.open(r, timeout=10) as resp:
            raw = resp.read(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read(); code = e.code
    except urllib.error.URLError as e:
        return None, 0
    try:    return json.loads(raw), code
    except: return raw.decode(errors="replace"), code

def req_form(method, path, fields=None):
    url  = BASE + path
    data = urllib.parse.urlencode(fields or {}).encode() if fields else None
    hdrs = {"Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"}
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with opener.open(r, timeout=10) as resp:
            raw = resp.read(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read(); code = e.code
    except urllib.error.URLError as e:
        return None, 0
    try:    return json.loads(raw), code
    except: return raw.decode(errors="replace"), code

def check(name, group, passed, detail=""):
    icon = "✅" if passed else "❌"
    results.append({"group":group,"name":name,"passed":passed,"detail":detail})
    print(f"  {icon}  {name:<56} {'PASS' if passed else 'FAIL'}  {detail}")

def run(username, password):

    # ── ⚓ HARBOUR ─────────────────────────────────────────────────────────
    print("\n ⚓ HARBOUR  — Authentication\n  " + "─"*66)

    b,c = req_json("GET","/")
    check("T01 · server reachable","⚓ HARBOUR", c in (200,304,307), f"HTTP {c}")

    b,c = req_json("GET","/api/auth/status")
    check("T02 · /api/auth/status","⚓ HARBOUR", c==200, f"HTTP {c}")

    b,c = req_json("POST","/api/auth/login",{"username":username,"password":"wrongpassword!!"})
    check("T03 · wrong password rejected","⚓ HARBOUR", c in (400,401,403), f"HTTP {c}")

    b,c = req_json("POST","/api/auth/login",{"username":username,"password":password})
    ok  = c==200 and isinstance(b,dict) and b.get("ok")
    check("T04 · correct login ok:true","⚓ HARBOUR", ok, f"HTTP {c} {str(b)[:60]}")
    if not ok:
        print("\n  ⚠️  Login failed — check your password.\n")
        print_report(); sys.exit(1)

    check("T05 · session cookie set","⚓ HARBOUR",
          len(list(jar))>0, str([ck.name for ck in jar]))

    b,c = req_json("POST","/api/auth/logout")
    check("T06 · logout 200","⚓ HARBOUR", c==200, f"HTTP {c}")

    b,c = req_json("GET","/api/auth/users")
    check("T07 · after logout /users blocked","⚓ HARBOUR", c in (401,403), f"HTTP {c}")

    req_json("POST","/api/auth/login",{"username":username,"password":password})

    b,c = req_json("GET","/api/auth/features")
    check("T08 · /api/auth/features","⚓ HARBOUR", c==200, f"HTTP {c}")

    b,c = req_json("GET","/api/auth/settings")
    check("T09 · /api/auth/settings","⚓ HARBOUR", c==200, f"HTTP {c}")

    b,c = req_json("GET","/api/auth/users")
    users = b.get("users",[]) if isinstance(b,dict) else (b if isinstance(b,list) else [])
    check("T10 · /api/auth/users has users","⚓ HARBOUR",
          c==200 and len(users)>0, f"HTTP {c} / {len(users)} user(s)")
    names = [u.get("username","") for u in users if isinstance(u,dict)]
    check("T11 · admin in user list","⚓ HARBOUR", username in names, f"found:{names[:5]}")

    # ── 🗺 CHART — sessions ────────────────────────────────────────────────
    print("\n 🗺 CHART  — Sessions\n  " + "─"*66)

    b,c = req_json("GET","/api/sessions")
    check("T12 · GET /api/sessions","🗺 CHART", c==200, f"HTTP {c}")

    # requires endpoint_id + endpoint_url + model as form fields
    b,c = req_form("POST","/api/session",{
        "name":         "property-test-session",
        "endpoint_id":  ENDPOINT_ID,
        "endpoint_url": ENDPOINT_URL,
        "model":        MODEL,
    })
    sid = None
    if isinstance(b,dict): sid = b.get("id") or b.get("session_id") or b.get("sid")
    check("T13 · POST /api/session creates session","🗺 CHART",
          c in (200,201) and sid is not None, f"HTTP {c} / id={sid}")

    if sid:
        b,c = req_json("GET",f"/api/history/{sid}")
        check("T14 · GET /api/history/:sid","🗺 CHART", c==200, f"HTTP {c}")

        b,c = req_form("PATCH",f"/api/session/{sid}",{"name":"renamed-by-test"})
        check("T15 · PATCH /api/session/:sid renames","🗺 CHART", c==200, f"HTTP {c}")

        b,c = req_json("POST",f"/api/session/{sid}/delete")
        check("T16 · POST /api/session/:sid/delete","🗺 CHART", c in (200,204), f"HTTP {c}")

        b,c = req_json("GET",f"/api/history/{sid}")
        check("T17 · deleted session → 404","🗺 CHART", c==404, f"HTTP {c}")
    else:
        for t,desc in [("T14","GET history"),("T15","rename"),
                       ("T16","delete"),("T17","404 check")]:
            check(f"{t} · skipped — {desc}","🗺 CHART", False, "T13 failed")

    # ── 🔭 CROW'S NEST — memory ────────────────────────────────────────────
    print("\n 🔭 CROW'S NEST  — Memory\n  " + "─"*66)

    b,c = req_json("GET","/api/memory")
    check("T18 · GET /api/memory","🔭 CROW'S NEST", c==200, f"HTTP {c}")

    # snapshot memory ids before adding so we can find the new one
    before_ids = set()
    if isinstance(b,dict):
        before_ids = {m.get("id") for m in b.get("memory",[])}

    b,c = req_json("POST","/api/memory/add",{"text":"property-test memory entry"})
    check("T19 · POST /api/memory/add","🔭 CROW'S NEST", c in (200,201), f"HTTP {c}")

    # find the new memory id by matching on text
    mid = None
    b2,c2 = req_json("GET","/api/memory")
    if isinstance(b2,dict):
        after = b2.get("memory",[])
        matches = [m for m in after if "property-test" in m.get("text","")]
        if matches:
            mid = matches[0].get("id")

    # memory search uses Form fields
    b,c = req_form("POST","/api/memory/search",{"query":"property-test"})
    check("T20 · POST /api/memory/search","🔭 CROW'S NEST", c==200, f"HTTP {c}")

    if mid:
        b,c = req_json("DELETE",f"/api/memory/{mid}")
        check("T21 · DELETE /api/memory/:id","🔭 CROW'S NEST",
              c in (200,204), f"HTTP {c}")
    else:
        check("T21 · DELETE /api/memory/:id","🔭 CROW'S NEST",
              False, "could not resolve new memory id")

    # ── 📄 DOCUMENTS ──────────────────────────────────────────────────────
    print("\n 📄 DOCUMENTS  — Document Store\n  " + "─"*66)

    b,c = req_json("GET","/api/documents/library")
    check("T22 · GET /api/documents/library","📄 DOCUMENTS", c==200, f"HTTP {c}")

    b,c = req_json("POST","/api/document",
                   {"title":"test-doc","content":"property test"})
    did = None
    if isinstance(b,dict):
        did = b.get("id") or b.get("doc_id") or b.get("document_id")
    check("T23 · POST /api/document creates doc","📄 DOCUMENTS",
          c in (200,201), f"HTTP {c} id={did}")

    if did:
        b,c = req_json("GET",f"/api/document/{did}")
        check("T24 · GET /api/document/:id","📄 DOCUMENTS", c==200, f"HTTP {c}")

        b,c = req_json("DELETE",f"/api/document/{did}")
        check("T25 · DELETE /api/document/:id","📄 DOCUMENTS",
              c in (200,204), f"HTTP {c}")
    else:
        check("T24 · GET /api/document/:id","📄 DOCUMENTS", False, "no did from T23")
        check("T25 · DELETE /api/document/:id","📄 DOCUMENTS", False, "no did from T23")

    # ── 🏴 FLAG — privilege enforcement ───────────────────────────────────
    print("\n 🏴 FLAG  — Privilege Enforcement\n  " + "─"*66)

    req_json("POST","/api/auth/logout")

    b,c = req_json("DELETE","/api/auth/users")
    check("T26 · unauthed DELETE /users blocked","🏴 FLAG", c in (401,403), f"HTTP {c}")

    b,c = req_form("POST","/api/session",{"name":"sneaky"})
    check("T27 · unauthed POST /session blocked","🏴 FLAG", c in (401,403), f"HTTP {c}")

    b,c = req_json("PUT","/api/auth/open-signup",{"enabled":True})
    check("T28 · unauthed open-signup blocked","🏴 FLAG", c in (401,403), f"HTTP {c}")

    req_json("POST","/api/auth/login",{"username":username,"password":password})

    # correct field name is current_password
    b,c = req_json("POST","/api/auth/change-password",
                   {"current_password":"totallynotright!!",
                    "new_password":"doesnotmatter123"})
    check("T29 · wrong current_password rejected","🏴 FLAG",
          c in (400,401,403), f"HTTP {c} {str(b)[:60]}")

    b,c = req_json("GET","/api/auth/2fa/status")
    check("T30 · GET /api/auth/2fa/status","🏴 FLAG", c==200, f"HTTP {c}")

    # ── 🧭 COMPASS ─────────────────────────────────────────────────────────
    print("\n 🧭 COMPASS  — Integrations & Models\n  " + "─"*66)

    b,c = req_json("GET","/api/auth/integrations")
    check("T31 · GET /api/auth/integrations","🧭 COMPASS", c==200, f"HTTP {c}")

    b,c = req_json("GET","/api/auth/integrations/presets")
    check("T32 · GET /api/auth/integrations/presets","🧭 COMPASS", c==200, f"HTTP {c}")

    b,c = req_json("GET","/api/models")
    check("T33 · GET /api/models","🧭 COMPASS", c==200, f"HTTP {c}")

    b,c = req_json("GET","/api/auth/settings")
    check("T34 · settings returns dict","🧭 COMPASS",
          c==200 and isinstance(b,dict), f"HTTP {c} type={type(b).__name__}")

    req_json("POST","/api/auth/logout")


def print_report():
    groups = ["⚓ HARBOUR","🗺 CHART","🔭 CROW'S NEST",
              "📄 DOCUMENTS","🏴 FLAG","🧭 COMPASS"]
    tp = sum(1 for r in results if r["passed"])
    tf = sum(1 for r in results if not r["passed"])
    print("\n"+"="*68+"\n  Odysseus Live Test Report\n"+"="*68)
    for g in groups:
        gr = [r for r in results if r["group"]==g]
        if gr:
            gp = sum(1 for r in gr if r["passed"])
            print(f"\n  {g}  —  {gp}/{len(gr)} passed")
    print(f"\n  Total : {tp} passed / {tf} failed out of {len(results)}")
    print(f"  Result: {'ALL TESTS PASSED ✅' if tf==0 else str(tf)+' TEST(S) FAILED ❌'}")
    print("="*68)
    if tf:
        print("\n  Failed tests:")
        for r in results:
            if not r["passed"]:
                print(f"    ❌  {r['name']}  —  {r['detail']}")
    print()

if __name__=="__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--password", required=True)
    p.add_argument("--username", default="admin")
    a = p.parse_args()
    print("\n"+"="*68+
          f"\n  Odysseus · Live Integration Tests"
          f"\n  Target: {BASE}"
          f"\n  User  : {a.username}\n"+"="*68)
    run(a.username, a.password)
    print_report()
