# Phase 2 — LLM-First Test Case Generation

**Status:** Implemented (deterministic baseline retained as fallback)  
**Date:** 2026-07-24

## New primary flow

```
Query
  → Hybrid Retrieval + ContextFusionLayer
  → TestCaseAgent.generate
       → if OpenAI available:
            build structured fused context
            LLM structured JSON generation (max 2 attempts, strict)
            Pydantic validate each TestCase
            on success → generation_method=llm
            on failure/empty/invalid → deterministic fallback
         else:
            deterministic graph-path generator
  → CriticAgent (unchanged)
  → QACopilotResponse.test_cases
```

## Fallback conditions

- `OPENAI_API_KEY` missing / client unavailable
- API exception / timeout (`strict=True` chat)
- Malformed JSON / missing `test_cases`
- Empty `test_cases`
- All items fail Pydantic validation or required-field checks

## Compatibility

- JSON graph store, Chroma/JSON vectors, retrieval planner, fusion: unchanged
- CriticAgent: unchanged
- API contract: additive optional `generation_method` on `TestCase`
- Baseline deterministic generator: preserved as `_generate_deterministic`
