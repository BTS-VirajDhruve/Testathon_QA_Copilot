# Phase 3 — Evidence, Explainability & Traceability

**Status:** Implemented  
**Date:** 2026-07-24

## Traceability model (additive)

`TestCase` fields (optional / backward compatible):

- `generation_method`: `llm` | `deterministic_fallback` | `critic`
- `reasoning`: short why-this-test explanation
- `evidence`: list of `EvidenceReference`
  - `source_type`, `source_id`, `source_title`, `relevance`
- Legacy `source_references: list[str]` still populated from evidence

## Source identity flow

Graph paths include `node_ids` + `path_id` in fusion → LLM catalog → sanitized evidence.  
Vector hits include chunk `id` / `document_id`.  
Existing tests / bugs keep `test_case_id` / `bug_id`.  
Fabricated LLM source IDs are dropped by `sanitize_evidence()`.
