"""Geometry-level tests for the exact polyline transect engine.

Beyond fixed scenarios (outer ring + hole crossings, tangencies, boundary
runs, fractional intersections) these tests check the structural guarantees:

* every raw segment is covered by an ordered, gap- and overlap-free partition
  of [0, 1] with reduced, fraction parameters;
* isolated contacts carry the correct before / at / after relations;
* reversing the whole polyline produces the one-to-one reverse image of the
  forward intervals, events and contacts;
* dense random sampling agrees with an independent point classifier;
* no floating point ever occurs in the output.
"""

from __future__ import annotations

import random
from fractions import Fraction

from app.geometry.rationals import int_point, point_in_interior, point_on_segment
from app.geometry.transect import (
    BOUNDARY,
    INSIDE,
    OUTSIDE,
    transect_polyline,
)
from app.geometry.validation import Polygon, build_polygon

SQ4 = [(0, 0), (4, 0), (4, 4), (0, 4)]
SQ4_HOLE = [[(1, 1), (3, 1), (3, 3), (1, 3)]]


def sq(x0, y0, x1, y1, holes=()):
    return build_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], list(holes))


def independent_status(point, polygons: list[Polygon]) -> str:
    """Classifier assembled independently from the raw ring primitives."""
    for poly in polygons:
        for ring in (poly.exterior, *poly.holes):
            for i, c in enumerate(ring.points):
                d = ring.points[(i + 1) % len(ring.points)]
                if point_on_segment(point, c, d):
                    return BOUNDARY
    for poly in polygons:
        if point_in_interior(point, poly.exterior.points):
            if any(point_in_interior(point, h.points) for h in poly.holes):
                return OUTSIDE
            return INSIDE
    return OUTSIDE


def assert_well_partitioned(seg):
    assert seg.intervals[0].t0 == 0
    assert seg.intervals[-1].t1 == 1
    prev = Fraction(0)
    for iv in seg.intervals:
        assert iv.t0 == prev
        assert iv.t0 < iv.t1
        # positive denominators prove the cuts are reduced Fractions
        assert iv.t0.denominator > 0 and iv.t1.denominator > 0
        prev = iv.t1
    assert prev == 1
    # strictly increasing event order
    ts = [e.t for e in seg.events]
    assert ts == sorted(ts)
    cts = [c.t for c in seg.contacts]
    assert cts == sorted(set(cts))
    # contacts are isolated points (may sit at a segment endpoint); their
    # sides agree with the adjacent interval labels and are null off the end
    for c in seg.contacts:
        assert 0 <= c.t <= 1
        assert c.a[1] == BOUNDARY or c.b[1] == BOUNDARY
        k = next(i for i, iv in enumerate(seg.intervals) if iv.t1 >= c.t)
        if c.t == 0:
            assert c.a[0] is None and c.b[0] is None
            assert (seg.intervals[0].a, seg.intervals[0].b) == (c.a[2], c.b[2])
        elif c.t == 1:
            assert c.a[2] is None and c.b[2] is None
            assert (seg.intervals[-1].a, seg.intervals[-1].b) == (c.a[0], c.b[0])
        else:
            assert (seg.intervals[k].a, seg.intervals[k].b) == (c.a[0], c.b[0])
            assert (seg.intervals[k + 1].a, seg.intervals[k + 1].b) == (
                c.a[2], c.b[2]
            )
    # everything is exact rationals
    for e in seg.events:
        assert isinstance(e.t, Fraction) and isinstance(e.point[0], Fraction)
    for c in seg.contacts:
        assert isinstance(c.t, Fraction) and isinstance(c.point[1], Fraction)


def label_at(seg, t: Fraction):
    for iv in seg.intervals:
        if iv.t0 < t < iv.t1:
            return iv.a, iv.b
        if t == iv.t0 == 0 or t == iv.t1 == 1:
            continue
    return None


def test_crosses_outer_ring_and_hole_two_groups():
    a = [sq(0, 0, 4, 4, SQ4_HOLE)]
    # B's bottom edge lies on the path line y=2 -> collinear boundary run
    b = [sq(2, 2, 6, 6)]
    segs = transect_polyline(a, b, [(-1, 2), (7, 2)])
    assert len(segs) == 1
    seg = segs[0]
    assert_well_partitioned(seg)
    got = [(iv.t0, iv.t1, iv.a, iv.b) for iv in seg.intervals]
    # x = -1 + 8t; ring crossings at x=0,1,2,3,4,6 -> t = 1/8,1/4,3/8,1/2,5/8,7/8
    assert got == [
        (Fraction(0), Fraction(1, 8), OUTSIDE, OUTSIDE),
        (Fraction(1, 8), Fraction(1, 4), INSIDE, OUTSIDE),
        (Fraction(1, 4), Fraction(3, 8), OUTSIDE, OUTSIDE),
        (Fraction(3, 8), Fraction(1, 2), OUTSIDE, BOUNDARY),
        (Fraction(1, 2), Fraction(5, 8), INSIDE, BOUNDARY),
        (Fraction(5, 8), Fraction(7, 8), OUTSIDE, BOUNDARY),
        (Fraction(7, 8), Fraction(1), OUTSIDE, OUTSIDE),
    ]
    # isolated contacts: A crossings at x=0,1,3,4.  The x=3 and x=4 crossings
    # happen while the path runs along B's boundary edge, so B is "boundary"
    # on all three sides.  B's run endpoints (x=2 and x=6) are not isolated.
    cts = {c.t: (c.a, c.b) for c in seg.contacts}
    assert set(cts) == {Fraction(1, 8), Fraction(1, 4),
                        Fraction(1, 2), Fraction(5, 8)}
    assert cts[Fraction(1, 8)] == (
        (OUTSIDE, BOUNDARY, INSIDE), (OUTSIDE, OUTSIDE, OUTSIDE))
    assert cts[Fraction(1, 4)] == (
        (INSIDE, BOUNDARY, OUTSIDE), (OUTSIDE, OUTSIDE, OUTSIDE))
    assert cts[Fraction(1, 2)] == (
        (OUTSIDE, BOUNDARY, INSIDE), (BOUNDARY, BOUNDARY, BOUNDARY))
    assert cts[Fraction(5, 8)] == (
        (INSIDE, BOUNDARY, OUTSIDE), (BOUNDARY, BOUNDARY, BOUNDARY))


def test_vertex_tangency_records_before_middle_after():
    a = [sq(0, 0, 4, 4)]
    # path touches corner (0, 4) from outside and leaves outside again
    seg = transect_polyline(a, [], [(-1, 3), (1, 5)])[0]
    assert_well_partitioned(seg)
    assert [(iv.a) for iv in seg.intervals] == [OUTSIDE, OUTSIDE]
    contact = seg.contacts[0]
    assert contact.t == Fraction(1, 2)
    assert contact.point == (Fraction(0), Fraction(4))
    assert contact.a == (OUTSIDE, BOUNDARY, OUTSIDE)
    assert contact.b == (OUTSIDE, OUTSIDE, OUTSIDE)


def test_vertex_crossing_through_corner():
    a = [sq(0, 0, 4, 4)]
    seg = transect_polyline(a, [], [(-1, -1), (1, 1)])[0]
    assert_well_partitioned(seg)
    assert [(iv.t0, iv.t1, iv.a) for iv in seg.intervals] == [
        (0, Fraction(1, 2), OUTSIDE),
        (Fraction(1, 2), 1, INSIDE),
    ]
    assert seg.contacts[0].a == (OUTSIDE, BOUNDARY, INSIDE)


def test_path_running_along_collinear_boundary():
    a = [sq(0, 0, 4, 4)]
    seg = transect_polyline(a, [], [(-1, 0), (5, 0)])[0]
    assert_well_partitioned(seg)
    got = [(iv.t0, iv.t1, iv.a) for iv in seg.intervals]
    # x = -1 + 6t; boundary run x in [0, 4] -> t in [1/6, 5/6]
    assert got == [
        (0, Fraction(1, 6), OUTSIDE),
        (Fraction(1, 6), Fraction(5, 6), BOUNDARY),
        (Fraction(5, 6), 1, OUTSIDE),
    ]
    # a boundary run has no isolated contacts on it
    assert seg.contacts == []
    events = [(e.t, e.a) for e in seg.events]
    assert (Fraction(1, 6), BOUNDARY) in events
    assert (Fraction(5, 6), BOUNDARY) in events


def test_path_vertex_resting_on_boundary_is_event_with_null_side():
    a = [sq(0, 0, 4, 4)]
    segs = transect_polyline(a, [], [(-1, 3), (0, 4), (1, 3)])
    assert segs[0].contacts[0].a == (OUTSIDE, BOUNDARY, None)
    assert segs[1].contacts[0].a == (None, BOUNDARY, INSIDE)
    # the boundary point is an event on both adjacent segments
    assert segs[0].events[-1].t == 1
    assert segs[1].events[0].t == 0


def test_fractional_intersections_are_exact():
    a = [sq(0, 0, 4, 4)]
    # (-1,1) -> (5,3): x = -1 + 6t, y = 1 + 2t; x=0 at t=1/6 (y=4/3),
    # x=4 at t=5/6 (y=8/3)
    seg = transect_polyline(a, [], [(-1, 1), (5, 3)])[0]
    assert_well_partitioned(seg)
    assert [iv.t0 for iv in seg.intervals] == [0, Fraction(1, 6), Fraction(5, 6)]
    first = seg.contacts[0]
    assert first.t == Fraction(1, 6)
    assert first.point == (Fraction(0), Fraction(4, 3))
    assert first.a == (OUTSIDE, BOUNDARY, INSIDE)
    assert seg.contacts[1].point == (Fraction(4), Fraction(8, 3))


def test_reversed_polyline_is_reverse_image():
    a = [sq(0, 0, 4, 4, SQ4_HOLE)]
    b = [sq(2, -1, 6, 5)]
    path = [(-2, 5), (-1, 1), (5, 3), (6, 0), (0, -2)]
    forward = transect_polyline(a, b, path)
    reverse = transect_polyline(a, b, list(reversed(path)))
    assert len(forward) == len(reverse) == len(path) - 1

    for i, fseg in enumerate(forward):
        rseg = reverse[len(path) - 2 - i]
        assert (fseg.start, fseg.end) == (rseg.end, rseg.start)

        # intervals: same labels, parameters complemented to 1, reverse order
        assert len(fseg.intervals) == len(rseg.intervals)
        for fiv, riv in zip(fseg.intervals, reversed(rseg.intervals)):
            assert fiv.t0 + riv.t1 == 1
            assert fiv.t1 + riv.t0 == 1
            assert (fiv.a, fiv.b) == (riv.a, riv.b)

        # events: same points and labels at 1 - t
        assert len(fseg.events) == len(rseg.events)
        for fev, rev_ev in zip(fseg.events, reversed(rseg.events)):
            assert fev.t + rev_ev.t == 1
            assert fev.point == rev_ev.point
            assert (fev.a, fev.b) == (rev_ev.a, rev_ev.b)

        # contacts: before/after swap under reversal
        assert len(fseg.contacts) == len(rseg.contacts)
        for fc, rc in zip(fseg.contacts, reversed(rseg.contacts)):
            assert fc.t + rc.t == 1
            assert fc.point == rc.point
            assert fc.a == (rc.a[2], rc.a[1], rc.a[0])
            assert fc.b == (rc.b[2], rc.b[1], rc.b[0])


def test_multi_segment_path_covers_each_raw_segment():
    a = [sq(0, 0, 4, 4)]
    path = [(-1, 1), (1, 1), (1, 5), (5, 5), (5, -1), (-1, -1)]
    segs = transect_polyline(a, [], path)
    assert [s.index for s in segs] == list(range(len(path) - 1))
    for i, seg in enumerate(segs):
        assert_well_partitioned(seg)
        assert seg.start == tuple(path[i])
        assert seg.end == tuple(path[i + 1])


def test_dense_sampling_matches_independent_classifier():
    rng = random.Random(20260917)
    # A and B: axis-aligned rectangles (possibly with a hole), scattered.
    a = [sq(-6, -6, 2, 2,
            [[(-4, -4), (-1, -4), (-1, -1), (-4, -1)]]),
         sq(4, 4, 9, 9)]
    b = [sq(-2, -2, 6, 6), sq(-9, 3, -5, 7)]

    for trial in range(200):
        p0 = (rng.randint(-10, 10), rng.randint(-10, 10))
        p1 = (rng.randint(-10, 10), rng.randint(-10, 10))
        if p0 == p1:
            continue
        seg = transect_polyline(a, b, [p0, p1])[0]
        assert_well_partitioned(seg)
        q0, q1 = int_point(p0), int_point(p1)
        for k in range(1, 40):
            t = Fraction(k, 41)
            point = (
                q0[0] + t * (q1[0] - q0[0]),
                q0[1] + t * (q1[1] - q0[1]),
            )
            # Skip samples that sit exactly on a boundary (they are events).
            got = label_at(seg, t)
            if got is None:
                continue
            want = (independent_status(point, a), independent_status(point, b))
            assert got == want, (p0, p1, t, trial)
