# Agentic QA Copilot

Premium enterprise **Agentic QA Intelligence System** that combines:

- **User-provided system flow graphs** (first-class product context)
- **Vector RAG** (requirements, docs, QA knowledge)
- **Graph RAG** (features, flows, dependencies, tests, bugs, risks)
- **Specialized QA agents** + critic / self-review
- **Graph path–based test generation** and coverage gap analysis

This is not a simple chatbot. The system understands the software under test *before* generating QA artifacts.

---

## Quick start

### 1. Environment

```bash
cp .env.example .env
# Optional but recommended:
# OPENAI_API_KEY=sk-...
```

Without an OpenAI key the API runs in **deterministic demo fallback mode** (hash embeddings + heuristic agents) so the hackathon demo still works end-to-end.

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=.
uvicorn app.main:app --reload --port 8000
```

Seed the Sign In demo:

```bash
curl -X POST http://localhost:8000/api/demo/seed
```

### 3. Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 4. Docker (optional)

```bash
docker compose up --build
```

Neo4j is optional (`NEO4J_ENABLED=false` by default). The primary graph store is a durable JSON knowledge graph with optional Neo4j sync.

---

## Demo workflow

1. Click **Load demo** (Auth Platform Demo / Sign In).
2. Open **System Flow** — inspect the nested auth graph.
3. Open **QA Copilot** and run:

   > Generate comprehensive QA coverage for Sign In.

4. Review:
   - Agent execution trace
   - Path-linked test cases
   - Exploratory missions
   - Coverage gaps (with calculation notes)
   - Sources, confidence, assumptions
5. Try impact analysis:

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

## Tests

```bash
cd backend
PYTHONPATH=. pytest -q
```

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
| `NEO4J_ENABLED` | Optional Neo4j sync |
| `ENABLE_DEMO_FALLBACK` | Deterministic offline mode |
| `GRAPH_STORE_PATH` | Persistent graph JSON |
| `CHROMA_DIR` | Chroma persistence |

Never hardcode API keys.