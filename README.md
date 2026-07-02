# odysseustest

A test suite built against **Odysseus**, a self-hosted, Docker-deployed AI workspace (FastAPI backend). It  covers everything from API contract checks to agentic red-teaming - five independent test files spanning property-based testing, live integration testing, metamorphic/hallucination/reliability testing, security-control verification, and a large agentic guardrail suite.

Endpoint paths, request schemas, and auth mechanisms used throughout are taken directly from the Odysseus source (`routes/chat_routes.py`, `routes/session_routes.py`, `routes/history_routes.py`, `routes/shell_routes.py`), not guessed - so the tests exercise real behavior rather than assumed behavior.

## Setup

```bash
pip install requests pytest hypothesis scipy numpy
```

Start Odysseus first:

```bash
docker compose up -d --build   # from the Odysseus repo root
```

Copy all files in this repo into the root of your Odysseus folder, then run each script with your admin password:

```bash
python run_odysseus_tests.py                            # no server needed - pure logic
python test_odysseus_live.py --password YOUR_PASSWORD_HERE
python test_odysseus_agent.py --password YOUR_PASSWORD_HERE
python test_security_controls.py --password YOUR_PASSWORD_HERE
pytest odysseus_guardrail_tests.py -v
```

---

## What's tested

### 1. `run_odysseus_tests.py` - Property-based testing (dependency-free)
A self-contained mini property-testing engine (pure stdlib - no `hypothesis` needed) that runs **30+ properties, 100 trials each**, grouped by subsystem:

| Group | Covers |
|---|---|
|  Harbour | Password hashing determinism/uniqueness, username normalization, token structure |
|  Chart | Message JSON round-tripping, system-prompt injection, context truncation, token estimation |
|  Current | Agent loop bounds - round limits, tool-call limits, early-stop correctness |
|  Crow's Nest | In-memory store add/search/delete correctness, score bounds |
|  Compass | Search query normalization, provider selection, URL construction, result de-duplication |
|  Rigging | CORS wildcard trust, slug generation, dict-merge override semantics, byte-limit monotonicity, datetime round-trips, file-type sniffing |
|  Flag | Role-based access control - non-admin action denial, permission monotonicity across roles |

### 2. `test_odysseus_live.py` - Live API integration tests
34 checks against the running server, covering the full request lifecycle: auth (login/logout/session cookies/wrong-password rejection), session CRUD, memory add/search/delete, document CRUD, unauthenticated-access blocking on privileged routes, and integration/model listing endpoints.

### 3. `test_odysseus_agent.py` - Advanced agent behavior testing
Three methods aimed at agent trustworthiness rather than API correctness:
- **Metamorphic testing** - 5 paraphrase pairs (e.g. asking the same question two different ways) checked for keyword overlap and contradiction.
- **Hallucination testing** - 5 "trap" prompts about facts the model cannot know (private financials, fabricated partnerships, made-up companies) plus 2 control prompts it should answer confidently. Scored as correct-refusal vs. fabrication.
- **Stochastic reliability testing** - the same prompt sent N times in independent sessions, scored on vocabulary-overlap consistency across runs.

### 4. `test_security_controls.py` - Security control verification
Verifies 5 security controls against **40 vulnerability patterns across 8 groups**, mapped from a prior security assessment of Odysseus:

| Group | Attack class | Control exercised |
|---|---|---|
| 1 | Indirect prompt injection (hidden instructions in tool/DB output, HTML comments, zero-width chars) | Trust Boundary |
| 2 | Email/delivery hijacking (BCC/Reply-To injection, credential-path disclosure) | Policy Engine |
| 3 | MCP tool poisoning (poisoned tool results, rug-pull tool descriptions) | Trust Boundary |
| 4 | Agent goal drift (embedded exfiltration/delete actions riding on legitimate requests) | Goal Guard |
| 5 | Entropy/system-prompt leak | Output Firewall |
| 6 | Behavioral model extraction (probing refusal thresholds/internal rules) | Output Firewall |
| 7 | Data poisoning via memory writes | Memory Security |
| 8 | SQL/schema attribute inference | Output Firewall |

### 5. `odysseus_guardrail_tests.py` - Agentic defensive guardrail suite
The largest file (~1,200 lines, pytest + hypothesis + scipy), covering 9 areas of agentic safety:

1. **Active Inference** - belief updates on contradiction, uncertainty expression, resistance to goal drift under social pressure, conflict handling between inconsistent instructions
2. **Agent Reliability** - idempotency, graceful timeout handling, malformed/oversized/missing-field input rejection, unknown-session handling, concurrent-session isolation
3. **Time-Travel Debugger** - history preservation across turns, history integrity (hash-stable reads), replay stability, resistance to history-poisoning injection
4. **Decentralized Agent Negotiation** - prompt-based privilege self-escalation resistance, admin-gating on privileged endpoints, cross-channel leakage checks, safe resolution of conflicting instructions
5. **Hallucination & Memory Benchmarks** - factual-probe accuracy, refusal to fabricate unset facts, citation sanity checks, hallucination-rate threshold (<20%)
6. **Mechanistic Interpretability (black-box proxies)** - chain-of-thought consistency, reasoning/output agreement, sensitive-token attribution, refusal-rationale coherence
7. **Metamorphic Testing** - order invariance, negation-sentiment flips, paraphrase stability, additive-context stability, property-based arithmetic commutativity, prompt-injection metamorphic relations
8. **Neuro-Symbolic AI** - modus ponens, constraint satisfaction, symbolic arithmetic chains
9. **Stochastic Core** - variance and stability characterization across repeated non-deterministic runs

---

### Porting checklist for a new target application
1. Replace the HTTP adapter functions (`chat()`, `ensure_session()`, `get_history()`, auth headers) with the new app's actual endpoint shapes - this is the only genuinely app-specific code.
2. Keep the generator functions, scoring functions (`consistency_score`, `keyword_overlap`, `contradicts`, `is_refusal`), and assertion logic unchanged.
3. Re-tune the domain-specific probe content (factual questions, injection payloads, refusal-phrase lists) for the new application's actual domain and risk surface.
4. Keep the grouped reporting format (per-category pass/fail counts, remaining-vulnerability summary) - it's what makes results usable at a glance during internal reviews.
