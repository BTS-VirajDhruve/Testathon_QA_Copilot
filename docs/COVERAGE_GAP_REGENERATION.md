# Phase 4 — Critic → Coverage Gap → Targeted Regeneration

## Flow

```
INITIAL RETRIEVAL
    → INITIAL TEST GENERATION (LLM-first + deterministic fallback)
    → CRITIC REVIEW (notes; path completeness)
    → COVERAGE GAP ANALYSIS (CoverageEngine + structured CoverageGap)
    → GAP PRIORITIZATION (deterministic; critical/high only)
    → TARGETED TEST GENERATION (TestCaseAgent.generate_for_gap)
    → DEDUPLICATION (title + steps + expected + graph_path)
    → FINAL COVERAGE ANALYSIS (before/after snapshots)
    → FINAL QA RESPONSE
```

## Bounds

- Default regeneration rounds: **1**
- Hard maximum: **2** (`QACopilotRequest.max_regeneration_rounds`, validated `le=2`)
- Only **critical/high** priority gaps are selected
- Default max gaps per round: **4**
- No automatic second critic→regen loop unless configured

## Key modules

| Module | Role |
|--------|------|
| `app/agents/coverage_gaps.py` | Structured gaps, prioritization, snapshots |
| `app/agents/dedup.py` | Semantic/deterministic test dedupe |
| `TestCaseAgent.generate_for_gap` | Targeted LLM/fallback generation |
| `CriticAgent.review(add_gap_tests=False)` | Orchestrator notes-only critic |
| `QAOrchestrator.run` | Bounded loop wiring |

## Response additions (compatible)

- `initial_test_cases`
- `selected_coverage_gaps`
- `targeted_test_cases`
- `coverage_before` / `coverage_after`
- `regeneration_rounds`
- `unresolved_gaps`

Targeted tests use `generation_method = "critic"` and set `closes_gap_id` / `closes_gap_title`.
