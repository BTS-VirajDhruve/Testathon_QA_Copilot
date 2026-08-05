# Agentic QA Copilot — Testathon Submission Notes

## Project / Initiative Summary

**Agentic QA Copilot** is an enterprise QA intelligence system built during the testathon. Instead of treating AI as a generic test-case chatbot, it first understands the software under test using a **user-provided system flow graph**, then fuses that with **Graph RAG** (paths, dependencies, tests, bugs, risk) and **Vector RAG** (requirements and QA docs).

Specialized agents generate tests, exploratory missions, bug reports, regression recommendations, and impact analysis. A **critic** reviews output, coverage gaps are identified, and **targeted regeneration** fills the highest-risk gaps — with evidence and an agent execution trace on every run.

A full **Enterprise Authentication Portal (Sign In)** demo is one-click loadable. A second **ShopEase ecommerce** sample pack was prepared for manual end-to-end walks (auth, cart, billing, payments). The stack runs with live OpenAI when configured, or in **deterministic fallback** so the demo works without an API key.

---

## Tools Used

| Tool / Platform | Role |
|-----------------|------|
| **Cursor** | Primary IDE + AI coding agent for architecture, implementation, and iteration |
| **OpenAI API** | Chat completions + embeddings for intent, generation, extraction, and RAG |
| **Model routing** (in-app) | Task-aware model selection / escalation (e.g. lighter models for intent, stronger for complex/security test gen) |
| **Next.js 15 + React 19 + Tailwind** | Frontend UI (Copilot console, flow builder, explorers, coverage/trace) |
| **@xyflow/react (React Flow)** | Visual system-flow editor |
| **FastAPI + Pydantic + uv** | Backend API, agents, graph/RAG services |
| **ChromaDB** | Persistent vector store for document RAG (JSON cosine fallback) |
| **Durable JSON graph store** | Primary knowledge graph for path discovery and fusion |
| **Neo4j** (optional) | Write-sync only; not required for demo path discovery |
| **Docker Compose** | Optional packaged run of API + frontend |
| **pytest** | Backend tests (routing, project isolation, etc.) |

---

## Pending Work

What’s left to make this reliable enough for everyday team use — practical polish, not a feature wishlist:

1. **Occasional bugs and UI glitches** — as with any prototype built under testathon time pressure, there are still rough edges: occasional freezes, awkward loading states, and small visual/UX inconsistencies that need a proper cleanup pass.
2. **Output quality isn’t always consistent** — some runs produce sharp, usable test ideas; others are generic, repetitive, or miss the nuance of the flow. We need more prompt/tuning work so results feel trustworthy by default.
3. **Model selection & token-cost optimization** — still figuring out the right balance: stronger models for complex/security scenarios vs cheaper/faster ones for simple asks, so we don’t burn budget on every query.
4. **Response time / wait experience** — longer analyses can feel slow; we want clearer progress feedback and smarter ways to keep wait times reasonable for day-to-day use.
5. **Human review before “done”** — generated tests and bugs should be easier to edit, accept, or reject so QA owns the final pack instead of copy-pasting from a dump of AI text.
6. **Easier onboarding for new projects** — loading a second product (beyond the polished Sign In demo) still takes more manual setup than it should; one smoother “bring your flow + docs” path would help adoption.
7. **Sharing results with the wider team** — today it’s strongest as an interactive demo; we still need a cleaner way to export or hand off outputs into the tools people already live in (test management, tickets, docs).
8. **Stability under real usage** — more soak testing with messy real requirements, incomplete flows, and concurrent use so it doesn’t surprise people mid-sprint.
9. **Clearer guidance when something goes wrong** — friendlier messages when a run fails, a key is missing, or context is thin, instead of leaving the user guessing.

---

## Value Add (Assessment)

**Potential impact:** High for QA teams that already struggle with incomplete regression packs, weak change-impact clarity, and AI-generated tests that ignore real product flows.

| Dimension | Assessment |
|-----------|------------|
| **Time saved** | Cuts early draft time for security/negative/regression suites by grounding generation in actual flow paths + existing bugs instead of blank-prompt inventing. |
| **Quality uplift** | Critic → gap → targeted regen loop is the differentiator vs one-shot ChatGPT test lists; coverage moves where risk is highest. |
| **Change confidence** | Impact analysis on a changed node (e.g. Google OAuth) gives a concrete blast radius for regression planning. |
| **Traceability** | Evidence cards and agent traces support auditability — important for regulated or enterprise release processes. |
| **Adoption risk** | Low for pilot: works offline via deterministic fallback; teams can start with flow import + docs ingest without full platform rewrite. |
| **ROI (directional)** | For a mid-size product squad, even reclaiming a few hours per sprint on test design + gap finding, plus fewer escaped path/lockout/SSO-class defects, pays back tooling cost quickly. Biggest upside comes once output is consistently solid, costs are under control, and handing results to the team is frictionless. |

**Bottom line:** The idea is not “another AI that writes test cases.” It is **flow-aware, evidence-backed QA intelligence** with a self-improving coverage loop. That is a credible near-term productivity win for the team — once we iron out the prototype roughness and make day-to-day use feel reliable and cost-sensible.
