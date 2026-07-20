from __future__ import annotations

import datetime

from fastapi import Request
from fastapi.responses import JSONResponse

from foundry.api.schemas import ApiError, ErrorEnvelope


class FoundryApiError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(FoundryApiError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(FoundryApiError):
    status_code = 409
    code = "CONFLICT"


class ValidationApiError(FoundryApiError):
    status_code = 400
    code = "VALIDATION_ERROR"


def validate_paging(offset: int, limit: int) -> None:
    if offset < 0:
        raise ValidationApiError(f"offset must be >= 0, got {offset}")
    if limit < 1:
        raise ValidationApiError(f"limit must be >= 1, got {limit}")
    if limit > 100:
        raise ValidationApiError(f"limit must be <= 100, got {limit}")


async def foundry_api_error_handler(request: Request, exc: FoundryApiError) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ApiError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
            path=str(request.url.path),
            details=exc.details,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=envelope.model_dump())
