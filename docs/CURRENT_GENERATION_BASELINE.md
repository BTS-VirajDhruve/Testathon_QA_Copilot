# Current Test Case Generation Baseline

**Status:** Locked regression baseline (deterministic fallback contract)  
**Date:** 2026-07-24  
**Update:** Phase 2 made LLM structured generation the **primary** path when OpenAI is available. This document still defines the **deterministic fallback** contract that must remain intact. See `docs/LLM_FIRST_GENERATION.md`.

**Original scope:** Document and lock heuristic generation behavior before LLM-first changes.

---

## 1. Entrypoints

| Layer | Location | Symbol |
|-------|----------|--------|
| HTTP API | `backend/app/api/routes.py` | `POST /api/copilot/query` → `copilot_query()` |
| Request / response models | `backend/app/models/schemas.py` | `QACopilotRequest`, `QACopilotResponse`, `TestCase` |
| Orchestrator | `backend/app/agents/orchestrator.py` | `QAOrchestrator.run()` |
| Test Case Agent | `backend/app/agents/specialists.py` | `TestCaseAgent.generate()` |
| Hybrid retrieval | `backend/app/rag/retrieval.py` | `RetrievalPlanner.plan()`, `ContextFusionLayer.fuse()` |

### When the Test Case Agent runs

`QAOrchestrator.run()` calls `TestCaseAgent.generate()` when intent is one of:

- `test_generation`
- `general_qa`
- `requirements_analysis`
- `regression` (if no cases generated yet)

After generation (when `include_critic=True` and cases exist), `CriticAgent.review()` may append coverage-gap-driven cases and notes.

---

## 2. Current input

### API request (`QACopilotRequest`)

```json
{
  "project_id": "<required>",
  "query": "<natural language QA request>",
  "root_feature": "<optional feature name>",
  "changed_node": "<optional; impact/regression>",
  "include_critic": true
}
```

### Agent method signature

```python
TestCaseAgent.generate(query: str, fused: FusedContext, project_id: str) -> list[TestCase]
```

Primary structural input is **`fused: FusedContext`**, not the raw query alone. The query is used mainly for:

1. Intent classification (orchestrator)
2. Retrieval planner decisions
3. Optional LLM enrichment prompt text

---

## 3. Current retrieval context (`FusedContext`)

Produced by `ContextFusionLayer.fuse()` after `RetrievalPlanner.plan()`.

| Field | Contents |
|-------|----------|
| `feature_context` | Root feature id/name/type/description/critical + direct branch names |
| `flow_paths` | Leaf graph paths as lists of node names from JSON graph DFS |
| `graph_context` | Path metadata (`is_failure_path`, `includes_external_dependency`, relationships) plus neighbor entity summaries |
| `semantic_context` | Vector search hits (Chroma or JSON cosine fallback), top_k=8 |
| `existing_coverage` | Existing project test cases from graph store (`test_case_id`, `title`, `graph_path`, `priority`) |
| `historical_risks` | Historical bugs for the project |
| `external_context` | Placeholder note only if planner sets `use_external_search` (no live search) |

### Retrieval plan flags (`RetrievalPlan`)

- `use_user_flow_graph`
- `use_vector_rag`
- `use_graph_rag`
- `use_existing_tests`
- `use_historical_bugs`
- `use_external_search` (flagged only; not executed)
- `reason`

**Graph source of truth today:** durable JSON graph store (`InMemoryGraphStore`). Neo4j is optional write-sync only and is **not** used for path discovery or fusion.

**Vector store today:** Chroma when available, else JSON embedding index. Not Qdrant.

---

## 4. Current generation flow

```
POST /api/copilot/query
  → QAOrchestrator.run
      → load project + user flow graph (JSON store)
      → resolve root feature
      → discover branches + graph paths
      → classify intent
      → RetrievalPlanner.plan
      → ContextFusionLayer.fuse  → (plan, FusedContext)
      → [optional] impact / coverage / risk
      → TestCaseAgent.generate(query, fused, project_id)
            1. Build one TestCase per fused.flow_paths entry (deterministic)
            2. If OpenAI available: append ≤3 LLM enrichment cases
            3. Persist cases into graph store.test_cases
      → [optional] CriticAgent.review (may add gap-driven cases)
      → QACopilotResponse (includes test_cases + execution_trace)
```

### Deterministic primary path (baseline)

For each path in `fused.flow_paths` (fallback: feature + branches):

1. Resolve failure/external flags from `graph_context` path metadata.
2. Build title via `_title_for` (`Graceful handling` / `Successful journey` / `Validate path`).
3. If title matches an existing coverage title → prefix `Verify existing coverage:`.
4. Derive category, priority (`_priority_for_path`), risk, technique (`_technique_for_path`).
5. Build preconditions, `test_data`, `steps`, `expected_result` from path tokens.
6. Attach `graph_path`, `graph_reasoning`, `source_references` (flow graph + optional vector hit + matching bugs).
7. Assign `TC-NNN` ids in discovery order.

This is the **primary** generator today.

### LLM enrichment (supplemental only)

Runs only when `OpenAIService.available` is true **and** at least one deterministic case exists:

- Asks for up to **3** additional cross-cutting security/session cases as JSON.
- Prompt includes query, feature, branches, and up to 5 historical risks — **not** the full fused semantic chunks or full path list.
- Appends cases with `source_references` including `"LLM reasoning"` and `confidence=medium`.
- Failures are logged and ignored (`testcase_llm_enrichment_failed`).

### Deterministic / offline fallback

When `OPENAI_API_KEY` is empty (or client init fails) and `ENABLE_DEMO_FALLBACK=true`:

- Embeddings: hash-based pseudo-vectors in `OpenAIService._hash_embed`
- Chat: heuristic JSON in `OpenAIService._demo_chat`
- **TestCaseAgent still generates from graph paths** without needing LLM

---

## 5. Current output schema (`TestCase`)

Defined in `backend/app/models/schemas.py`:

| Field | Type | Baseline notes |
|-------|------|----------------|
| `test_case_id` | str | `TC-001`, `TC-002`, … for agent output |
| `title` | str | Path-derived or LLM title |
| `category` | str | `functional` or `security` |
| `priority` | Priority | critical/high/medium/low |
| `risk` | RiskLevel | high for failure/external paths |
| `preconditions` | list[str] | Includes graph path string |
| `test_data` | dict | Path-token heuristics |
| `steps` | list[str] | Navigate + traverse each node + verify/fail |
| `expected_result` | str | Success or graceful failure wording |
| `testing_technique` | str | Keyword-mapped technique |
| `graph_path` | list[str] | Required in practice for path-based cases |
| `graph_reasoning` | str | Explains path coverage |
| `source_references` | list[str] | Always includes user flow graph for deterministic cases |
| `confidence` | ConfidenceLevel | high unless path metadata inferred |
| `assumptions` | list[str] | Fixed baseline assumptions |
| `project_id` | str \| None | Set by agent |
| `feature_id` | str \| None | From fused feature context |

API response wraps cases in `QACopilotResponse.test_cases`.

---

## 6. Current API endpoint

```
POST /api/copilot/query
Content-Type: application/json
```

**Body:** `QACopilotRequest`  
**Response:** `QACopilotResponse` (JSON), including:

- `test_cases`
- `retrieval_plan`
- `discovered_graph_paths`
- `execution_trace`
- `coverage` / `critic_notes` / `evidence` / `confidence` / `assumptions`

Related helpers (not the generation endpoint itself):

- `POST /api/demo/seed` — Sign In demo graph + docs + seeded tests/bugs
- `GET /api/projects/{id}/tests` — list persisted tests
- `GET /api/projects/{id}/paths` — path discovery only

---

## 7. Current test coverage

| Test | File | What it locks |
|------|------|----------------|
| `test_path_based_generation_and_coverage` | `backend/tests/test_core.py` | End-to-end copilot query: ≥8 cases, all with `graph_path`, retrieval uses user flow graph |
| `test_impact_and_regression` | `backend/tests/test_core.py` | Impact/regression path via same API |
| `test_retrieval_planner_uses_flow_graph` | `backend/tests/test_core.py` | Planner flags for test generation |
| `test_testcase_agent_deterministic_path_baseline` | `backend/tests/test_generation_baseline.py` | Unit-level: one case per path, no LLM when unavailable, schema fields, title/step conventions |
| `test_testcase_agent_marks_existing_coverage_titles` | `backend/tests/test_generation_baseline.py` | Existing-title prefix behavior |
| `test_copilot_query_baseline_schema_contract` | `backend/tests/test_generation_baseline.py` | API contract fields required for generation responses |

All baseline tests force `OPENAI_API_KEY=""` so LLM enrichment is off and behavior is deterministic.

---

## 8. Explicit non-goals of this baseline

This baseline intentionally does **not** change:

- JSON graph store as Graph RAG source of truth
- Chroma / JSON vector stack
- Neo4j role (optional sync only)
- Frontend design
- Product architecture / agent list

**Next change (out of scope here):** make fused-context LLM generation the primary Test Case Agent path, keeping this deterministic generator as fallback.

---

## 9. How to run baseline verification locally

```bash
cd backend
uv sync --extra dev
uv run pytest -q tests/test_core.py tests/test_generation_baseline.py
```

Or:

```bash
cd backend
uv run pytest -q
```
