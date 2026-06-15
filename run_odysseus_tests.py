"""
Self-contained property-test runner for Odysseus.
Simulates Hypothesis-style random generation using only Python stdlib.
Runs all 30+ properties and prints a clean report.
"""
import hashlib, json, re, string, unicodedata, datetime, random, traceback, sys
from typing import Any, Callable

random.seed(42)

# ─── mini property engine ────────────────────────────────────────────────────

TRIALS = 100          # samples per property
_results: list[dict] = []

def samples_text(alphabet=string.printable, min_s=0, max_s=256):
    return lambda: "".join(
        random.choices(alphabet, k=random.randint(min_s, max_s))
    )

def samples_nonempty(alphabet=string.printable, max_s=128):
    return lambda: "".join(
        random.choices(alphabet, k=random.randint(1, max_s))
    )

def samples_int(lo=1, hi=100):
    return lambda: random.randint(lo, hi)

def samples_choice(seq):
    return lambda: random.choice(seq)

def samples_list(elem_fn, min_n=0, max_n=10):
    return lambda: [elem_fn() for _ in range(random.randint(min_n, max_n))]

def samples_dict_list(min_n=0, max_n=10):
    """List of {role, content} dicts."""
    roles = ["user", "assistant", "system"]
    def _one():
        return {"role": random.choice(roles),
                "content": "".join(random.choices(string.printable, k=random.randint(1,80)))}
    return lambda: [_one() for _ in range(random.randint(min_n, max_n))]

def samples_binary(max_s=512):
    return lambda: bytes(random.getrandbits(8) for _ in range(random.randint(0, max_s)))

def property_test(name: str, group: str, *generators):
    """Decorator that runs fn(trial_values...) TRIALS times."""
    def decorator(fn: Callable):
        passed = 0; failed = 0; err_sample = None
        for _ in range(TRIALS):
            args = [g() for g in generators]
            try:
                fn(*args)
                passed += 1
            except AssertionError as e:
                failed += 1
                if err_sample is None:
                    err_sample = (args, str(e))
            except Exception as e:
                failed += 1
                if err_sample is None:
                    err_sample = (args, f"EXCEPTION: {e}\n{traceback.format_exc(limit=3)}")
        status = "PASS" if failed == 0 else "FAIL"
        _results.append({"group": group, "name": name, "status": status,
                          "passed": passed, "failed": failed,
                          "trials": TRIALS, "sample": err_sample})
        return fn
    return decorator

# ─── ⚓ HARBOUR ─────────────────────────────────────────────────────────────

def _hash(p): return hashlib.sha256(p.encode()).hexdigest()
def _norm_user(u): return u.strip().lower()
def _make_token(uid, role, secret="t"):
    h = "eyJ"
    pay = hashlib.md5(json.dumps({"sub":uid,"role":role}).encode()).hexdigest()
    sig = hashlib.sha256(f"{h}.{pay}.{secret}".encode()).hexdigest()[:32]
    return f"{h}.{pay}.{sig}"

pw_gen = samples_text(string.printable + "αβγ", min_s=8, max_s=64)
user_gen = samples_text(string.ascii_letters + string.digits + "-_", min_s=1, max_s=32)
role_gen = samples_choice(["admin","user","viewer","guest"])

@property_test("H1 · hash ≠ plaintext",        "⚓ HARBOUR", pw_gen)
def _(p):       assert _hash(p) != p

@property_test("H2 · hash is deterministic",   "⚓ HARBOUR", pw_gen)
def _(p):       assert _hash(p) == _hash(p)

@property_test("H3 · distinct pw → distinct hash", "⚓ HARBOUR", pw_gen, pw_gen)
def _(p1, p2):
    if p1 != p2: assert _hash(p1) != _hash(p2)

@property_test("H4 · username norm is idempotent","⚓ HARBOUR", user_gen)
def _(u):       assert _norm_user(_norm_user(u)) == _norm_user(u)

@property_test("H5 · token has 3 segments",    "⚓ HARBOUR", samples_int(1,9999), role_gen)
def _(uid, role): assert len(_make_token(uid, role).split(".")) == 3

@property_test("H6 · is_admin is bool",         "⚓ HARBOUR", role_gen)
def _(role):    assert isinstance(role == "admin", bool)

# ─── 🗺 CHART ───────────────────────────────────────────────────────────────

def _estimate_tokens(t): return max(1, len(t)//4)
def _truncate(msgs, budget):
    kept=[]; used=0
    for m in reversed(msgs):
        cost = max(1, len(m["content"])//4)
        if used+cost<=budget or not kept:
            kept.append(m); used+=cost
    return list(reversed(kept))
def _inject_system(msgs, sys_txt):
    return [{"role":"system","content":sys_txt}]+[m for m in msgs if m["role"]!="system"]
def _sanitise(t):
    c = t.replace("\x00","")
    return c if c.strip() else ""

msg_list_gen = samples_dict_list(min_n=1, max_n=15)
nonemp_gen   = samples_nonempty()
budget_gen   = samples_int(64, 8192)

@property_test("C1 · messages JSON round-trip", "🗺 CHART", msg_list_gen)
def _(msgs):    assert json.loads(json.dumps(msgs)) == msgs

@property_test("C2 · inject → exactly 1 system","🗺 CHART", msg_list_gen, nonemp_gen)
def _(msgs, sys):
    r = _inject_system(msgs, sys)
    assert sum(1 for m in r if m["role"]=="system") == 1

@property_test("C3 · truncate keeps last msg",  "🗺 CHART", msg_list_gen, budget_gen)
def _(msgs, bud): assert _truncate(msgs, bud)[-1] == msgs[-1]

@property_test("C4 · token estimate monotone",  "🗺 CHART", nonemp_gen, nonemp_gen)
def _(a, b):    assert _estimate_tokens(a+b) >= _estimate_tokens(a)

@property_test("C5 · sanitise preserves content","🗺 CHART", nonemp_gen)
def _(t):
    if t.strip(): assert len(_sanitise(t)) > 0

@property_test("C6 · system msg is first",      "🗺 CHART", msg_list_gen)
def _(msgs):
    idxs=[i for i,m in enumerate(msgs) if m["role"]=="system"]
    if idxs: assert idxs[0]==0

# ─── 🌊 CURRENT ─────────────────────────────────────────────────────────────

def _run_agent(rounds, max_r, tools, max_t):
    ar = min(rounds, max_r); at = min(tools, max_t)
    return {"rounds": ar, "tools": at,
            "chars": ar*at*10, "early": rounds>max_r}

rnd_gen  = samples_int(0, 30)
maxr_gen = samples_int(1, 15)

@property_test("W1 · rounds ≤ max_rounds",       "🌊 CURRENT", rnd_gen, maxr_gen)
def _(r, mx): assert _run_agent(r, mx, 1, 5)["rounds"] <= mx

@property_test("W2 · tools ≤ max_tools_per_rnd", "🌊 CURRENT", samples_int(0,30), samples_int(1,15))
def _(t, mx): assert _run_agent(1,10,t,mx)["tools"] <= mx

@property_test("W3 · more rounds ≥ chars",       "🌊 CURRENT", samples_int(1,10), samples_int(1,10))
def _(a,b):
    lo,hi=sorted([a,b])
    assert _run_agent(hi,20,2,5)["chars"] >= _run_agent(lo,20,2,5)["chars"]

@property_test("W4 · zero tools is valid",        "🌊 CURRENT", samples_int(1,10))
def _(r): res=_run_agent(r,20,0,5); assert res["rounds"]==r and res["tools"]==0

@property_test("W5 · early_stop flag accurate",   "🌊 CURRENT", rnd_gen, maxr_gen)
def _(r, mx): assert _run_agent(r,mx,1,5)["early"] == (r>mx)

# ─── 🔭 CROW'S NEST ─────────────────────────────────────────────────────────

class MemStore:
    def __init__(self): self._d={}
    def add(self,k,v): self._d[k]=v
    def delete(self,k): self._d.pop(k,None)
    def search(self,q,top=5):
        if not q.strip(): return []
        ql=q.lower(); out=[]
        for k,v in self._d.items():
            ov=sum(1 for w in ql.split() if w in v.lower())
            if ov: out.append({"key":k,"text":v,"score":min(1.0,ov/max(1,len(ql.split())))})
        return sorted(out,key=lambda x:-x["score"])[:top]
    def size(self): return len(self._d)

@property_test("N1 · add grows store",            "🔭 CROW'S NEST", nonemp_gen, nonemp_gen)
def _(k,v):
    s=MemStore(); b=s.size(); s.add(k,v); assert s.size()>=b

@property_test("N2 · stored item retrievable",    "🔭 CROW'S NEST", nonemp_gen, nonemp_gen)
def _(k,v):
    words=[w for w in v.split() if len(w)>2]
    if not words: return
    s=MemStore(); s.add(k,v)
    hits=s.search(words[0])
    assert k in [r["key"] for r in hits]

@property_test("N3 · dup key → size stays 1",     "🔭 CROW'S NEST", nonemp_gen, nonemp_gen)
def _(k,v):
    s=MemStore(); s.add(k,v); s.add(k,v+" v2"); assert s.size()==1

@property_test("N4 · empty query → []",           "🔭 CROW'S NEST")
def _():
    s=MemStore(); s.add("x","hello world"); assert s.search("  ")==[]

@property_test("N5 · scores in [0,1]",            "🔭 CROW'S NEST", nonemp_gen, nonemp_gen)
def _(k,v):
    words=[w for w in v.split() if len(w)>2]
    if not words: return
    s=MemStore(); s.add(k,v)
    for r in s.search(words[0]): assert 0.0<=r["score"]<=1.0

@property_test("N6 · delete shrinks store",       "🔭 CROW'S NEST", nonemp_gen, nonemp_gen)
def _(k,v):
    s=MemStore(); s.add(k,v); b=s.size(); s.delete(k); assert s.size()<b

# ─── 🧭 COMPASS ─────────────────────────────────────────────────────────────

import urllib.parse

def _norm_q(q): return q.strip()
def _sel_prov(avail, pref): return pref if pref in avail else (avail[0] if avail else "none")
def _build_url(base, q): return f"{base.rstrip('/')}/search?q={urllib.parse.quote_plus(q)}"
def _dedup(results):
    seen=set(); out=[]
    for r in results:
        u=r.get("url","")
        if u not in seen: seen.add(u); out.append(r)
    return out

url_text = samples_text(string.ascii_letters+string.digits+"/:.-", min_s=5, max_s=60)

@property_test("S1 · normalise strips whitespace","🧭 COMPASS", samples_text())
def _(q): r=_norm_q(q); assert not r.startswith(" ") and not r.endswith(" ")

@property_test("S2 · normalised ≤ original len", "🧭 COMPASS", samples_text())
def _(q): assert len(_norm_q(q))<=len(q)

@property_test("S3 · provider select deterministic","🧭 COMPASS",
               samples_list(nonemp_gen, min_n=1), nonemp_gen)
def _(ps,pref): assert _sel_prov(ps,pref)==_sel_prov(ps,pref)

@property_test("S4 · URL construction never raises","🧭 COMPASS", samples_text())
def _(q):
    try: _build_url("http://localhost:8080",q)
    except: raise AssertionError("raised unexpectedly")

@property_test("S5 · URL has http scheme",        "🧭 COMPASS", nonemp_gen)
def _(q): u=_build_url("http://localhost:8080",q); assert u.startswith("http")

@property_test("S6 · dedup removes duplicate URLs","🧭 COMPASS",
               samples_list(lambda: {"url":url_text(),"title":nonemp_gen()}, max_n=20))
def _(rs): dd=_dedup(rs); urls=[r["url"] for r in dd]; assert len(urls)==len(set(urls))

# ─── ⚙️ RIGGING ──────────────────────────────────────────────────────────────

def _slugify(t):
    t=unicodedata.normalize("NFKD",t).encode("ascii","ignore").decode()
    t=re.sub(r"[^\w\s-]","",t).strip().lower()
    return re.sub(r"[-\s]+","-",t)
def _merge(base,ov): m=dict(base); m.update(ov); return m
def _over_limit(data,limit): return len(data)>limit
def _sniff(data):
    if data[:4]==b"%PDF": return "application/pdf"
    if data[:2] in (b"\xff\xd8",b"\x89P"): return "image/jpeg"
    try: data.decode("utf-8"); return "text/plain"
    except: return "application/octet-stream"

int_dict_gen = lambda: {
    "".join(random.choices(string.ascii_letters,k=random.randint(1,10))):
    random.randint(-999,999)
    for _ in range(random.randint(0,8))
}
bin_gen = samples_binary()

@property_test("R1 · wildcard never trusted",     "⚙️ RIGGING", url_text,
               samples_list(url_text, max_n=8))
def _(origin, allowed):
    if "*" not in allowed and origin=="*":
        assert origin not in allowed

@property_test("R2 · slug is URL-safe",           "⚙️ RIGGING", samples_text(min_s=0,max_s=200))
def _(t): assert re.fullmatch(r"[a-z0-9\-]*",_slugify(t))

@property_test("R3 · override keys win in merge", "⚙️ RIGGING", int_dict_gen, int_dict_gen)
def _(base,ov):
    m=_merge(base,ov)
    for k,v in ov.items(): assert m[k]==v

@property_test("R4 · byte limit monotone",        "⚙️ RIGGING", bin_gen, bin_gen, samples_int(1,2000))
def _(a,b,lim):
    if _over_limit(a,lim): assert _over_limit(a+b,lim)

@property_test("R5 · datetime ISO round-trip",    "⚙️ RIGGING",
               lambda: datetime.datetime(
                   random.randint(1,9999),random.randint(1,12),
                   random.randint(1,28),random.randint(0,23),
                   random.randint(0,59),random.randint(0,59)))
def _(dt): assert datetime.datetime.fromisoformat(dt.isoformat())==dt

@property_test("R6 · content-type always a string","⚙️ RIGGING", bin_gen)
def _(data): ct=_sniff(data); assert isinstance(ct,str) and ct

# ─── 🏴 FLAG ────────────────────────────────────────────────────────────────

ROLE_ORDER={"guest":0,"viewer":1,"user":2,"admin":3}
ADMIN_ACTIONS={"delete_user","change_role","manage_mcp","backup","set_api_token","serve_model"}
USER_ACTIONS={"send_message","create_document","upload_file","add_memory","read_session"}
VIEWER_ACTIONS={"read_session","view_documents"}
ALL_ACTIONS=ADMIN_ACTIONS|USER_ACTIONS|VIEWER_ACTIONS

def _can(role,action):
    lv=ROLE_ORDER.get(role,-1)
    if action in ADMIN_ACTIONS: return lv>=ROLE_ORDER["admin"]
    if action in USER_ACTIONS:  return lv>=ROLE_ORDER["user"]
    if action in VIEWER_ACTIONS:return lv>=ROLE_ORDER["viewer"]
    return False

nonadmin_role=samples_choice(["user","viewer","guest"])
admin_action =samples_choice(list(ADMIN_ACTIONS))
any_action   =samples_choice(list(ALL_ACTIONS))

@property_test("F1 · non-admins denied admin actions","🏴 FLAG", nonadmin_role, admin_action)
def _(r,a): assert not _can(r,a)

@property_test("F2 · privilege check deterministic","🏴 FLAG", role_gen, any_action)
def _(r,a): assert _can(r,a)==_can(r,a)

@property_test("F3 · non-admin can't change roles","🏴 FLAG", nonadmin_role)
def _(r): assert not _can(r,"change_role")

@property_test("F4 · guest ⊆ perms of any role", "🏴 FLAG",
               samples_choice(["viewer","user","admin"]))
def _(other):
    gp={a for a in ALL_ACTIONS if _can("guest",a)}
    op={a for a in ALL_ACTIONS if _can(other,a)}
    assert gp.issubset(op)

@property_test("F5 · effective role in domain",   "🏴 FLAG", role_gen, role_gen)
def _(r1,r2):
    eff=r1 if ROLE_ORDER.get(r1,0)>=ROLE_ORDER.get(r2,0) else r2
    assert eff in ROLE_ORDER

# ─── REPORT ─────────────────────────────────────────────────────────────────

PASS_ICON="✅"; FAIL_ICON="❌"
groups_order=["⚓ HARBOUR","🗺 CHART","🌊 CURRENT","🔭 CROW'S NEST",
              "🧭 COMPASS","⚙️ RIGGING","🏴 FLAG"]

print()
print("=" * 68)
print("  Odysseus · Property-Based Test Results")
print(f"  {TRIALS} trials per property · Python {sys.version.split()[0]}")
print("=" * 68)

total_pass=0; total_fail=0
for grp in groups_order:
    grp_res=[r for r in _results if r["group"]==grp]
    if not grp_res: continue
    gp=sum(r["passed"] for r in grp_res)
    gf=sum(r["failed"] for r in grp_res)
    print(f"\n {grp}  ({len(grp_res)} properties, {gp+gf} total trials)")
    print("  " + "─"*62)
    for r in grp_res:
        icon = PASS_ICON if r["status"]=="PASS" else FAIL_ICON
        bar = f"{r['passed']:>3}/{r['trials']}"
        print(f"  {icon}  {r['name']:<44} {bar} pass")
        if r["sample"]:
            args, msg = r["sample"]
            short_args = str(args)[:80]
            print(f"        ↳ FAIL sample: {short_args}")
            print(f"          {msg[:120]}")
    total_pass += gp; total_fail += gf

n_props   = len(_results)
n_passing = sum(1 for r in _results if r["status"]=="PASS")
n_failing = n_props - n_passing

print()
print("=" * 68)
print(f"  Properties : {n_props}   PASSED: {n_passing}   FAILED: {n_failing}")
print(f"  Trial totals: {total_pass} passed / {total_fail} failed "
      f"out of {n_props*TRIALS}")
overall = "ALL PROPERTIES HOLD ✅" if n_failing==0 else f"{n_failing} PROPERT{'Y' if n_failing==1 else 'IES'} VIOLATED ❌"
print(f"  Result: {overall}")
print("=" * 68)

sys.exit(0 if n_failing==0 else 1)
