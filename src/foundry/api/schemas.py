from __future__ import annotations

from pydantic import BaseModel


class Paging(BaseModel):
    offset: int | None = None
    limit: int | None = None
    total: int | None = None
    total_pages: int | None = None
    has_next: bool | None = None
    has_prev: bool | None = None

    @classmethod
    def none(cls) -> Paging:
        return cls()

    @classmethod
    def for_page(cls, offset: int, limit: int, total: int) -> Paging:
        total_pages = (total + limit - 1) // limit if limit else 0
        return cls(
            offset=offset,
            limit=limit,
            total=total,
            total_pages=total_pages,
            has_next=(offset + limit) < total,
            has_prev=offset > 0,
        )

    @classmethod
    def unpaginated(cls, total: int) -> Paging:
        return cls(total=total)


class ApiResponse[T](BaseModel):
    data: T
    paging: Paging


class ApiError(BaseModel):
    code: str
    message: str
    status_code: int
    timestamp: str
    path: str
    details: dict | None = None


class ErrorEnvelope(BaseModel):
    error: ApiError
