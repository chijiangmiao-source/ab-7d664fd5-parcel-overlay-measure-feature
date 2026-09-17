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
from fractions import Fraction as Fr

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
# Transect
# ---------------------------------------------------------------------------

def test_transect_outer_and_hole_dual_groups_live():
    payload = {
        "a": [poly([(0, 0), (10, 0), (10, 10), (0, 10)],
                   [[(3, 3), (7, 3), (7, 7), (3, 7)]])],
        "b": [poly([(1, -1), (9, -1), (9, 11), (1, 11)])],
        "path": [(-2, 5), (12, 5)],
    }
    status, data = _post("/api/v1/transect", payload)
    assert status == 200, data
    segments = data["segments"]
    assert len(segments) == 1 and segments[0]["index"] == 0

    ranges = [i for i in segments[0]["intervals"] if i["type"] == "range"]
    points = [i for i in segments[0]["intervals"] if i["type"] == "point"]

    assert [(r["a"], r["b"]) for r in ranges] == [
        ("outside", "outside"),
        ("inside", "outside"),
        ("inside", "inside"),
        ("outside", "inside"),   # inside A's hole
        ("inside", "inside"),
        ("inside", "outside"),
        ("outside", "outside"),
    ]

    # Contact parameters measured from (-2,5): x = -2 + 14t.
    by_x = {tuple(p["t"]): p for p in points}
    for x, group, boundary, before, after in [
        (0, "a", "exterior", "outside", "inside"),
        (1, "b", "exterior", "outside", "inside"),
        (3, "a", "hole", "inside", "outside"),
        (7, "a", "hole", "outside", "inside"),
        (9, "b", "exterior", "inside", "outside"),
        (10, "a", "exterior", "inside", "outside"),
    ]:
        t_fr = Fr(x + 2, 14)
        point = by_x[(t_fr.numerator, t_fr.denominator)]
        (ev,) = point["events"]
        assert ev["group"] == group
        assert ev["before"] == before and ev["after"] == after
        assert ev["contacts"][0]["boundary"] == boundary

    # Full [0,1] coverage with no gaps.
    assert ranges[0]["start"] == [0, 1]
    assert ranges[-1]["end"] == [1, 1]


def test_transect_tangency_and_boundary_run_live():
    # Segment 1 horizontally kisses triangle apex (4,4): one isolated contact
    # with outside on both sides.  Segment 2 reaches the apex, and segment 3
    # then travels from the apex straight down the triangle edge to (2,0): a
    # whole segment collinear with the boundary.
    payload = {
        "a": [poly([(2, 0), (6, 0), (4, 4)])],
        "b": [poly([(20, 20), (21, 20), (21, 21), (20, 21)])],
        "path": [(0, 4), (8, 4), (4, 4), (2, 0)],
    }
    status, data = _post("/api/v1/transect", payload)
    assert status == 200, data
    s0, _s1, s2 = data["segments"]

    kiss = [i for i in s0["intervals"] if i["type"] == "point"]
    assert len(kiss) == 1 and kiss[0]["t"] == [1, 2]
    (ev,) = kiss[0]["events"]
    assert (ev["group"], ev["before"], ev["after"]) == (
        "a", "outside", "outside"
    )

    # The final segment lies entirely on a ring edge: contact points at both
    # ends surrounding one boundary range covering (0, 1).
    kinds = [(i["type"], i.get("t"), i.get("a")) for i in s2["intervals"]]
    assert kinds == [
        ("point", [0, 1], "boundary"),
        ("range", None, "boundary"),
        ("point", [1, 1], "boundary"),
    ]
    middle = s2["intervals"][1]
    assert middle["start"] == [0, 1] and middle["end"] == [1, 1]


def test_transect_fractional_intersections_reverse_live():
    payload_fwd = {
        "a": [poly([(0, 0), (4, 0), (0, 4)])],
        "b": [poly([(1, -4), (5, -4), (5, 4), (1, 4)])],
        "path": [(-2, 1), (5, 1)],
    }
    status, fwd = _post("/api/v1/transect", payload_fwd)
    assert status == 200, fwd
    payload_rev = dict(payload_fwd, path=list(reversed(payload_fwd["path"])))
    status, rev = _post("/api/v1/transect", payload_rev)
    assert status == 200, rev

    def mirror(segments):
        out = []
        for i, seg in enumerate(reversed(segments)):
            mirrored = []
            for item in reversed(seg["intervals"]):
                if item["type"] == "point":
                    t = 1 - Fr(*item["t"])
                    item = dict(
                        item, t=[t.numerator, t.denominator],
                        events=[
                            dict(e, before=e["after"], after=e["before"])
                            for e in item["events"]
                        ],
                    )
                else:
                    start = 1 - Fr(*item["end"])
                    end = 1 - Fr(*item["start"])
                    item = dict(
                        item,
                        start=[start.numerator, start.denominator],
                        end=[end.numerator, end.denominator],
                    )
                mirrored.append(item)
            out.append({"index": i, "intervals": mirrored})
        return out

    assert rev["segments"] == mirror(fwd["segments"])
    # A genuinely fractional intersection parameter survives serialization:
    # the line y=1 meets triangle edge x+y=4 at x=3, i.e. t = 5/7.
    assert any(
        item["type"] == "point" and item["t"] == [5, 7]
        for item in fwd["segments"][0]["intervals"]
    )


def test_transect_invalid_path_then_overlap_still_works_live():
    payload = {
        "a": [poly([(0, 0), (4, 0), (4, 4), (0, 4)])],
        "b": [poly([(0, 0), (4, 0), (4, 4), (0, 4)])],
        "path": [(0, 0), (1, 1), (1, 1), (2, 2)],
    }
    status, data = _post("/api/v1/transect", payload)
    assert status == 422
    assert data["error"]["code"] == "invalid_request"
    assert "vertex 2" in data["error"]["details"][0]["message"]

    status, data = _post(
        "/api/v1/overlap",
        {
            "a": [poly([(0, 0), (4, 0), (4, 4), (0, 4)])],
            "b": [poly([(2, 0), (6, 0), (6, 4), (2, 4)])],
        },
    )
    assert status == 200
    assert data["area_sq_mm"] == [8, 1]
