# Phase 5 — Hackathon Demo Polish

## Demo journey

1. Click **Load Demo Project** → Enterprise Authentication Portal
2. Inspect **System Flow** (Sign In + Email/OAuth/Microsoft Enterprise SSO/Self Registration)
3. Open **Knowledge Base** (requirements already seeded)
4. On **QA Copilot**, run the curated demo query
5. Review summary → coverage loop → evidence cards → Agent Trace

## Runtime diagnostics

`GET /api/health` (no secrets):

- `openai_configured` / `openai_client_ready`
- `vector_store_mode` (`chroma` | `json_fallback`)
- `graph_store_mode` (`json` | `neo4j+json`)
- `demo_fallback`

Copilot responses also include `generation_backend` and `runtime_diagnostics`.

## Demo seed

- Deterministic fixed IDs for tests/bugs
- Flow fingerprint skip on re-run (`graph_rewritten: false`)
- Content-hash document ingest
- Leaves Microsoft Enterprise SSO / SSO Timeout as high-risk uncovered for the coverage loop

## Docker

Default compose uses JSON graph store (`NEO4J_ENABLED=false`).
Optional Neo4j: `docker compose --profile neo4j up`.
