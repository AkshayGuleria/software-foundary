# ADR-001: REST API Response Structure & Query Parameters

**Date:** 2026-07-20
**Status:** Accepted
**Topic:** API Standards
**Scope:** Public `/api` surface (dashboard, humans) — see design doc §7 for the full
endpoint list this formalizes. Does not apply to `/internal` (agent-facing, shared-secret
auth, RPC-style artifact/event submission — no list endpoints, no pagination concern).

---

## Context

Design doc §7 sketches the `/api` surface (`GET /api/runs`, `GET /api/runs/{id}/artifacts`,
`POST /api/gates/{id}/decide`, etc.) but doesn't pin down response shape, pagination, or
error format. M1 is the first milestone that implements `/api` (M0 is CLI + `FakeDriver`
only) — this needs to be settled before that work starts, not discovered endpoint by
endpoint.

Requirements:
1. Single resources (`GET /api/runs/{id}`) and collections (`GET /api/runs`) need one
   predictable envelope, not per-endpoint shapes.
2. Pagination must be simple and SQLite-friendly (`LIMIT x OFFSET y`) — this is a
   local-first, 1-user-to-small-team system (design doc §2.2: ≤10 concurrent sessions,
   5-50 projects), not a system that needs cursor pagination for scale.
3. List filtering as shown in the design doc is plain `?key=value` (`GET
   /api/runs?status=…`, `GET /api/runs/{id}/artifacts?latest=1`) — keep it that way;
   don't introduce operator-bracket query syntax (`field[gte]=…`) the design doc never
   asked for.
4. Errors need one shape so the dashboard's error handling isn't per-endpoint.

---

## Decision

Uniform response envelope with `data` + `paging` for every successful `/api` response;
one error shape for every failure. FastAPI response models via Pydantic v2 — the
envelope is a generic `ApiResponse[T]`, not hand-built per route.

### 1. Response structure

**All successful responses:**

```python
class Paging(BaseModel):
    offset: int | None
    limit: int | None
    total: int | None
    total_pages: int | None
    has_next: bool | None
    has_prev: bool | None

class ApiResponse(BaseModel, Generic[T]):
    data: T | list[T]
    paging: Paging
```

**Paginated list** (`GET /api/runs`):

```json
{
  "data": [
    {"id": "01J...", "playbook_ref": "sdlc_story.toml", "status": "active"},
    {"id": "01J...", "playbook_ref": "sdlc_story.toml", "status": "closed"}
  ],
  "paging": {"offset": 0, "limit": 20, "total": 43, "total_pages": 3, "has_next": true, "has_prev": false}
}
```

**Single resource** (`GET /api/runs/{id}`) — all paging fields `null`:

```json
{
  "data": {"id": "01J...", "playbook_ref": "sdlc_story.toml", "status": "active"},
  "paging": {"offset": null, "limit": null, "total": null, "total_pages": null, "has_next": null, "has_prev": null}
}
```

**Non-paginated collection** (e.g. `GET /api/runs/{id}/artifacts?latest=1` — bounded by
the run's own DAG, not independently paginated) — only `total` filled:

```json
{
  "data": [{"id": "01J...", "kind": "code_diff_artifact", "version": 2}],
  "paging": {"offset": null, "limit": null, "total": 1, "total_pages": null, "has_next": null, "has_prev": null}
}
```

**Error response:**

```json
{
  "error": {
    "code": "RUN_NOT_FOUND",
    "message": "Run 01J9Z... not found",
    "status_code": 404,
    "timestamp": "2026-07-20T14:03:00Z",
    "path": "/api/runs/01J9Z...",
    "details": null
  }
}
```

`code` is a short SCREAMING_SNAKE identifier stable across releases (dashboards can
switch on it); `message` is human-readable and may change.

### 2. Query parameters

Plain `?key=value`, matching design doc §7 exactly — no operator-bracket syntax:

```
GET /api/runs?status=active
GET /api/runs?status=active&project=foundry-web
GET /api/runs/{id}/artifacts?latest=1
GET /api/runs?offset=20&limit=20
```

One value per key = equality filter. Multi-value filters (e.g. "status in
[active, blocked]") aren't needed by any endpoint in §7 today — add `status=a,b` (CSV,
parsed to `IN (...)`) if and when a real endpoint needs it, not preemptively.

### 3. Pagination

- `offset`/`limit` query params. Default `offset=0`, `limit=20`. Max `limit=100`
  (reject above that with a 400, don't silently clamp — a silent clamp hides a caller
  bug behind a truncated result set).
- Maps directly to SQLAlchemy `.offset(x).limit(y)` on aiosqlite — no cursor complexity
  needed at this scale (design doc §2.2 NFRs).
- Always paginate the run-list-shaped endpoints (`GET /api/runs`, `GET /api/projects`,
  `GET /api/memory`). Never paginate a single-resource `GET .../{id}`. Nested,
  DAG-bounded collections (a run's artifacts, gates, events) are typically small
  enough to return whole — use the non-paginated shape (§1) unless a specific
  endpoint's collection can grow unbounded.

### 4. HTTP status codes

| Code | Usage | Body |
|------|-------|------|
| 200 | GET, PUT/PATCH, POST that doesn't create (e.g. `/gates/{id}/decide`) | `{data, paging}` |
| 201 | POST that creates (e.g. `POST /api/runs`) | `{data, paging}` for the created resource |
| 204 | Cancel/delete-shaped actions with no body to return | no body |
| 400 | Validation error (incl. `limit` over max) | `{error}` |
| 404 | Resource not found | `{error}` |
| 409 | Conflict (e.g. double-cancel, decide on an already-decided gate) | `{error}` |
| 500 | Server error | `{error}` |

### 5. SSE is a separate contract, not this envelope

`GET /api/stream[/{run_id}]` streams `event.*`-namespaced payloads per design doc §7's
event taxonomy, resumable via `Last-Event-ID` against `events.seq`. It does not use the
`ApiResponse` envelope — SSE frames are events, not REST responses. Contract rule from
§7 stands: events are facts, never commands.

---

## Consequences

### Positive

- One envelope, one error shape — the dashboard's HTTP client layer handles every
  endpoint the same way.
- `offset`/`limit` maps to SQLite directly; no query-parsing utility needed beyond
  FastAPI's own param binding.
- Matches design doc §7's query style exactly — no invented syntax to document or teach.
- Pydantic generics (`ApiResponse[T]`) mean the envelope is enforced by the type system,
  not hand-rolled per route.

### Negative

- `null`-filled paging on single resources is a few dozen bytes of overhead per
  response — negligible, accepted for consistency.
- Plain `?key=value` can't express `>`/`<`/date-range filters if a future endpoint needs
  them. **Mitigation:** cross that bridge with a dedicated ADR when a concrete endpoint
  needs it — don't build filter-operator machinery for a need that isn't in §7 yet.

---

## Alternatives considered

**Operator-bracket query syntax** (`status[eq]=active`, `createdAt[gte]=...`) — rejected
for now. Design doc §7 doesn't show any endpoint needing range/comparison filters; the
one filter shown (`?status=…`) is equality. Adding operator parsing ahead of a real need
is speculative complexity this project's own constraints page argues against (YAGNI).

**Page-based pagination** (`page=1&limit=20`) — rejected, same reasoning as offset/limit
being more SQL-direct; no meaningful difference at this project's scale either way, but
offset/limit needs no `(page-1)*limit` translation layer.

**Cursor-based pagination** — rejected as over-engineered for a local-first, single-user
to small-team system (design doc §2.2). Revisit only if/when the Postgres team-shared
deployment (M5) shows offset pagination becoming a real bottleneck.

---

## References

- Design doc §7 (API and event design) — the endpoint list this ADR formalizes
- Design doc §2.2 (Non-functional requirements) — the scale assumptions behind the
  pagination-strategy choice
