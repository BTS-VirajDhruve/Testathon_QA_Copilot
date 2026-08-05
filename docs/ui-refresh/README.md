# UI Refresh Coordination Contract

## Objective

Redesign and implement a professional, accessible, responsive light-and-dark

interface for the Agentic QA Copilot without changing product behavior,

backend contracts, RAG logic, project isolation, or persisted data.

## Agent ownership

### Agent 1 — Designer

May modify only:

- docs/ui-refresh/CURRENT_STATE_[AUDIT.md](http://AUDIT.md)

- docs/ui-refresh/DESIGN_[SYSTEM.md](http://SYSTEM.md)

- docs/ui-refresh/PAGE_[SPECIFICATIONS.md](http://SPECIFICATIONS.md)

- docs/ui-refresh/COMPONENT_[INVENTORY.md](http://INVENTORY.md)

- docs/ui-refresh/MOTION_[SPECIFICATION.md](http://SPECIFICATION.md)

- docs/ui-refresh/ACCESSIBILITY_[REQUIREMENTS.md](http://REQUIREMENTS.md)

- docs/ui-refresh/DECISION_[LOG.md](http://LOG.md)

- design reference assets under docs/ui-refresh/

Must not edit production application files.

### Agent 2 — Implementer

May modify:

- frontend production code

- frontend tests

- frontend documentation

- docs/ui-refresh/IMPLEMENTATION_[STATUS.md](http://STATUS.md)

Must follow the design artifacts.

Must not modify backend business logic or API contracts unless required for

an existing frontend contract and explicitly documented.

### Agent 3 — Reviewer

May modify:

- docs/ui-refresh/REVIEW_[FINDINGS.md](http://FINDINGS.md)

- docs/ui-refresh/DECISION_[LOG.md](http://LOG.md)

- focused test files

- narrowly scoped corrective frontend patches after recording the finding

Must not redesign the application independently.

## Severity levels

- BLOCKER: broken behavior, build failure, inaccessible critical flow,

  theme failure, data loss, or major mismatch with the specification.

- HIGH: significant visual, responsive, usability, or interaction defect.

- MEDIUM: local inconsistency or incomplete polish.

- LOW: optional improvement.

## Completion rules

Implementation is not complete until:

- no BLOCKER findings remain;

- no unresolved HIGH findings remain;

- frontend build succeeds;

- tests succeed;

- all main pages work in light and dark mode;

- keyboard navigation works;

- responsive layouts are verified;

- existing QA workflows remain functional.