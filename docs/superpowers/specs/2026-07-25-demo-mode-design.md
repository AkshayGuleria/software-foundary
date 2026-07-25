# Demo mode — design

## Goal

A one-command way to populate a throwaway SQLite database with realistic,
varied fake data — multiple projects at different lifecycle stages, runs in
different states (active, closed, cancelled), gates in every decision state,
artifacts, memory items, and a real on-disk knowledge graph — so a new
visitor can run `foundry serve` against it and see every dashboard view
populated meaningfully, without spending tokens or needing a real driver.

## Why this needs its own design (not just a fixture)

This is a different job from the existing test fixtures under `tests/`:
those exist to exercise specific engine behaviors in isolation (one playbook,
one scenario, torn down per test). Demo mode needs *breadth* — a believable
slice of a working deployment, all at once, that stays up and browsable.

## Scope

**In scope:**
- A `foundry demo-seed` CLI command that populates a fresh SQLite db.
- 4-5 fake projects spanning every `Project.status` value the dashboard
  renders differently (`active`, `paused`, `archived`).
- Per project, 2-4 runs spanning every state the dashboard distinguishes:
  `active` with a pending human gate, `active` with a pending agent-review
  gate, `closed` (successful), `closed` with a rejection→rework cycle in its
  history, `cancelled`.
- Real artifacts, gates (all three `gate_type`s, all three `decision`s),
  events, and sessions backing those runs — not just header rows — so
  `RunDetailPage`'s ribbon/DAG/gates/feed panels all have real content, and
  `MetricsPage`'s rework-rate/approval-latency/retry/crash columns are
  non-zero and varied across projects (the entire point of a *comparison*
  view is worthless if every row is identical).
- Real memory items (a few `lesson`/`pattern`/`pitfall` entries per project)
  so `MemoryBrowser` has content.
- A **real on-disk toy Python package** per demo project (10-20 files with
  genuine import relationships), because `GET /api/projects/{id}/kg-graph`
  and `GET /api/runs/{id}/blast-radius` call `build_kg(project.path)` live
  against the filesystem (`src/foundry/api/routes/knowledge.py:26,53`) — a
  demo project whose `path` points nowhere, or to an empty directory, would
  render an empty Knowledge view no matter how much fake DB data exists.
  This is not optional set-dressing; it's a hard dependency of the feature
  actually working.
- A `foundry demo-seed --reset` flag (or equivalent) to wipe and re-seed
  idempotently, since running the command twice on the same db file should
  not double every row.

**Out of scope:**
- Not a replacement for pytest fixtures — existing `tests/fixtures/` and
  `tests/*/fixtures/` stay exactly as they are, untouched.
- Not wired to any real driver — demo data is either directly inserted via
  `Store` methods or produced by running real playbooks through the
  orchestrator on `FakeDriver` (open question below), never `CodexDriver`/
  `ClaudeCodeDriver`. No tokens, no network calls, ever.
- No auth/multi-tenant concerns — out of scope for the whole codebase until
  M5, demo mode doesn't change that.
- Not a perpetual background data generator (no cron, no continuously
  "live" demo) — one seed, static afterward, matches how every other
  Foundry deployment behaves today.

## Two open design questions worth resolving before a plan gets written

**1. How is the data produced — direct `Store` writes, or real orchestrator runs on `FakeDriver`?**

- *Direct writes* (construct `Project`/`Run`/`WorkUnit`/`Gate`/`Artifact`/
  `Event` rows straight through `Store` methods, no `Orchestrator` involved):
  fast, fully deterministic, easy to hit every state combination
  deliberately (e.g. "a rejected-then-approved gate" is just two rows).
  Risk: the data can silently drift out of sync with what the real engine
  actually produces (a field the orchestrator always sets that the seed
  script forgets), and it never exercises the real tick loop, so it proves
  nothing about the engine — only about the dashboard's rendering.
- *Real runs* (materialize real playbooks — reuse `packs/default/`'s
  `sdlc_story.toml`/`bugfix.toml` — through a real `Orchestrator` on
  `FakeDriver`, scripted to reject-then-approve on some runs): the data is
  guaranteed structurally valid by construction, and doubles as a live
  smoke test that the engine still produces sensible output. Slower, and
  getting a *cancelled* run or a *paused* project still needs some direct
  `Store` calls layered on top (those aren't reachable by just running a
  playbook to completion).
- **Recommendation:** hybrid — drive the bulk of run/gate/artifact data
  through real `Orchestrator.run_to_completion()` calls on `FakeDriver`
  (reusing the default pack's playbooks, scripting different `FakeStepScript`
  outcomes per run to get the state variety), then apply direct `Store`
  writes only for the states unreachable by construction (project
  pause/archive, run cancellation, backdated `created_at` timestamps so the
  changelog/metrics don't all cluster at the exact seed moment). This keeps
  the "proves the engine still works" property for the common path while
  not fighting the orchestrator to force states it doesn't naturally reach.

**2. Where does the demo command live, and where does the toy on-disk repo come from?**

- CLI: a new `foundry demo-seed` Typer command in `src/foundry/cli.py`
  (matching the existing `run`/`events`/`serve`/`archive-events` commands)
  vs. a standalone `scripts/seed_demo.py` outside the package. Recommend the
  CLI command — it's the pattern every other "do a thing to a db" operation
  in this codebase already follows, and it means `pip install`/`uv run
  foundry demo-seed` just works with no separate script to discover.
- Toy repo: generate a small synthetic Python package on the fly into a
  temp/fixed directory (e.g. `.foundry-demo/toy-repo-N/`) each time
  `demo-seed` runs, rather than committing a static fake codebase into this
  repo. Generating it keeps the demo data self-contained (no risk of the
  toy repo drifting from whatever DB rows reference it) and avoids adding
  unrelated Python files to `software-foundary`'s own source tree that a
  future contributor might mistake for real code.

## Non-functional constraints carried over from the rest of the codebase

- Must not touch a real/default `foundry.db` by accident — `demo-seed`
  should require an explicit `--db` path (or default to something obviously
  demo-named like `demo.db`, never silently reuse whatever `foundry.db`
  already contains real data in).
- No new dependencies.
- Runs entirely offline, same as every existing test in this suite.

## What I did not design here

Exact seed data (which project names, how many of each state, exact fake
lesson/pitfall text) and the toy repo's generated file/import structure are
implementation-plan-level detail, not spec-level — the plan should pick
concrete numbers once the two questions above are settled.
