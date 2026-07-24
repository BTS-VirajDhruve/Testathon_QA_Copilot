# Hackathon Demo Runbook (3–5 minutes)

Live presentation path for **Agentic QA Copilot**. Uses the real seed + Copilot pipeline — no fake datasets.

## Startup (before the pitch)

```bash
# Terminal 1 — backend
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

Optional: set `OPENAI_API_KEY` in `.env` for live LLM generation. Without it, the UI shows **Deterministic fallback** and the full demo still works.

---

## Exact live sequence

### 0. Landing (10 sec)

- Point to the product one-liner: *understands the software under test before generating tests*.
- Primary CTA: **Load Demo Project** (top bar or empty state).

### 1. Load Demo Project (15 sec)

- Click **Load Demo Project**.
- Confirm status: **Enterprise Authentication Portal**.
- You land on **QA Copilot** with the curated query ready.

### 2. System Flow (45 sec)

- Open **System Flow**.
- Root: **Sign In**.
- Walk branches:
  - **Email + Password** — Valid / Invalid / Account Lockout / Forgot Password / MFA
  - **Google OAuth** — Consent / Callback / Provider Failure / Session Creation
  - **Microsoft Enterprise SSO** — SAML / OIDC / **SSO Timeout** / IdP Failure
  - **Self Registration** — Email Verification / Profile Creation
- Say: *this user-provided graph is first-class context for Graph RAG*.

### 3. Knowledge Base (30 sec)

- Open **Knowledge Base** — requirements document is seeded.
- Open **Test Cases** (seed catalog) — Successful email login, Invalid password, Successful Google OAuth.
- Open **Bug Reports** — Invalid OAuth state, Locked users → Dashboard, SSO timeout infinite loading.
- Say: *Vector RAG retrieves this QA knowledge; Graph RAG understands paths*.

### 4. QA Copilot — run (60–90 sec)

- Open **QA Copilot**.
- Point to:
  - **What is being tested** — Enterprise Authentication Portal → Sign In
  - **Context used** — System Flow / Requirements / Existing Tests / Historical Bugs
  - **What the AI will do** — generate → critic → gaps → targeted tests → improved coverage
- Click **Run agentic analysis** (curated query is pre-filled).
- Loading banner should appear while the pipeline runs.

### 5. Results — story beats (90–120 sec)

1. **Context used** — graph paths + vector hits + existing tests + bugs.
2. **Initial tests** — expand one card:
   - Why this test exists
   - Graph path
   - Evidence (requirements / bugs / graph)
   - Generation method (LLM or Deterministic fallback — be honest)
3. **Coverage loop panel**:
   - INITIAL analysis → CRITIC → COVERAGE GAPS → TARGETED TESTS → FINAL COVERAGE
   - Live metrics: initial count, before %, gaps found, selected high-priority, targeted count, duplicates removed, after %, remaining gaps
4. **Targeted test** — show:
   - *Generated to address coverage gap: …*
   - Graph path (often SSO Timeout or Account Lockout)
5. **Agent Trace** — walk real steps (skipped steps stay marked skipped).

### 6. Close (15 sec)

- Traditional AI tests are generic; this system grounds every case in **system flow + evidence**, then **improves coverage only where it matters**.

---

## Curated query (do not invent a different one live)

```
Analyze the Sign In flow. Generate comprehensive tests focused on security, negative scenarios, historical bugs, and uncovered branches. Then identify coverage gaps and generate targeted tests for the highest-risk gaps.
```

## Demo talking points (problem → solution)

```
SYSTEM FLOW GRAPH  +  QA KNOWLEDGE
        ↓
GRAPH RAG + VECTOR RAG
        ↓
EVIDENCE-BACKED TEST GENERATION
        ↓
CRITIC → COVERAGE GAPS → TARGETED TESTS
        ↓
IMPROVED COVERAGE
```

## Fallback safety

| Situation | What to say |
|-----------|-------------|
| Badge: Deterministic fallback | “Running without OpenAI — same pipeline, deterministic generators.” |
| Badge: OpenAI ready | “Live LLM generation + embeddings.” |
| Targeted tests = 0 | “All high-priority gaps already covered after initial generation.” |

## Pre-flight checklist

- [ ] Backend health OK (`/api/health`)
- [ ] Frontend loads
- [ ] Load Demo Project succeeds twice without duplicate projects
- [ ] Curated Copilot query completes with loading state
- [ ] Coverage loop shows before/after from live API
- [ ] At least one test card shows Why / Graph / Evidence
- [ ] Trace shows real steps only
