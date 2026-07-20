# Architecture Decision Records (ADRs)

This directory captures architectural decisions for Foundry (software-foundary) along
with their context and consequences — for decisions made *after* the initial design
doc. The initial platform-wide decisions (backend stack, engine philosophy, process
model, store choice, playbook format, gate policy, KG, worktrees) are already recorded
in `docs/software-foundary-design.md` §13 ("Trade-off analysis") — don't duplicate
those here; only add an ADR when a *new* decision is made or an existing one is revised.

## ADR format

```markdown
# [Number]. [Title]

**Date:** YYYY-MM-DD
**Status:** [Proposed | Accepted | Rejected | Deprecated | Superseded by ADR-XXX]
**Topic:** [Category: Framework, Data model, Scalability, etc.]
**Scope:** [Which parts of the system this affects]

## Context and Problem Statement

[What led to this decision]

## Decision

[What was decided]

## Consequences

### Positive
- [Benefit]

### Negative
- [Trade-off]

## Alternatives Considered

### Alternative: [Name]
- Reason for rejection: [...]

## References
- [Link or doc reference]
```

## Index of ADRs

| # | Title | Date | Status | Topic |
|---|-------|------|--------|-------|
| [001](./001-api-response-structure.md) | REST API Response Structure & Query Parameters | 2026-07-20 | Accepted | API Standards |

## Lifecycle

- **Proposed:** decision is being considered
- **Accepted:** decision approved, will be/is implemented
- **Rejected:** considered but not adopted
- **Deprecated:** no longer valid
- **Superseded:** replaced by a newer ADR (link it)
