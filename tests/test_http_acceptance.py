"""End-to-end HTTP acceptance tests run by the ``verify`` Compose service.

The tests target a live server given by ``EXACT_AREA_BASE_URL`` (e.g.
``http://api:8000`` inside Compose).  When the variable is not set the whole
module is skipped, so local ``pytest`` runs do not require a running server.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

BASE_URL = os.environ.get("EXACT_AREA_BASE_URL")

pytestmark = pytest.mark.skipif(
    BASE_URL is None,
    reason="EXACT_AREA_BASE_URL not set; live API acceptance tests skipped",
)


def _post(path: str, payload: dict):
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(path: str):
    with urllib.request.urlopen(BASE_URL.rstrip() + path, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def poly(exterior, holes=None):
    return {"exterior": exterior, "holes": holes or []}


def test_health_live():
    status, data = _get("/health")
    assert status == 200
    assert data == {"status": "ok"}


def test_fractional_overlap_live():
    payload = {
        "a": [poly([(0, 0), (3, 0), (0, 3)])],
        "b": [poly([(1, 1), (4, 1), (1, 4)])],
    }
    status, data = _post("/api/v1/overlap", payload)
    assert status == 200, data
    assert data["area_sq_mm"] == [1, 2]
    assert data["numerator"] == 1
    assert data["denominator"] == 2
    assert data["decimal"] == "0.500"
    assert data["rounding"] == "half-up"


def test_holes_and_edge_contact_live():
    payload = {
        "a": [poly([(0, 0), (4, 0), (4, 4), (0, 4)],
                   [[(1, 1), (3, 1), (3, 3), (1, 3)]])],
        "b": [poly([(0, 0), (4, 0), (4, 4), (0, 4)])],
    }
    status, data = _post("/api/v1/overlap", payload)
    assert status == 200
    assert data["area_sq_mm"] == [12, 1]
    assert data["decimal"] == "12.000"

    payload = {
        "a": [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
        "b": [poly([(1, 0), (2, 0), (2, 1), (1, 1)])],
    }
    status, data = _post("/api/v1/overlap", payload)
    assert status == 200
    assert data["area_sq_mm"] == [0, 1]
    assert data["decimal"] == "0.000"


def test_half_up_rounding_live():
    # A unit square and a long, thin triangle whose upper edge runs through
    # (0, 0) and (1000, 1) overlap in a wedge of area 1/2000 = 0.0005, which
    # rounds half-up to 0.001 (Python's built-in round() would not).
    payload = {
        "a": [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
        "b": [poly([(0, 0), (1000, 1), (0, -1)])],
    }
    status, data = _post("/api/v1/overlap", payload)
    assert status == 200, data
    assert data["area_sq_mm"] == [1, 2000]
    assert data["decimal"] == "0.001"


def test_invalid_geometry_is_structured_422_live():
    payload = {
        "a": [poly([(0, 0), (4, 4), (4, 0), (0, 4)])],  # bowtie
        "b": [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    }
    status, data = _post("/api/v1/overlap", payload)
    assert status == 422
    assert data["error"]["code"] == "invalid_geometry"
    assert isinstance(data["error"]["message"], str) and data["error"]["message"]
    assert "details" in data["error"]


def test_schema_violation_is_structured_422_live():
    status, data = _post("/api/v1/overlap", {"a": []})
    assert status == 422
    assert data["error"]["code"] == "invalid_request"
    assert data["error"]["details"]
