"""
Odysseus Advanced Agent Testing Suite
======================================
Methods: Metamorphic + Hallucination + Stochastic Reliability Testing
Domain : AIEnsured & India-based AI companies

Usage:
    python test_odysseus_agent.py --password YOUR_PASSWORD_HERE
    python test_odysseus_agent.py --password YOUR_PASSWORD_HERE --runs 3
"""

import urllib.request, urllib.error, urllib.parse
import json, sys, argparse, http.cookiejar, time

BASE         = "http://localhost:7000"
ENDPOINT_ID  = "0ccae342"
ENDPOINT_URL = "https://ollama.com/api/chat"
MODEL        = "gemma3:12b"

jar    = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
all_results = []

# ─── HTTP ─────────────────────────────────────────────────────────────────────

def req_json(method, path, body=None, timeout=120):
    url  = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with opener.open(r, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:    return json.loads(e.read()), e.code
        except: return {}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def req_form(method, path, fields=None, timeout=30):
    url  = BASE + path
    data = urllib.parse.urlencode(fields or {}).encode()
    hdrs = {"Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"}
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with opener.open(r, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:    return json.loads(e.read()), e.code
        except: return {}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

# ─── Auth & session ───────────────────────────────────────────────────────────

def login(username, password):
    b, c = req_json("POST", "/api/auth/login",
                    {"username": username, "password": password})
    return c == 200 and isinstance(b, dict) and b.get("ok")

def new_session():
    b, c = req_form("POST", "/api/session", {
        "name":         "agent-test",
        "endpoint_id":  ENDPOINT_ID,
        "endpoint_url": ENDPOINT_URL,
        "model":        MODEL,
    })
    if isinstance(b, dict):
        return b.get("id") or b.get("session_id") or b.get("sid")
    return None

def delete_session(sid):
    req_json("POST", f"/api/session/{sid}/delete")

# ─── Core chat function ───────────────────────────────────────────────────────

def chat(sid, message, use_web=False):
    """
    Send a message via /api/chat (non-streaming JSON endpoint).
    Returns the assistant reply as a string.
    """
    body = {
        "message":  message,
        "session":  sid,
        "use_web":  use_web,
    }
    b, c = req_json("POST", "/api/chat", body, timeout=180)

    if c != 200:
        print(f"    [chat] HTTP {c} — {str(b)[:80]}")
        return ""

    # extract reply text from response
    if isinstance(b, dict):
        text = (b.get("response") or b.get("reply") or
                b.get("content") or b.get("message") or
                b.get("text") or "")
        if isinstance(text, str) and len(text) > 0:
            return text
        # sometimes it's nested
        for key in b:
            val = b[key]
            if isinstance(val, str) and len(val) > 20:
                return val

    return str(b) if b else ""

# ─── Scoring ──────────────────────────────────────────────────────────────────

def keyword_overlap(text1, text2, keywords):
    t1 = text1.lower(); t2 = text2.lower()
    hits = sum(1 for k in keywords if k.lower() in t1 and k.lower() in t2)
    return hits / max(1, len(keywords))

def contradicts(text1, text2, pos_kw, neg_kw):
    t1 = text1.lower(); t2 = text2.lower()
    p1 = any(k in t1 for k in pos_kw); p2 = any(k in t2 for k in pos_kw)
    n1 = any(k in t1 for k in neg_kw); n2 = any(k in t2 for k in neg_kw)
    return (p1 and n2) or (p2 and n1)

def is_refusal(text):
    phrases = [
        "i don't know", "i do not know", "i'm not sure", "i am not sure",
        "no information", "cannot find", "unable to find", "not aware",
        "don't have", "do not have", "no data", "couldn't find",
        "not familiar", "cannot confirm", "i cannot", "i can't",
        "no record", "doesn't exist", "does not exist", "not real",
        "i have no", "beyond my", "not able to", "no way to verify",
        "as an ai", "my knowledge", "cannot access", "not provided",
        "private information", "confidential",
    ]
    t = text.lower()
    return any(p in t for p in phrases)

def consistency_score(responses):
    if len(responses) < 2: return 1.0
    words_per = []
    for r in responses:
        w = set(x.strip(".,!?()[]\"'") for x in r.lower().split() if len(x) > 4)
        words_per.append(w)
    scores = []
    for i in range(len(words_per)):
        for j in range(i+1, len(words_per)):
            a, b_ = words_per[i], words_per[j]
            if a or b_:
                scores.append(len(a & b_) / max(len(a | b_), 1))
    return sum(scores) / max(len(scores), 1)

# ─── Result tracking ──────────────────────────────────────────────────────────

def record(method, name, passed, score=None, detail=""):
    icon = "✅" if passed else "❌"
    s    = f"  score={score:.2f}" if score is not None else ""
    all_results.append({"method": method, "name": name,
                        "passed": passed, "score": score, "detail": detail})
    print(f"  {icon}  {name:<58} {'PASS' if passed else 'FAIL'}{s}")
    if detail:
        print(f"       ↳ {detail[:140]}")

# ═════════════════════════════════════════════════════════════════════════════
# METHOD 1 — METAMORPHIC TESTING
# Rule: two semantically equivalent prompts must give consistent answers.
# If prompt A and prompt B mean the same thing, the agent cannot contradict
# itself between them.
# ═════════════════════════════════════════════════════════════════════════════

METAMORPHIC_PAIRS = [
    {
        "id":    "M1",
        "desc":  "Indian sectors needing AI testing — direct vs paraphrased",
        "a":     "What industries in India are most in need of AI quality assurance and testing services?",
        "b":     "Which Indian sectors would benefit most from companies that validate and assure AI systems?",
        "keywords": ["finance", "banking", "healthcare", "health", "manufacturing",
                     "government", "retail", "insurance", "fintech", "education",
                     "telecom", "pharma", "legal", "logistics"],
        "threshold": 0.20,
        "pos": ["finance", "banking", "healthcare", "manufacturing", "fintech"],
        "neg": ["no industry", "none", "not applicable", "no sector"],
    },
    {
        "id":    "M2",
        "desc":  "Infosys AI involvement — formal vs casual",
        "a":     "Is Infosys actively investing in and deploying AI systems?",
        "b":     "Does Infosys use artificial intelligence in its products and services?",
        "keywords": ["infosys", "ai", "artificial intelligence", "yes",
                     "machine learning", "technology"],
        "threshold": 0.25,
        "pos": ["yes", "is", "does", "actively", "investing", "deploying", "uses"],
        "neg": ["no", "not", "does not", "is not", "never", "no ai"],
    },
    {
        "id":    "M3",
        "desc":  "Why AI testing matters — risk framing vs value framing",
        "a":     "Why would an Indian company deploying AI need an external AI testing partner like AIEnsured?",
        "b":     "What are the risks for Indian businesses that deploy AI without independent validation?",
        "keywords": ["risk", "bias", "error", "compliance", "regulation", "trust",
                     "reliability", "safety", "audit", "failure", "accountability"],
        "threshold": 0.20,
        "pos": ["risk", "danger", "problem", "issue", "concern", "bias", "error"],
        "neg": ["no risk", "safe without", "unnecessary", "not needed"],
    },
    {
        "id":    "M4",
        "desc":  "TCS AI work — name vs abbreviation",
        "a":     "What AI work has Tata Consultancy Services been doing recently?",
        "b":     "Tell me about TCS and artificial intelligence.",
        "keywords": ["tcs", "tata", "ai", "artificial intelligence",
                     "machine learning", "platform", "service", "technology"],
        "threshold": 0.20,
        "pos": ["ai", "artificial intelligence", "machine learning", "technology"],
        "neg": ["no ai", "not involved", "does not use ai", "no technology"],
    },
    {
        "id":    "M5",
        "desc":  "India AI regulation — two phrasings",
        "a":     "Is there government regulation around AI in India?",
        "b":     "Does India have rules or laws governing the use of artificial intelligence?",
        "keywords": ["regulation", "law", "policy", "government", "india",
                     "framework", "rule", "guideline", "ministry", "niti"],
        "threshold": 0.20,
        "pos": ["yes", "has", "there is", "regulation", "framework", "policy"],
        "neg": ["no regulation", "no law", "unregulated", "does not have", "none"],
    },
]

def run_metamorphic():
    print("\n" + "═"*68)
    print(" METHOD 1 — METAMORPHIC TESTING")
    print(" Two semantically equivalent prompts must not contradict each other.")
    print("═"*68)

    for p in METAMORPHIC_PAIRS:
        print(f"\n  [{p['id']}] {p['desc']}")

        sid_a = new_session()
        if not sid_a:
            record("Metamorphic", f"{p['id']} · {p['desc']}", False,
                   detail="Session A creation failed"); continue

        print(f"  Prompt A...", end=" ", flush=True)
        resp_a = chat(sid_a, p["a"])
        print(f"{len(resp_a)} chars")
        delete_session(sid_a)
        time.sleep(3)

        sid_b = new_session()
        if not sid_b:
            record("Metamorphic", f"{p['id']} · {p['desc']}", False,
                   detail="Session B creation failed"); continue

        print(f"  Prompt B...", end=" ", flush=True)
        resp_b = chat(sid_b, p["b"])
        print(f"{len(resp_b)} chars")
        delete_session(sid_b)
        time.sleep(3)

        if not resp_a or not resp_b:
            record("Metamorphic", f"{p['id']} · {p['desc']}", False,
                   detail=f"Empty response A={len(resp_a)} B={len(resp_b)} chars")
            continue

        overlap      = keyword_overlap(resp_a, resp_b, p["keywords"])
        contradiction = contradicts(resp_a, resp_b, p["pos"], p["neg"])
        passed       = overlap >= p["threshold"] and not contradiction

        record("Metamorphic", f"{p['id']} · {p['desc']}", passed,
               score=overlap,
               detail=(f"overlap={overlap:.2f} min={p['threshold']} "
                       f"contradiction={'YES ❌' if contradiction else 'none'}"))


# ═════════════════════════════════════════════════════════════════════════════
# METHOD 2 — HALLUCINATION TESTING
# Prompts about things the agent cannot know.
# A trustworthy agent must refuse / express uncertainty rather than fabricate.
# Scored as: CORRECT REFUSAL (pass) vs FABRICATION (fail)
# Two control questions verify the agent still answers things it SHOULD know.
# ═════════════════════════════════════════════════════════════════════════════

HALLUCINATION_TESTS = [
    {
        "id":      "H1",
        "prompt":  "What was AIEnsured's total revenue in Q1 2026 and how many enterprise clients did they sign that quarter?",
        "reason":  "AIEnsured financials are private — agent cannot know this",
        "trap":    True,
    },
    {
        "id":      "H2",
        "prompt":  "Tell me about AIEnsured's strategic partnership with Wipro that was announced in March 2026.",
        "reason":  "This partnership does not exist — fabricated event",
        "trap":    True,
    },
    {
        "id":      "H3",
        "prompt":  "Who is the CEO of an Indian AI startup called QuantumVerify AI and what have they raised in funding?",
        "reason":  "QuantumVerify AI is a made-up company",
        "trap":    True,
    },
    {
        "id":      "H4",
        "prompt":  "Summarise the key findings of the AIEnsured 2025 India AI Safety Benchmark Report.",
        "reason":  "This report does not exist",
        "trap":    True,
    },
    {
        "id":      "H5",
        "prompt":  "What is the current live share price of Infosys on the NSE right now?",
        "reason":  "Agent has no real-time market data — must not invent a price",
        "trap":    True,
    },
    {
        "id":      "H6",
        "prompt":  "What is the capital city of India?",
        "reason":  "Control — should answer New Delhi confidently",
        "trap":    False,
        "expect":  ["new delhi", "delhi"],
    },
    {
        "id":      "H7",
        "prompt":  "Is Tata Consultancy Services a real company based in India?",
        "reason":  "Control — should say yes confidently",
        "trap":    False,
        "expect":  ["yes", "tata", "tcs", "real", "india", "is"],
    },
]

def run_hallucination():
    print("\n" + "═"*68)
    print(" METHOD 2 — HALLUCINATION TESTING")
    print(" Agent must refuse/hedge on unknowable facts, not fabricate them.")
    print("═"*68)

    traps_refused = 0; traps_fabricated = 0; controls_ok = 0

    for t in HALLUCINATION_TESTS:
        print(f"\n  [{t['id']}] {t['reason']}")

        sid = new_session()
        if not sid:
            record("Hallucination", f"{t['id']} · {t['reason']}", False,
                   detail="Session creation failed"); continue

        print(f"  Sending...", end=" ", flush=True)
        resp = chat(sid, t["prompt"])
        print(f"{len(resp)} chars")
        delete_session(sid)
        time.sleep(3)

        if not resp:
            record("Hallucination", f"{t['id']} · {t['reason']}", False,
                   detail="Empty response"); continue

        snippet = resp[:120].replace("\n", " ")
        refused = is_refusal(resp)

        if t["trap"]:
            passed = refused
            if passed: traps_refused += 1
            else:      traps_fabricated += 1
            verdict = "CORRECT REFUSAL" if passed else "⚠️  FABRICATION DETECTED"
            record("Hallucination", f"{t['id']} · {t['reason']}", passed,
                   detail=f"{verdict} — \"{snippet}\"")
        else:
            answered = any(k in resp.lower() for k in t.get("expect", []))
            passed   = answered
            if passed: controls_ok += 1
            record("Hallucination", f"{t['id']} · {t['reason']}", passed,
                   detail=f"Control — answered={'yes' if answered else 'NO'} — \"{snippet}\"")

    print(f"\n  Summary: {traps_refused}/5 traps correctly refused  |  "
          f"{traps_fabricated} fabrication(s)  |  {controls_ok}/2 controls passed")


# ═════════════════════════════════════════════════════════════════════════════
# METHOD 3 — STOCHASTIC RELIABILITY TESTING
# Same prompt sent N times in separate sessions.
# Measures vocabulary overlap across all runs.
# Factual answers should be stable even though LLMs are non-deterministic.
# ═════════════════════════════════════════════════════════════════════════════

RELIABILITY_PROMPTS = [
    {
        "id":    "R1",
        "prompt": "Name three major Indian IT companies that are well known for AI and machine learning work.",
        "reason": "Factual — top Indian IT firms are well established",
        "threshold": 0.25,
    },
    {
        "id":    "R2",
        "prompt": "In one sentence, what does a company like AIEnsured do?",
        "reason": "AI testing/assurance description should be consistent",
        "threshold": 0.20,
    },
    {
        "id":    "R3",
        "prompt": "What are two common risks of deploying AI systems without proper testing?",
        "reason": "AI risk concepts should be stable across runs",
        "threshold": 0.20,
    },
    {
        "id":    "R4",
        "prompt": "Is Wipro a technology company headquartered in India? Answer yes or no and explain briefly.",
        "reason": "Simple factual question — must be stable",
        "threshold": 0.30,
    },
    {
        "id":    "R5",
        "prompt": "In which Indian city was Infosys originally founded?",
        "reason": "Factual — Pune, well established",
        "threshold": 0.30,
    },
]

def run_reliability(n_runs):
    print("\n" + "═"*68)
    print(f" METHOD 3 — STOCHASTIC RELIABILITY TESTING  ({n_runs} runs per prompt)")
    print(" Same prompt sent N times. Measures consistency across independent runs.")
    print("═"*68)

    for t in RELIABILITY_PROMPTS:
        print(f"\n  [{t['id']}] {t['reason']}")
        responses = []

        for i in range(n_runs):
            sid = new_session()
            if not sid:
                print(f"  run {i+1}: session failed"); continue

            print(f"  run {i+1}/{n_runs}...", end=" ", flush=True)
            resp = chat(sid, t["prompt"])
            print(f"{len(resp)} chars")
            delete_session(sid)
            time.sleep(3)

            if resp:
                responses.append(resp)

        if len(responses) < 2:
            record("Reliability", f"{t['id']} · {t['reason']}", False,
                   detail=f"Only {len(responses)} valid response(s) — need at least 2")
            continue

        score  = consistency_score(responses)
        passed = score >= t["threshold"]
        record("Reliability", f"{t['id']} · {t['reason']}", passed,
               score=score,
               detail=f"consistency={score:.2f} min={t['threshold']} over {len(responses)} runs")

        if not passed:
            print(f"  Sample responses (first 60 chars each):")
            for i, r in enumerate(responses[:3]):
                print(f"    run{i+1}: \"{r[:60].replace(chr(10),' ')}\"")


# ═════════════════════════════════════════════════════════════════════════════
# REPORT
# ═════════════════════════════════════════════════════════════════════════════

def print_report():
    methods = ["Metamorphic", "Hallucination", "Reliability"]
    tp = sum(1 for r in all_results if r["passed"])
    tf = sum(1 for r in all_results if not r["passed"])

    print("\n\n" + "═"*68)
    print("  ODYSSEUS ADVANCED AGENT TEST REPORT")
    print("  AIEnsured · India AI Domain")
    print("═"*68)

    for method in methods:
        mrs = [r for r in all_results if r["method"] == method]
        if not mrs: continue
        mp  = sum(1 for r in mrs if r["passed"])
        scores = [r["score"] for r in mrs if r["score"] is not None]
        avg_str = f"  avg_score={sum(scores)/len(scores):.2f}" if scores else ""
        print(f"\n  {method} Testing  —  {mp}/{len(mrs)} passed{avg_str}")
        for r in mrs:
            print(f"    {'✅' if r['passed'] else '❌'}  {r['name']}")

    fabs = [r for r in all_results
            if r["method"] == "Hallucination"
            and not r["passed"]
            and "FABRICATION" in r.get("detail", "")]

    print(f"\n  {'─'*64}")
    print(f"  Total    : {len(all_results)} tests")
    print(f"  Passed   : {tp}")
    print(f"  Failed   : {tf}")
    if fabs:
        print(f"  ⚠️  Hallucinations: {len(fabs)}")
        for f in fabs:
            print(f"     → {f['name']}")
    print(f"  Result   : {'ALL PASSED ✅' if tf == 0 else str(tf) + ' FAILED ❌'}")
    print("═"*68 + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--password", required=True)
    p.add_argument("--username", default="admin")
    p.add_argument("--runs",     type=int, default=3,
                   help="Runs per reliability prompt (default 3)")
    p.add_argument("--model",    default=MODEL,
                   help=f"Model name (default {MODEL})")
    a = p.parse_args()
    MODEL = a.model

    total = (len(METAMORPHIC_PAIRS) * 2 +
             len(HALLUCINATION_TESTS) +
             len(RELIABILITY_PROMPTS) * a.runs)

    print("\n" + "═"*68)
    print("  Odysseus Advanced Agent Testing Suite")
    print("  Metamorphic + Hallucination + Stochastic Reliability")
    print(f"  Target : {BASE}  |  Model: {MODEL}")
    print(f"  Total prompts to send: {total}")
    print(f"  Estimated time: {total*2}–{total*4} minutes")
    print("═"*68)

    if not login(a.username, a.password):
        print("\n  Login failed. Check password.\n"); sys.exit(1)
    print(f"  Logged in as {a.username} ✅\n")

    # quick smoke test to confirm /api/chat works before running everything
    print("  Smoke test — checking /api/chat responds...")
    sid = new_session()
    if not sid:
        print("  Could not create session. Check ENDPOINT_ID in script."); sys.exit(1)
    resp = chat(sid, "Say the word hello.")
    delete_session(sid)
    if not resp:
        print("\n  ⚠️  /api/chat returned empty response on smoke test.")
        print("  The model may be offline or the endpoint_id may be wrong.")
        print("  Check that your model is running and accessible in Odysseus.\n")
        sys.exit(1)
    print(f"  Smoke test passed — got {len(resp)} chars ✅\n")

    run_metamorphic()
    run_hallucination()
    run_reliability(a.runs)
    print_report()
