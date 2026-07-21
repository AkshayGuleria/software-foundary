from foundry.api.scheduler import GlobalDispatchLimiter


def test_global_cap_blocks_dispatch_once_reached():
    limiter = GlobalDispatchLimiter(global_cap=2, per_project_cap=5)
    assert limiter.can_dispatch(project_id="p1") is True
    limiter.record_dispatch(project_id="p1")
    limiter.record_dispatch(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is False


def test_per_project_cap_blocks_before_global_cap():
    limiter = GlobalDispatchLimiter(global_cap=10, per_project_cap=1)
    limiter.record_dispatch(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is False
    assert limiter.can_dispatch(project_id="p2") is True  # other project unaffected


def test_release_frees_a_slot():
    limiter = GlobalDispatchLimiter(global_cap=1, per_project_cap=1)
    limiter.record_dispatch(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is False
    limiter.release(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is True
