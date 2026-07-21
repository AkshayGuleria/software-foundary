import datetime as dt

from foundry.kg.memory_retrieval import score_memory_item, select_relevant_memory
from foundry.store.models import Memory


def _item(title, body, created_offset=0):
    return Memory(
        id=f"m-{title}",
        scope="project",
        kind="lesson",
        title=title,
        body_md=body,
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(minutes=created_offset),
    )


def test_score_is_zero_for_disjoint_text():
    item = _item("budget pause", "token budgets pause dispatch")
    assert score_memory_item(item, "completely unrelated topic here") == 0.0


def test_score_is_higher_for_more_overlap():
    item_a = _item("budget pause", "token budgets pause dispatch never kill")
    item_b = _item("unrelated", "some other lesson entirely about drivers")
    query = "token budget pause dispatch"
    assert score_memory_item(item_a, query) > score_memory_item(item_b, query)


def test_select_relevant_memory_drops_zero_score_items():
    items = [_item("a", "token budget pause"), _item("b", "completely unrelated")]
    selected = select_relevant_memory(items, "token budget dispatch", k=5)
    assert [i.title for i in selected] == ["a"]


def test_select_relevant_memory_respects_k():
    items = [_item(f"item{i}", "token budget pause dispatch") for i in range(10)]
    selected = select_relevant_memory(items, "token budget pause dispatch", k=3)
    assert len(selected) == 3


def test_select_relevant_memory_respects_max_chars():
    items = [_item(f"item{i}", "token budget pause dispatch " * 50) for i in range(5)]
    selected = select_relevant_memory(items, "token budget pause dispatch", k=10, max_chars=200)
    total_chars = sum(len(i.body_md) for i in selected)
    # allows the item that crosses the boundary to be included whole
    assert total_chars <= 200 + len(items[0].body_md)
    assert len(selected) < 5


def test_select_relevant_memory_breaks_ties_by_newest():
    older = _item("older", "token budget pause", created_offset=0)
    newer = _item("newer", "token budget pause", created_offset=10)
    selected = select_relevant_memory([older, newer], "token budget pause", k=1)
    assert selected == [newer]
