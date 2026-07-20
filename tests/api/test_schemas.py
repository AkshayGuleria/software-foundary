import pytest

from foundry.api.errors import ValidationApiError, validate_paging
from foundry.api.schemas import ApiResponse, Paging


def test_paging_none_is_all_null():
    p = Paging.none()
    assert p.offset is None
    assert p.limit is None
    assert p.total is None
    assert p.total_pages is None
    assert p.has_next is None
    assert p.has_prev is None


def test_paging_for_page_computes_total_pages_and_next_prev():
    p = Paging.for_page(offset=20, limit=20, total=43)
    assert p.total_pages == 3
    assert p.has_next is True
    assert p.has_prev is True

    first_page = Paging.for_page(offset=0, limit=20, total=43)
    assert first_page.has_prev is False

    last_page = Paging.for_page(offset=40, limit=20, total=43)
    assert last_page.has_next is False


def test_paging_unpaginated_fills_only_total():
    p = Paging.unpaginated(total=2)
    assert p.total == 2
    assert p.offset is None
    assert p.limit is None


def test_api_response_envelope_roundtrips():
    resp = ApiResponse[dict](data={"id": "01J..."}, paging=Paging.none())
    dumped = resp.model_dump()
    assert dumped["data"] == {"id": "01J..."}
    assert dumped["paging"]["offset"] is None


def test_validate_paging_rejects_limit_over_max():
    with pytest.raises(ValidationApiError):
        validate_paging(offset=0, limit=101)


def test_validate_paging_rejects_negative_offset():
    with pytest.raises(ValidationApiError):
        validate_paging(offset=-1, limit=20)


def test_validate_paging_accepts_defaults():
    validate_paging(offset=0, limit=20)  # must not raise
