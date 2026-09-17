"""Endpoint-level tests for POST /api/v1/transect.

Covers the acceptance scenarios: two-group paths crossing outer rings and
holes, vertex tangencies and boundary runs, forward/reverse fractional paths,
the 422 rejection of illegal paths with precise locations, and continued
correct operation of the existing overlap endpoint.
"""

from __future__ import annotations

from fractions import Fraction


SQ4 = [[0, 0], [4, 0], [4, 4], [0, 4]]


def poly(exterior, holes=None):
    return {"exterior": exterior, "holes": holes or []}


def transect(client, a, b, path):
    return client.post(
        "/api/v1/transect", json={"a": a, "b": b, "path": path}
    )


def interval_pairs(seg):
    return [(iv["t0"], iv["t1"], iv["a"], iv["b"]) for iv in seg["intervals"]]


def test_health_unchanged(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_two_group_path_crosses_outer_ring_and_hole(client):
    a = [poly(SQ4, [[[1, 1], [3, 1], [3, 3], [1, 3]]])]
    b = [poly([[2, 2], [6, 2], [6, 6], [2, 6]])]
    resp = transect(client, a, b, [[-1, 2], [7, 2]])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["segments"]) == 1
    seg = data["segments"][0]
    assert seg["index"] == 0
    assert seg["start"] == [-1, 2]
    assert seg["end"] == [7, 2]
    assert interval_pairs(seg) == [
        ([0, 1], [1, 8], "outside", "outside"),
        ([1, 8], [1, 4], "inside", "outside"),
        ([1, 4], [3, 8], "outside", "outside"),
        ([3, 8], [1, 2], "outside", "boundary"),
        ([1, 2], [5, 8], "inside", "boundary"),
        ([5, 8], [7, 8], "outside", "boundary"),
        ([7, 8], [1, 1], "outside", "outside"),
    ]
    # fractions are emitted as [numerator, denominator], never decimals
    assert all(isinstance(x, int)
               for iv in seg["intervals"]
               for x in iv["t0"] + iv["t1"])


def test_intervals_cover_each_raw_segment_completely(client):
    a = [poly(SQ4)]
    path = [[-1, 1], [1, 1], [1, 5], [5, 5], [5, -1], [-1, -1]]
    resp = transect(client, a, [], path)
    assert resp.status_code == 200, resp.text
    segs = resp.json()["segments"]
    assert [s["index"] for s in segs] == list(range(len(path) - 1))
    for i, seg in enumerate(segs):
        assert seg["start"] == path[i]
        assert seg["end"] == path[i + 1]
        assert seg["intervals"][0]["t0"] == [0, 1]
        assert seg["intervals"][-1]["t1"] == [1, 1]
        prev = [0, 1]
        for iv in seg["intervals"]:
            assert iv["t0"] == prev
            prev = iv["t1"]
        assert prev == [1, 1]


def test_vertex_tangency_contact_has_before_middle_after(client):
    a = [poly(SQ4)]
    resp = transect(client, a, [], [[-1, 3], [1, 5]])
    seg = resp.json()["segments"][0]
    contact = seg["contacts"][0]
    assert contact["t"] == [1, 2]
    assert contact["point"] == [0, 1, 4, 1]
    assert contact["a"] == ["outside", "boundary", "outside"]
    assert contact["b"] == ["outside", "outside", "outside"]
    # the tangency splits the segment into two pieces, both outside
    assert [iv["a"] for iv in seg["intervals"]] == ["outside", "outside"]


def test_path_along_collinear_boundary_is_boundary_run(client):
    a = [poly(SQ4)]
    resp = transect(client, a, [], [[-1, 0], [5, 0]])
    seg = resp.json()["segments"][0]
    assert [(iv["t0"], iv["t1"], iv["a"]) for iv in seg["intervals"]] == [
        ([0, 1], [1, 6], "outside"),
        ([1, 6], [5, 6], "boundary"),
        ([5, 6], [1, 1], "outside"),
    ]
    assert seg["contacts"] == []
    assert [(e["t"], e["a"]) for e in seg["events"]] == [
        ([1, 6], "boundary"), ([5, 6], "boundary")]


def test_path_vertex_on_boundary_splits_events_with_null_side(client):
    a = [poly(SQ4)]
    resp = transect(client, a, [], [[-1, 3], [0, 4], [1, 3]])
    s0, s1 = resp.json()["segments"]
    assert s0["contacts"][-1]["a"] == ["outside", "boundary", None]
    assert s1["contacts"][0]["a"] == [None, "boundary", "inside"]
    assert s0["events"][-1]["t"] == [1, 1]
    assert s1["events"][0]["t"] == [0, 1]


def test_fractional_intersection_points_are_exact(client):
    a = [poly(SQ4)]
    resp = transect(client, a, [], [[-1, 1], [5, 3]])
    seg = resp.json()["segments"][0]
    assert seg["contacts"][0]["point"] == [0, 1, 4, 3]
    assert seg["contacts"][1]["point"] == [4, 1, 8, 3]
    # exact rational coordinates, never float values
    for c in seg["contacts"]:
        assert all(isinstance(x, int) for x in c["point"] + c["t"])


def _complement(fr):
    value = 1 - Fraction(fr[0], fr[1])
    return [value.numerator, value.denominator]


def _reverse_skeleton(data):
    """The response that reversing the whole polyline must reproduce."""
    out = []
    for seg in reversed(data["segments"]):
        out.append({
            "start": seg["end"],
            "end": seg["start"],
            "intervals": [
                {
                    "t0": _complement(iv["t1"]),
                    "t1": _complement(iv["t0"]),
                    "a": iv["a"],
                    "b": iv["b"],
                }
                for iv in reversed(seg["intervals"])
            ],
            "contacts": [
                {
                    "t": _complement(c["t"]),
                    "point": c["point"],
                    "a": [c["a"][2], c["a"][1], c["a"][0]],
                    "b": [c["b"][2], c["b"][1], c["b"][0]],
                }
                for c in reversed(seg["contacts"])
            ],
        })
    return out


def test_reversed_polyline_maps_one_to_one(client):
    a = [poly(SQ4, [[[1, 1], [3, 1], [3, 3], [1, 3]]])]
    b = [poly([[-2, -2], [6, -2], [6, 6], [-2, 6]])]
    path = [[-2, 5], [-1, 1], [5, 3], [6, 0], [0, -2]]
    fwd = transect(client, a, b, path).json()["segments"]
    rev = transect(client, a, b, list(reversed(path))).json()["segments"]
    expected = _reverse_skeleton({"segments": fwd})
    assert len(rev) == len(expected)
    for rseg, eseg in zip(rev, expected):
        assert rseg["start"] == eseg["start"]
        assert rseg["end"] == eseg["end"]
        assert rseg["intervals"] == eseg["intervals"]
        assert rseg["contacts"] == eseg["contacts"]


def test_consecutive_duplicate_path_point_is_422_at_position(client):
    a = [poly(SQ4)]
    resp = transect(client, a, a, [[0, 0], [1, 1], [1, 1], [2, 2]])
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "invalid_request"
    locs = [tuple(d["loc"]) for d in err["details"]]
    assert any(loc[:2] == ("body", "path") and loc[-1] == "2" for loc in locs)
    assert any("repeats point 1" in d["message"] for d in err["details"])


def test_too_few_path_points_is_422(client):
    for bad_path in ([[0, 0]], []):
        resp = transect(client, [poly(SQ4)], [poly(SQ4)], bad_path)
        assert resp.status_code == 422, bad_path
        assert resp.json()["error"]["code"] == "invalid_request"


def test_bad_path_coordinates_are_422(client):
    a = [poly(SQ4)]
    for bad in ([[0, 0], [1.5, 1]], [[0, 0], [True, 1]],
                [[0, 0], ["1", 1]], [[0, 0], [1_000_001, 0]],
                [[0, 0]], "x", None):
        resp = client.post(
            "/api/v1/transect", json={"a": a, "b": a, "path": bad}
        )
        assert resp.status_code == 422, bad
        assert resp.json()["error"]["code"] == "invalid_request"


def test_polygon_error_keeps_existing_location(client):
    bowtie = [[0, 0], [4, 4], [4, 0], [0, 4]]
    resp = transect(client, [poly(bowtie)], [poly(SQ4)], [[0, 0], [1, 1]])
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "invalid_geometry"
    assert err["details"][0]["loc"] == ["a", 0, "exterior"]


def test_invalid_path_does_not_affect_overlap_endpoint(client):
    # An illegal transect is rejected ...
    bad = transect(client, [poly(SQ4)], [poly(SQ4)], [[0, 0], [0, 0]])
    assert bad.status_code == 422
    # ... while the original overlap interface keeps computing unchanged.
    resp = client.post(
        "/api/v1/overlap",
        json={"a": [poly(SQ4, [[[1, 1], [3, 1], [3, 3], [1, 3]]])],
              "b": [poly(SQ4)]},
    )
    assert resp.status_code == 200
    assert resp.json()["area_sq_mm"] == [12, 1]
    assert resp.json()["decimal"] == "12.000"


def test_overlap_contract_unchanged_after_transect(client):
    resp = client.post(
        "/api/v1/overlap",
        json={"a": [poly([[0, 0], [3, 0], [0, 3]])],
              "b": [poly([[1, 1], [4, 1], [1, 4]])]},
    )
    data = resp.json()
    assert data == {
        "area_sq_mm": [1, 2],
        "numerator": 1,
        "denominator": 2,
        "decimal": "0.500",
        "rounding": "half-up",
        "units": "mm^2",
    }
