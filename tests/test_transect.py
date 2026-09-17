"""Endpoint tests for POST /api/v1/transect (exact crossing profiles)."""

from __future__ import annotations

from fractions import Fraction

import pytest


def poly(exterior, holes=None):
    return {"exterior": exterior, "holes": holes or []}


SQ10 = [(0, 0), (10, 0), (10, 10), (0, 10)]
HOLE4 = [(3, 3), (7, 3), (7, 7), (3, 7)]


def post(client, path, a, b):
    return client.post("/api/v1/transect", json={"a": a, "b": b, "path": path})


def frac(pair):
    return Fraction(pair[0], pair[1])


def items(client, path, a, b, status=200):
    resp = post(client, path, a, b)
    assert resp.status_code == status, resp.text
    return resp.json()["segments"]


# ---------------------------------------------------------------------------
# Structural invariants shared by every successful response
# ---------------------------------------------------------------------------

def assert_covers_unit_interval(segments):
    """Intervals cover [0,1] of every original segment with no gaps/overlap."""
    assert [s["index"] for s in segments] == list(range(len(segments)))
    for seg in segments:
        iv = seg["intervals"]
        assert iv, "every segment has at least one interval"
        first, last = iv[0], iv[-1]
        assert frac(first.get("start", first.get("t"))) == 0
        assert frac(last.get("end", last.get("t"))) == 1

        cursor = Fraction(0)
        seen_points = set()
        for item in iv:
            if item["type"] == "point":
                t = frac(item["t"])
                # Strictly increasing parameters; zero-length points sit at the
                # boundary between two positive-length ranges.
                assert t >= cursor
                assert t not in seen_points
                seen_points.add(t)
                cursor = t
            else:
                start, end = frac(item["start"]), frac(item["end"])
                assert start == cursor
                assert end > start
                cursor = end
        assert cursor == 1


def assert_reduced_fractions(segments):
    for seg in segments:
        for item in seg["intervals"]:
            pairs = [item.get("t"), item.get("start"), item.get("end")]
            for pair in pairs:
                if pair is None:
                    continue
                v = Fraction(pair[0], pair[1])
                assert [v.numerator, v.denominator] == pair
                assert v.denominator > 0


def range_items(seg):
    return [i for i in seg["intervals"] if i["type"] == "range"]


def point_items(seg):
    return [i for i in seg["intervals"] if i["type"] == "point"]


# ---------------------------------------------------------------------------
# Crossing profiles
# ---------------------------------------------------------------------------

def test_path_through_outer_and_hole_both_groups(client):
    # Group A: 10x10 square with a central 4x4 hole.
    # Group B: vertical strip x in [1, 9].
    # Horizontal path y=5 crosses: A exterior, B exterior, A hole (twice), ...
    a = [poly(SQ10, [HOLE4])]
    b = [poly([(1, -1), (9, -1), (9, 11), (1, 11)])]
    segments = items(client, [(-2, 5), (12, 5)], a, b)
    assert len(segments) == 1
    seg = segments[0]
    assert_covers_unit_interval(segments)
    assert_reduced_fractions(segments)

    rng = range_items(seg)
    pts = point_items(seg)

    # Open pieces, in order, as (a, b) material relations.
    assert [(r["a"], r["b"]) for r in rng] == [
        ("outside", "outside"),  # x < 0
        ("inside", "outside"),   # 0 < x < 1
        ("inside", "inside"),    # 1 < x < 3
        ("outside", "inside"),   # 3 < x < 7  (inside the hole)
        ("inside", "inside"),    # 7 < x < 9
        ("inside", "outside"),   # 9 < x < 10
        ("outside", "outside"),  # x > 10
    ]

    # Contact parameters measured from (-2,5): x = -2 + 14t.
    contacts = {frac(p["t"]): p for p in pts}
    t_at = {x: Fraction(x + 2, 14) for x in (0, 1, 3, 7, 9, 10)}
    assert set(contacts) == set(t_at.values())

    at0 = contacts[t_at[0]]
    assert at0["a"] == "boundary" and at0["b"] == "outside"
    (ev,) = at0["events"]
    assert ev["group"] == "a"
    assert (ev["before"], ev["after"]) == ("outside", "inside")
    assert ev["contacts"] == [
        {"polygon": 0, "boundary": "exterior", "hole_index": None}
    ]

    # Entering the hole: inside material -> outside material, hole tagged.
    at3 = contacts[t_at[3]]
    assert at3["a"] == "boundary"
    (ev,) = at3["events"]
    assert (ev["group"], ev["before"], ev["after"]) == ("a", "inside", "outside")
    assert ev["contacts"] == [
        {"polygon": 0, "boundary": "hole", "hole_index": 0}
    ]

    # Leaving the hole again at x=7.
    at7 = contacts[t_at[7]]
    (ev,) = at7["events"]
    assert (ev["before"], ev["after"]) == ("outside", "inside")
    assert ev["contacts"][0]["boundary"] == "hole"

    # B events at x=1 and x=9.
    assert [e["group"] for e in contacts[t_at[1]]["events"]] == ["b"]
    assert [e["group"] for e in contacts[t_at[9]]["events"]] == ["b"]


def test_vertex_tangency_is_isolated_contact(client):
    # Triangle apex (4,4); the horizontal path kisses exactly that vertex
    # without entering the interior, on either side.
    a = [poly([(2, 0), (6, 0), (4, 4)])]
    b = [poly([(20, 20), (21, 20), (21, 21), (20, 21)])]
    seg = items(client, [(0, 4), (8, 4)], a, b)[0]
    assert_covers_unit_interval([seg])

    rng = range_items(seg)
    pts = point_items(seg)
    assert len(pts) == 1
    kiss = pts[0]
    assert frac(kiss["t"]) == Fraction(1, 2)
    assert kiss["a"] == "boundary" and kiss["b"] == "outside"
    (ev,) = kiss["events"]
    assert ev["group"] == "a"
    assert (ev["before"], ev["after"]) == ("outside", "outside")
    assert ev["contacts"][0] == {
        "polygon": 0, "boundary": "exterior", "hole_index": None
    }
    # Both open pieces remain outside.
    assert all(r["a"] == "outside" and r["b"] == "outside" for r in rng)


def test_path_running_along_boundary(client):
    # From (-2,0) along the bottom edge of the [0,4] square to (2,0), then
    # inward at x=2 up to (2,4).
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    b = [poly([(20, 20), (21, 20), (21, 21), (20, 21)])]
    segments = items(client, [(-2, 0), (2, 0), (2, 4)], a, b)
    assert_covers_unit_interval(segments)

    s0, s1 = segments
    # First segment: outside piece, contact at t=1/2 (x=0), then a positive
    # boundary piece along the edge up to the fold vertex.
    r0 = range_items(s0)
    assert r0[0]["a"] == "outside"
    assert r0[-1]["a"] == "boundary"
    assert frac(point_items(s0)[0]["t"]) == Fraction(1, 2)
    enter = point_items(s0)[0]
    (ev,) = enter["events"]
    assert (ev["before"], ev["after"]) == ("outside", "boundary")

    # Second segment travels through the interior; its start is the fold
    # vertex on the boundary, after which the line is inside.
    fold = point_items(s1)[0]
    assert frac(fold["t"]) == 0
    (ev,) = fold["events"]
    assert (ev["before"], ev["after"]) == ("boundary", "inside")
    assert range_items(s1)[-1]["a"] == "inside"
    assert point_items(s1)[-1]["a"] == "boundary"  # ends on the top edge


def test_fractional_intersections_forward_and_reverse(client):
    # Slanted path crosses triangle edges at non-integer parameters.
    a = [poly([(0, 0), (4, 0), (0, 4)])]
    b = [poly([(1, -4), (5, -4), (5, 4), (1, 4)])]
    path = [(-2, 1), (5, 1)]
    fwd = items(client, path, a, b)
    rev = items(client, list(reversed(path)), a, b)
    assert_covers_unit_interval(fwd)
    assert_covers_unit_interval(rev)
    assert_reduced_fractions(fwd)

    def mirror(segments):
        out = []
        for i, seg in enumerate(reversed(segments)):
            mirrored = []
            for item in reversed(seg["intervals"]):
                if item["type"] == "point":
                    t = 1 - frac(item["t"])
                    item = {
                        **item,
                        "t": [t.numerator, t.denominator],
                        "events": [
                            {
                                **e,
                                "before": e["after"],
                                "after": e["before"],
                            }
                            for e in item["events"]
                        ],
                    }
                else:
                    start, end = 1 - frac(item["end"]), 1 - frac(item["start"])
                    item = {
                        **item,
                        "start": [start.numerator, start.denominator],
                        "end": [end.numerator, end.denominator],
                    }
                mirrored.append(item)
            out.append({"index": i, "intervals": mirrored})
        return out

    # Reversing the whole polyline maps every interval/event one-to-one back.
    assert rev == mirror(fwd)

    # And the forward run really contains a non-integer fraction parameter.
    all_ts = [
        frac(i["t"])
        for seg in fwd for i in point_items(seg)
    ]
    assert any(t.denominator != 1 for t in all_ts)
    # Intersection with triangle edge x+y=4 at y=1 -> x=3 -> t = 5/7.
    assert Fraction(5, 7) in all_ts


def test_multi_segment_path_states_at_vertices(client):
    # Two segments: enter through the left edge, leave through the right;
    # the shared fold vertex (2,2) sits inside and creates no contact point.
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    b = []
    segments = items(client, [(-2, 2), (2, 2), (6, 2)], a, b)
    assert_covers_unit_interval(segments)
    # No contact at the interior fold vertex (segment 1 starts at t=0 with a
    # positive-length inside range, not a point).
    assert segments[1]["intervals"][0]["type"] == "range"
    assert frac(segments[1]["intervals"][0]["start"]) == 0
    assert segments[1]["intervals"][0]["a"] == "inside"
    assert range_items(segments[0])[-1]["a"] == "inside"
    # The shared vertex joins the two inside ranges; segment 1 exits at t=1/2.
    exit_pt = point_items(segments[1])[0]
    assert frac(exit_pt["t"]) == Fraction(1, 2)


def test_simultaneous_contact_of_both_groups(client):
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    b = [poly([(4, 0), (8, 0), (8, 4), (4, 4)])]
    seg = items(client, [(2, 2), (6, 2)], a, b)[0]
    (mid,) = point_items(seg)
    assert frac(mid["t"]) == Fraction(1, 2)
    assert mid["a"] == "boundary" and mid["b"] == "boundary"
    by_group = {e["group"]: e for e in mid["events"]}
    assert set(by_group) == {"a", "b"}
    assert (by_group["a"]["before"], by_group["a"]["after"]) == (
        "inside", "outside"
    )
    assert (by_group["b"]["before"], by_group["b"]["after"]) == (
        "outside", "inside"
    )


def test_no_contact_single_range(client):
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    b = []
    seg = items(client, [(10, 10), (12, 10)], a, b)[0]
    assert not point_items(seg)
    (only,) = range_items(seg)
    assert (frac(only["start"]), frac(only["end"])) == (0, 1)
    assert (only["a"], only["b"]) == ("outside", "outside")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def assert_422(resp):
    assert resp.status_code == 422, resp.text
    data = resp.json()
    assert data["error"]["code"] in {"invalid_request", "invalid_geometry"}
    return data


def test_consecutive_duplicate_path_vertex_is_422_at_position(client):
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    resp = post(client, [(0, 0), (1, 1), (1, 1), (2, 2)], a, a)
    data = assert_422(resp)
    assert data["error"]["code"] == "invalid_request"
    detail = data["error"]["details"][0]
    assert detail["loc"] == ["body", "path"]
    # The original request position (vertex 2) is reported.
    assert "vertex 2" in detail["message"]


def test_non_consecutive_repeated_vertex_is_allowed(client):
    # A folded/closed polyline may revisit a non-adjacent vertex.
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    seg = items(client, [(-2, 2), (2, 2), (-2, 2)], a, [])
    assert_covers_unit_interval(seg)


def test_too_few_path_points_is_422(client):
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    for bad_path in ([], [(0, 0)]):
        data = assert_422(post(client, bad_path, a, a))
        assert data["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "bad_path",
    [
        [(0, 0), (1, 1.5)],          # non-integer
        [(0, 0), (True, 1)],         # bool is not an integer
        [(0, 0), ("1", 1)],          # string
        [(0, 0), (1_000_001, 0)],    # out of range
        [(0, 0), None],              # null vertex
        [(0, 0)],                    # too short
    ],
)
def test_malformed_path_is_structured_422(client, bad_path):
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    assert_422(post(client, bad_path, a, a))


def test_path_field_wrong_type_is_422(client):
    a = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    for payload in (
        {"a": a, "b": a},
        {"a": a, "b": a, "path": None},
        {"a": a, "b": a, "path": "x"},
    ):
        resp = client.post("/api/v1/transect", json=payload)
        assert_422(resp)


def test_geometry_error_keeps_existing_location(client):
    bowtie = [(0, 0), (4, 4), (4, 0), (0, 4)]
    resp = post(
        client, [(0, 0), (1, 1)],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)]), poly(bowtie)],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    data = assert_422(resp)
    assert data["error"]["code"] == "invalid_geometry"
    assert data["error"]["details"][0]["loc"][:2] == ["a", 1]


def test_rejected_path_does_not_affect_overlap_endpoint(client):
    good = [poly([(0, 0), (4, 0), (4, 4), (0, 4)])]
    # An illegal path is rejected ...
    resp = post(client, [(0, 0), (0, 0)], good, good)
    assert_422(resp)
    # ... and the original overlap interface still computes normally, with
    # its unchanged response shape.
    resp = client.post(
        "/api/v1/overlap",
        json={"a": good, "b": [poly([(2, 0), (6, 0), (6, 4), (2, 4)])]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["area_sq_mm"] == [8, 1]
    assert data["decimal"] == "8.000"
    assert data["rounding"] == "half-up"
    assert data["units"] == "mm^2"
