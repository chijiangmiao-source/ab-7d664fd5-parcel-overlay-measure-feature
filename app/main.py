"""FastAPI application: exact multi-polygon overlap area service."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .geometry.validation import GeometryValidationError
from .models import OverlapRequest, OverlapResponse, TransectRequest, TransectResponse
from .service import compute_overlap, compute_transect, round_half_up_thirds

app = FastAPI(
    title="Exact Multi-Polygon Overlap API",
    version="1.0.0",
    description=(
        "Computes the exact overlap area of two groups of multi-polygons using "
        "integer/rational arithmetic only. Coordinates are integer "
        "millimetres; the result is a reduced fraction and a half-up "
        "three-decimal value."
    ),
)


def _error_body(code: str, message: str,
                details: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


@app.exception_handler(GeometryValidationError)
async def geometry_validation_handler(request: Request,
                                      exc: GeometryValidationError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "invalid_geometry",
            exc.message,
            [{"loc": list(exc.loc)}] if exc.loc else None,
        ),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request,
                                     exc: RequestValidationError) -> JSONResponse:
    del request
    details: List[Dict[str, Any]] = []
    for err in exc.errors():
        details.append(
            {
                "loc": [str(part) for part in err.get("loc", [])],
                "type": err.get("type", "value_error"),
                "message": err.get("msg", ""),
            }
        )
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "invalid_request",
            "request payload does not satisfy the schema",
            details,
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request,
                                 exc: StarletteHTTPException) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body("http_error", str(exc.detail)),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request,
                                      exc: Exception) -> JSONResponse:
    # Last-resort guard: every response keeps the structured JSON envelope
    # instead of Starlette's plain-text 500.
    del request, exc
    return JSONResponse(
        status_code=500,
        content=_error_body(
            "internal_error", "an unexpected error occurred while computing the result"
        ),
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/overlap", response_model=OverlapResponse)
def overlap(req: OverlapRequest) -> OverlapResponse:
    # Synchronous CPU-bound work: FastAPI runs sync endpoints in a worker
    # thread, so a long exact-arithmetic computation never blocks the loop.
    area = compute_overlap(req.a, req.b)
    decimal = round_half_up_thirds(area)
    return OverlapResponse(
        area_sq_mm=[area.numerator, area.denominator],
        numerator=area.numerator,
        denominator=area.denominator,
        decimal=decimal,
    )


@app.post("/api/v1/transect", response_model=TransectResponse)
def transect(req: TransectRequest) -> TransectResponse:
    return compute_transect(req.a, req.b, req.path)
