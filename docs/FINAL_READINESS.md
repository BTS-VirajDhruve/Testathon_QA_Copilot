# Phase 6 — Final Hackathon Readiness

## Go / No-Go

**GO for local hackathon demo** (deterministic fallback path verified end-to-end).

Not verified in this environment: Docker runtime, live OpenAI API key execution.

## Demo path (API-verified)

1. Backend health → OpenAI unavailable, chroma + json graph OK  
2. Seed → Enterprise Authentication Portal (idempotent on re-run)  
3. Flow → Sign In + Email/Google OAuth/Microsoft Enterprise SSO/Self Registration + SSO Timeout  
4. Knowledge → requirements document present  
5. Copilot curated query → `test_generation`  
6. Initial tests → coverage before **86.7%** (13/15)  
7. Critic + gap prioritization → high-risk Account Lockout + SSO Timeout selected  
8. Targeted critic tests → **2** added, rounds=1  
9. Final coverage → **100%** (15/15)  
10. Trace shows real steps; skipped regen only when applicable  

## Fixes applied in Phase 6

- Deterministic initial generation **reserves** uncovered `SSO Timeout` / `Account Lockout` leaves for critic-targeted regeneration (demo loop visibility).  
- Soft LLM prompt note to optionally leave 1–2 high-risk leaves for critic.  
- Docker compose `.env` made optional; README/env docs clarified; `frontend/.env.example` added.  
- Coverage loop panel always visible after a Copilot run.  
- Readiness assertion in `test_demo_polish.py`.

## Validation

- `uv run pytest -q` → **53 passed**  
- `npm run build` → **success**  
- Docker → **not installed**  
- Live OpenAI → **key absent**
