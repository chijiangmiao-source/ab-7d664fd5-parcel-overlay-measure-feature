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


# ---------------------------------------------------------------------------
# Transect endpoint acceptance
# ---------------------------------------------------------------------------


def test_transect_two_groups_cross_outer_ring_and_hole_live():
    payload = {
        "a": [poly([(0, 0), (4, 0), (4, 4), (0, 4)],
                   [[(1, 1), (3, 1), (3, 3), (1, 3)]])],
        "b": [poly([(2, 2), (6, 2), (6, 6), (2, 6)])],
        "path": [[-1, 2], [7, 2]],
    }
    status, data = _post("/api/v1/transect", payload)
    assert status == 200, data
    seg = data["segments"][0]
    assert [(iv["t0"], iv["t1"], iv["a"], iv["b"])
            for iv in seg["intervals"]] == [
        ([0, 1], [1, 8], "outside", "outside"),
        ([1, 8], [1, 4], "inside", "outside"),
        ([1, 4], [3, 8], "outside", "outside"),
        ([3, 8], [1, 2], "outside", "boundary"),
        ([1, 2], [5, 8], "inside", "boundary"),
        ([5, 8], [7, 8], "outside", "boundary"),
        ([7, 8], [1, 1], "outside", "outside"),
    ]
    # full [0, 1] coverage, gap-free
    assert seg["intervals"][0]["t0"] == [0, 1]
    assert seg["intervals"][-1]["t1"] == [1, 1]
    contact = seg["contacts"][0]
    assert contact["a"] == ["outside", "boundary", "inside"]


def test_transect_vertex_tangency_and_boundary_run_live():
    square = poly([(0, 0), (4, 0), (4, 4), (0, 4)])

    # Tangent at corner (0, 4): isolated contact, outside on both sides.
    status, data = _post(
        "/api/v1/transect",
        {"a": [square], "b": [], "path": [[-1, 3], [1, 5]]},
    )
    assert status == 200, data
    seg = data["segments"][0]
    assert [iv["a"] for iv in seg["intervals"]] == ["outside", "outside"]
    assert seg["contacts"][0]["t"] == [1, 2]
    assert seg["contacts"][0]["point"] == [0, 1, 4, 1]
    assert seg["contacts"][0]["a"] == ["outside", "boundary", "outside"]

    # Running along the bottom edge: a boundary interval, no contacts.
    status, data = _post(
        "/api/v1/transect",
        {"a": [square], "b": [], "path": [[-1, 0], [5, 0]]},
    )
    assert status == 200
    seg = data["segments"][0]
    assert [(iv["t0"], iv["t1"], iv["a"]) for iv in seg["intervals"]] == [
        ([0, 1], [1, 6], "outside"),
        ([1, 6], [5, 6], "boundary"),
        ([5, 6], [1, 1], "outside"),
    ]
    assert seg["contacts"] == []


def _complement(fr):
    from fractions import Fraction
    value = 1 - Fraction(fr[0], fr[1])
    return [value.numerator, value.denominator]


def test_transect_fractional_forward_and_reverse_live():
    square = poly([(0, 0), (4, 0), (4, 4), (0, 4)])
    # (-1,1) -> (5,3) crosses at fractional points (0,4/3) and (4,8/3).
    path = [[-1, 1], [5, 3]]
    status, fwd = _post(
        "/api/v1/transect", {"a": [square], "b": [], "path": path}
    )
    assert status == 200, fwd
    fseg = fwd["segments"][0]
    assert fseg["contacts"][0]["point"] == [0, 1, 4, 3]
    assert fseg["contacts"][1]["point"] == [4, 1, 8, 3]
    assert [iv["t0"] for iv in fseg["intervals"]] == [
        [0, 1], [1, 6], [5, 6]]
    for iv in fseg["intervals"]:
        for x in iv["t0"] + iv["t1"]:
            assert isinstance(x, int)

    # Reverse the whole polyline: events/intervals map one-to-one under t->1-t.
    status, rev = _post(
        "/api/v1/transect",
        {"a": [square], "b": [], "path": list(reversed(path))},
    )
    assert status == 200, rev
    rseg = rev["segments"][0]
    assert rseg["start"] == path[1] and rseg["end"] == path[0]
    for fiv, riv in zip(fseg["intervals"], reversed(rseg["intervals"])):
        assert riv["t0"] == _complement(fiv["t1"])
        assert riv["t1"] == _complement(fiv["t0"])
        assert (riv["a"], riv["b"]) == (fiv["a"], fiv["b"])
    for fc, rc in zip(fseg["contacts"], reversed(rseg["contacts"])):
        assert rc["t"] == _complement(fc["t"])
        assert rc["point"] == fc["point"]
        assert rc["a"] == [fc["a"][2], fc["a"][1], fc["a"][0]]


def test_transect_illegal_path_rejected_then_overlap_still_works_live():
    square = poly([(0, 0), (4, 0), (4, 4), (0, 4)])
    status, data = _post(
        "/api/v1/transect",
        {"a": [square], "b": [square], "path": [[0, 0], [1, 1], [1, 1]]},
    )
    assert status == 422
    assert data["error"]["code"] == "invalid_request"
    assert any(tuple(d["loc"])[:2] == ("body", "path")
               for d in data["error"]["details"])

    # The existing interface is unaffected after the rejected request.
    status, data = _post(
        "/api/v1/overlap",
        {"a": [poly([(0, 0), (3, 0), (0, 3)])],
         "b": [poly([(1, 1), (4, 1), (1, 4)])]},
    )
    assert status == 200
    assert data["area_sq_mm"] == [1, 2]
    assert data["decimal"] == "0.500"


def test_transect_bad_geometry_keeps_location_live():
    status, data = _post(
        "/api/v1/transect",
        {"a": [poly([(0, 0), (4, 4), (4, 0), (0, 4)])],  # bowtie
         "b": [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
         "path": [[-1, -1], [2, 2]]},
    )
    assert status == 422
    assert data["error"]["code"] == "invalid_geometry"
    assert data["error"]["details"][0]["loc"] == ["a", 0, "exterior"]
