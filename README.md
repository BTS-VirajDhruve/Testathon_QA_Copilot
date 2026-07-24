# Agentic QA Copilot

Premium enterprise **Agentic QA Intelligence System** that combines:

- **User-provided system flow graphs** (first-class product context)
- **Vector RAG** (requirements, docs, QA knowledge)
- **Graph RAG** (features, flows, dependencies, tests, bugs, risks)
- **Specialized QA agents** + critic / self-review
- **Graph path–based test generation** and coverage gap analysis

This is not a simple chatbot. The system understands the software under test *before* generating QA artifacts.

---

## Prerequisites

- **Python 3.11+** (3.12 recommended; see `backend/.python-version`)
- **[uv](https://docs.astral.sh/uv/)** for backend dependency management
- **Node.js 20+** and **npm** for the frontend

### Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart the terminal (or refresh `PATH`) so `uv` is available.

---

## Environment

From the repository root:

```bash
cp .env.example .env
# Optional but recommended:
# OPENAI_API_KEY=sk-...
```

You may also place `.env` inside `backend/` (settings load from the process working directory).

Without an OpenAI key the API runs in **deterministic demo fallback mode** so the hackathon demo still works end-to-end.

---

## Backend setup (uv — required)

**Working directory must be `backend/`.** Do not run `uvicorn` from the repo root, and do not rely on a globally installed `uvicorn`.

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or use the Makefile:

```bash
cd backend
make sync
make dev
```

### Why `uv run`?

`uvicorn: command not found` happens when the shell looks for a **global** `uvicorn` executable. This project installs uvicorn into the project virtualenv managed by uv. Always start the API with `uv run ...` so the correct environment is used.

`uv sync` also installs this package in editable mode, so `app.main:app` imports correctly without setting `PYTHONPATH`.

### Verify backend

- Health: [http://localhost:8000/api/health](http://localhost:8000/api/health)
- OpenAPI docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Seed the Sign In demo:

```bash
curl -X POST http://localhost:8000/api/demo/seed
```

### Backend tests

```bash
cd backend
uv sync --extra dev
uv run pytest -q
```

### Pip fallback (not preferred)

`requirements.txt` is kept in sync for Docker/legacy pip users, but **uv is the supported workflow**:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
uvicorn app.main:app --reload --port 8000
```

---

## Frontend setup

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Docker (optional)

```bash
# Fastest demo path (JSON graph store; Neo4j off)
docker compose up --build

# Optional Neo4j profile
NEO4J_ENABLED=true docker compose --profile neo4j up --build
```

Neo4j is optional (`NEO4J_ENABLED=false` by default). The primary graph store is a durable JSON knowledge graph with optional Neo4j sync.

---

## Demo workflow

1. Click **Load Demo Project** (Enterprise Authentication Portal / Sign In).
2. Inspect **System Flow** — Email + Password, Google OAuth, Microsoft Enterprise SSO, Self Registration.
3. Open **Knowledge Base** — requirements are already seeded (optional: add more notes).
4. On **QA Copilot**, run the curated query:

   > Analyze the Sign In flow. Generate comprehensive tests focused on security, negative scenarios, historical bugs, and uncovered branches. Then identify coverage gaps and generate targeted tests for the highest-risk gaps.

5. Review:
   - Context used (Graph RAG + Vector RAG)
   - Initial tests + evidence
   - Critic findings
   - Coverage before → targeted tests → coverage after
   - Agent execution trace
6. Try impact analysis:

   > What components are impacted if Google OAuth changes?

---

## Architecture

```
USER QUERY
  → Identify project / root feature
  → Load user flow graph
  → Classify intent
  → Retrieval planner
  → Traverse graph + Vector RAG + tests + bugs
  → Context fusion
  → Specialized agents (tests, exploratory, regression, impact, coverage)
  → Critic agent
  → Evidence-backed final response + execution trace
```

### Backend layout

| Path | Role |
|------|------|
| `app/models` | Pydantic schemas + enums (node types, relationships, provenance) |
| `app/graph` | Store, ingestion, traversal, coverage, entity extraction |
| `app/rag` | Document ingest, vector store, retrieval planner, context fusion |
| `app/agents` | Orchestrator + specialist agents |
| `app/services` | OpenAI wrapper with demo fallback |
| `app/api` | FastAPI routes |
| `seed/` | Sign In demo seed |

### Frontend layout

| Path | Role |
|------|------|
| System Flow Builder | React Flow visual editor, JSON import, NL→graph, undo/redo |
| Graph Explorer | Node insight: deps, flows, tests, bugs, risk, coverage |
| QA Copilot | Agentic query console + narrative output |
| Coverage / Trace / Evidence | Gap analysis, orchestrator steps, provenance |

---

## API highlights

- `GET /api/health` — health check
- `POST /api/projects` — create project (+ optional root feature)
- `PUT /api/projects/{id}/flow` — save visual system flow graph
- `POST /api/projects/{id}/flow/import` — nested JSON import
- `POST /api/projects/{id}/flow/from-text` — natural language → graph
- `POST /api/projects/{id}/documents/text` — ingest + embed
- `POST /api/copilot/query` — full agentic QA run
- `GET /api/projects/{id}/coverage` — explained graph coverage
- `GET /api/projects/{id}/impact?node=Google%20OAuth`
- `POST /api/demo/seed` — Sign In demo dataset

---

## Graph model

Canonical graph supports deep nesting and extensible node types:

`Project`, `UserJourney`, `Feature`, `SubFeature`, `UserFlow`, `AuthenticationMethod`, `Component`, `Service`, `API`, `FailurePath`, `AlternateFlow`, `State`, `TestCase`, `Bug`, `Risk`, …

Every node/edge carries provenance:

```json
{
  "source_type": "user_input|document|llm_inference|external_source",
  "source_reference": "...",
  "confidence": 0.0,
  "inferred": false
}
```

User-provided facts are never silently overwritten by inferred relationships.

---

## Design notes

UI direction: premium, enterprise, spacious, editorial — calm presentation of complex QA/graph data. Inspired by polished professional service sites (information architecture & typography only; no cloned assets/branding).

Color system: deep ink greens, mist surfaces, brass accents (not purple-gradient AI clichés).

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM + embeddings |
| `OPENAI_MODEL` | Chat model (default `gpt-4o-mini`) |
| `OPENAI_EMBEDDING_MODEL` | Embeddings model |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Optional Neo4j connection |
| `NEO4J_ENABLED` | Optional Neo4j sync (`false` by default) |
| `ENABLE_DEMO_FALLBACK` | Deterministic offline mode |
| `DATA_DIR` / `CHROMA_DIR` / `GRAPH_STORE_PATH` | Persistence paths (relative to `backend/`) |
| `CORS_ORIGINS` | Allowed frontend origins |

Never hardcode API keys.
