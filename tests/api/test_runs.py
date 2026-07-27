import subprocess

import pytest

from foundry.orchestrator.worktrees import _git_env
from foundry.store.models import WorkUnit, utcnow


def _init_git_repo(path):
    # Strip repo-scoped GIT_* env vars (GIT_DIR in particular) so `-C <path>`
    # is authoritative even when this test itself runs inside this repo's own
    # pre-commit hook, which sets GIT_DIR for its linked-worktree context.
    # See worktrees.py's _git_env() docstring for the real incident this
    # guards against.
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=_git_env())
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True, env=_git_env()
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True, env=_git_env())
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, env=_git_env())
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True, env=_git_env())


@pytest.mark.asyncio
async def test_create_run_materializes_and_registers_with_scheduler(api_client):
    client, store, scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "title": "my run",
        },
    )

    assert run_resp.status_code == 201, run_resp.text
    body = run_resp.json()["data"]
    assert body["title"] == "my run"
    assert body["status"] == "active"
    run_id = body["id"]

    assert run_id in scheduler._orchestrators
    units = await store.list_units(run_id)
    assert len(units) == 3  # plan, implement, review


@pytest.mark.asyncio
async def test_create_run_accepts_and_persists_a_driver_choice(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "driver": "codex",
        },
    )
    assert run_resp.status_code == 201, run_resp.text
    assert run_resp.json()["data"]["driver"] == "codex"


@pytest.mark.asyncio
async def test_create_run_with_bad_playbook_returns_400(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/fixtures/dangling_needs.toml",
            "title": "bad",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_run_for_missing_project_returns_404(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post(
        "/api/runs",
        json={
            "project_id": "does-not-exist",
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
        },
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_detail_shows_units_and_gates_with_cost_estimate(api_client):
    client, store, scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]
    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/playbook/fixtures/sdlc_mini.toml",
            "title": "plan-gated run",
        },
    )
    run_id = run_resp.json()["data"]["id"]

    # sdlc_mini: requirement -> (architecture, test_plan) -> plan_approval (derived
    # gate) -> implement. requirement/architecture/test_plan each carry their own
    # success-path "human" gate, and M1a gates stay pending until a human decides
    # (no auto-approve) — so drive the run forward by approving each human gate as
    # it appears, until plan_approval's derived gate materializes.
    for _ in range(3):
        await scheduler.tick_all_once()
        gates = await store.list_gates_for_run(run_id)
        pending_human = [g for g in gates if g.gate_type == "human" and g.decision == "pending"]
        for g in pending_human:
            await store.decide_gate(g.id, "approved", decided_by="test")
    await scheduler.tick_all_once()

    detail_resp = await client.get(f"/api/runs/{run_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.json()["data"]
    assert body["run"]["id"] == run_id
    # 5 step-level units (requirement, architecture, test_plan, plan_approval,
    # implement) + 1 session unit per dispatched task (requirement, architecture,
    # test_plan each ran once) = 8.
    assert len(body["units"]) == 8

    derived_gates = [g for g in body["gates"] if g["gate_type"] == "derived"]
    assert len(derived_gates) == 1
    assert derived_gates[0]["decision"] == "pending"
    assert derived_gates[0]["cost_estimate"]["estimated_writes_steps"] == 1

    # sdlc_mini has no fan-out, so units should carry convoy_id as a present
    # (non-missing) field, expected None.
    assert all("convoy_id" in u for u in body["units"])
    assert all(u["convoy_id"] is None for u in body["units"])


@pytest.mark.asyncio
async def test_list_runs_filters_by_project_and_status(api_client):
    client, _store, _scheduler = api_client

    proj1 = (await client.post("/api/projects", json={"name": "p1", "path": "/tmp/p1"})).json()["data"]["id"]
    proj2 = (await client.post("/api/projects", json={"name": "p2", "path": "/tmp/p2"})).json()["data"]["id"]
    await client.post(
        "/api/runs",
        json={"project_id": proj1, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )
    await client.post(
        "/api/runs",
        json={"project_id": proj2, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )

    resp = await client.get(f"/api/runs?project_id={proj1}")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


@pytest.mark.asyncio
async def test_get_run_graph_returns_units_and_deps(api_client):
    client, _store, _scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
        )
    ).json()["data"]["id"]

    resp = await client.get(f"/api/runs/{run_id}/graph")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["units"]) == 3
    assert len(body["deps"]) == 2  # implement needs plan, review needs implement


@pytest.mark.asyncio
async def test_get_run_artifacts_latest_only_returns_max_version(api_client):
    client, store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/gated_demo.toml"},
        )
    ).json()["data"]["id"]

    for _ in range(5):
        await scheduler.tick_all_once()

    gates = await store.list_gates_for_run(run_id)
    await store.decide_gate(gates[0].id, "rejected", decided_by="test")
    for _ in range(5):
        await scheduler.tick_all_once()
    gates = await store.list_gates_for_run(run_id)
    pending = [g for g in gates if g.decision == "pending"]
    if pending:
        await store.decide_gate(pending[0].id, "approved", decided_by="test")
        for _ in range(5):
            await scheduler.tick_all_once()

    resp = await client.get(f"/api/runs/{run_id}/artifacts?latest=1")
    assert resp.status_code == 200
    a_artifacts = [a for a in resp.json()["data"] if a["kind"] == "a_artifact"]
    assert len(a_artifacts) == 1
    assert a_artifacts[0]["version"] == 2


@pytest.mark.asyncio
async def test_cancel_run_flips_non_terminal_units_and_stops_scheduling(api_client):
    client, store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/gated_demo.toml"},
        )
    ).json()["data"]["id"]

    for _ in range(5):
        await scheduler.tick_all_once()

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 204

    units = await store.list_units(run_id)
    assert all(u.status in ("closed", "failed", "killed") for u in units)

    run_row = await store.get_run(run_id)
    assert run_row.status == "cancelled"
    assert run_id not in scheduler._orchestrators


@pytest.mark.asyncio
async def test_double_cancel_returns_409(api_client):
    client, _store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
        )
    ).json()["data"]["id"]

    first = await client.post(f"/api/runs/{run_id}/cancel")
    assert first.status_code == 204

    second = await client.post(f"/api/runs/{run_id}/cancel")
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_cancel_missing_run_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/runs/does-not-exist/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_run_pins_pack_version_when_playbook_is_pack_content(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", ".")
    resp = await client.post(
        "/api/runs",
        json={"project_id": project.id, "playbook_path": "packs/default/playbooks/sdlc_story.toml"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["pack_version_pin"] == "default@0.1.0"


@pytest.mark.asyncio
async def test_create_run_with_gate_overrides_persists_and_applies_them(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo2", ".")
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": project.id,
            "playbook_path": "packs/default/playbooks/bugfix.toml",
            "gate_overrides": {"diagnose": "approved"},
        },
    )
    assert resp.status_code == 201
    run_id = resp.json()["data"]["id"]
    run_row = await store.get_run(run_id)
    assert run_row.gate_overrides_json == {"diagnose": "approved"}


@pytest.mark.asyncio
async def test_create_run_with_invalid_gate_override_value_returns_400(api_client):
    # apply_gate_decisions only recognizes "approved"/"rejected" -- any other
    # string would silently leave the unit blocked forever with no error, so
    # the request boundary must reject bad values instead of accepting them.
    client, store, _scheduler = api_client
    project = await store.create_project("demo3", ".")
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": project.id,
            "playbook_path": "packs/default/playbooks/bugfix.toml",
            "gate_overrides": {"diagnose": "maybe"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_run_out_exposes_gate_overrides_and_token_fields(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", ".")
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": project.id,
            "playbook_path": "packs/default/playbooks/bugfix.toml",
            "gate_overrides": {"diagnose": "approved"},
        },
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["gate_overrides"] == {"diagnose": "approved"}
    assert body["token_budget"] == 0
    assert body["tokens_used"] == 0


@pytest.mark.asyncio
async def test_create_run_wires_a_real_worktree_manager(api_client, tmp_path):
    client, _store, scheduler = api_client
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": str(repo)})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={"project_id": project_id, "playbook_path": "tests/fixtures/writes_demo.toml"},
    )
    assert run_resp.status_code == 201, run_resp.text
    run_id = run_resp.json()["data"]["id"]

    orchestrator = scheduler._orchestrators[run_id]
    assert orchestrator.worktree_manager is not None


@pytest.mark.asyncio
async def test_create_run_applies_project_default_token_budget(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "budgetproj", "path": "/tmp/budgetproj"})
    project_id = proj_resp.json()["data"]["id"]
    await client.patch(f"/api/projects/{project_id}/settings", json={"token_budget": 30000})

    run_resp = await client.post(
        "/api/runs",
        json={"project_id": project_id, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )
    assert run_resp.status_code == 201, run_resp.text
    assert run_resp.json()["data"]["token_budget"] == 30000


@pytest.mark.asyncio
async def test_create_run_explicit_token_budget_overrides_project_default(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "budgetproj2", "path": "/tmp/budgetproj2"})
    project_id = proj_resp.json()["data"]["id"]
    await client.patch(f"/api/projects/{project_id}/settings", json={"token_budget": 30000})

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "token_budget": 5000,
        },
    )
    assert run_resp.status_code == 201, run_resp.text
    assert run_resp.json()["data"]["token_budget"] == 5000


@pytest.mark.asyncio
async def test_get_run_sessions_returns_all_sessions_for_the_run(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("proj", "/tmp/proj")
    run = await store.create_run(project.id, "pb.toml", "session route test")
    session_unit = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="implement", type="session", status="running")]
        )
    )[0]
    # SessionRow's own primary key is always set equal to its owning
    # session-type WorkUnit's id -- see Orchestrator.dispatch()'s real
    # create_session_row(id=session_unit.id, work_unit_id=session_unit.id, ...)
    # call in src/foundry/orchestrator/tick.py; this test fixture matches
    # that real convention rather than inventing its own.
    await store.create_session_row(
        id=session_unit.id,
        work_unit_id=session_unit.id,
        driver="fake",
        status="running",
        model="m1",
        tokens_in=10,
        tokens_out=20,
    )

    resp = await client.get(f"/api/runs/{run.id}/sessions")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body) == 1
    assert body[0]["id"] == session_unit.id
    assert body[0]["work_unit_id"] == session_unit.id
    assert body[0]["step_id"] == "implement"
    assert body[0]["run_id"] == run.id


@pytest.mark.asyncio
async def test_get_run_sessions_includes_closed_sessions_with_ended_at(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("proj2", "/tmp/proj2")
    run = await store.create_run(project.id, "pb.toml", "closed session test")
    session_unit = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="implement", type="session", status="closed")]
        )
    )[0]

    await store.create_session_row(
        id=session_unit.id,
        work_unit_id=session_unit.id,
        driver="fake",
        status="closed",
        started_at=utcnow(),
        ended_at=utcnow(),
    )

    resp = await client.get(f"/api/runs/{run.id}/sessions")

    body = resp.json()["data"]
    assert len(body) == 1
    assert body[0]["ended_at"] is not None


@pytest.mark.asyncio
async def test_get_run_sessions_404s_for_an_unknown_run(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/runs/nonexistent/sessions")

    assert resp.status_code == 404
