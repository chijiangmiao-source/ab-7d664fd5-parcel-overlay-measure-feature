"""Unit tests for transect primitives and randomized profile checks."""

from __future__ import annotations

import random
from fractions import Fraction as F

from app.geometry.rationals import P, point_in_interior, point_on_segment
from app.geometry.transect import (
    INSIDE,
    OUTSIDE,
    Event,
    PointInterval,
    RangeInterval,
    _edge_contact_params,
    line_transect,
)
from app.geometry.validation import build_polygon


def params(p0, p1, a, b):
    return _edge_contact_params(P(*p0), P(*p1), P(*a), P(*b))


def test_contact_params_proper_cross():
    assert params((0, 0), (4, 4), (0, 4), (4, 0)) == [F(1, 2)]


def test_contact_params_fractional():
    # y=1 line meets triangle edge x+y=4 at x=3 -> t=3/7 of (-2,1)->(5,1)
    (t,) = params((-2, 1), (5, 1), (0, 4), (4, 0))
    assert t == F(5, 7)
    assert isinstance(t, F) and t.denominator == 7


def test_contact_params_endpoint_of_ring_edge():
    # T-junction through the ring edge endpoint.
    assert params((0, 0), (4, 0), (2, 0), (2, 2)) == [F(1, 2)]
    assert params((2, 2), (2, -2), (0, 0), (4, 0)) == [F(1, 2)]


def test_contact_params_tangent_through_vertex():
    # Horizontal line through apex (2,3): two ring edges meet there.
    t1 = params((0, 3), (4, 3), (0, 0), (2, 3))
    t2 = params((0, 3), (4, 3), (2, 3), (4, 0))
    assert t1 == t2 == [F(1, 2)]


def test_contact_params_collinear_overlap():
    lo, hi = params((0, 0), (6, 0), (2, 0), (4, 0))
    assert (lo, hi) == (F(1, 3), F(2, 3))


def test_contact_params_collinear_point_contact():
    assert params((0, 0), (2, 0), (2, 0), (2, 4)) == [F(1)]
    # Segment touches a collinear ring edge only at its shared endpoint.
    assert params((-2, 0), (0, 0), (0, 0), (4, 0)) == [F(1)]


def test_contact_params_disjoint():
    assert params((0, 0), (1, 0), (2, 0), (3, 0)) == []
    assert params((0, 0), (1, 1), (2, 0), (3, 1)) == []
    assert params((0, 0), (2, 2), (0, 3), (1, 2)) == []


def _material_state(point, poly):
    """Independent reference state using the validation-level predicates."""
    for ring in [poly.exterior, *poly.holes]:
        pts = ring.points
        n = len(pts)
        for i in range(n):
            if point_on_segment(point, pts[i], pts[(i + 1) % n]):
                return "boundary"
    if not point_in_interior(point, poly.exterior.points):
        return OUTSIDE
    if any(point_in_interior(point, h.points) for h in poly.holes):
        return OUTSIDE
    return INSIDE


def _profile_state(profiles, seg_index, t):
    for item in profiles[seg_index].items:
        if hasattr(item, "t"):
            if item.t == t:
                return item.states
        elif item.start <= t < item.end:
            return item.states
        elif item.end == t:
            continue
    raise AssertionError(f"parameter {t} not covered in segment {seg_index}")


def _random_polygon(rng, with_hole):
    while True:
        x0, y0 = r0 = rng.randrange(-8, 4), rng.randrange(-8, 4)
        x1, y1 = r0 = rng.randrange(x0 + 3, 10), rng.randrange(y0 + 3, 10)
        ext = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        holes = []
        if with_hole and x1 - x0 >= 5 and y1 - y0 >= 5:
            hx = rng.randrange(x0 + 1, x1 - 2)
            hy = rng.randrange(y0 + 1, y1 - 2)
            holes = [[(hx, hy), (hx + 2, hy), (hx + 2, hy + 2), (hx, hy + 2)]]
            if hx + 2 >= x1 or hy + 2 >= y1:
                holes = []
        try:
            return build_polygon(ext, holes)
        except Exception:
            continue


def test_randomized_reversal_correspondence():
    """Reversing the polyline mirrors every interval and swaps before/after."""
    rng = random.Random(771)
    for _ in range(60):
        poly_a = _random_polygon(rng, True)
        poly_b = _random_polygon(rng, False)
        path = [(rng.randrange(-12, 12), rng.randrange(-12, 12))]
        while len(path) < rng.randrange(2, 5):
            nxt = (rng.randrange(-12, 12), rng.randrange(-12, 12))
            if nxt != path[-1]:
                path.append(nxt)

        fwd = line_transect(path, [poly_a], [poly_b])
        rev = line_transect(list(reversed(path)), [poly_a], [poly_b])
        assert len(fwd) == len(rev)
        for i, profile in enumerate(fwd):
            mirrored_profile = rev[len(fwd) - 1 - i]
            assert len(profile.items) == len(mirrored_profile.items)
            for item, mirror in zip(
                reversed(profile.items), mirrored_profile.items
            ):
                if isinstance(item, PointInterval):
                    assert isinstance(mirror, PointInterval)
                    assert mirror.t == 1 - item.t
                    assert mirror.states == item.states
                    assert len(mirror.events) == len(item.events)
                    for ev, mev in zip(item.events, mirror.events):
                        assert mev.group == ev.group
                        assert mev.before == ev.after
                        assert mev.after == ev.before
                        assert mev.contacts == ev.contacts
                else:
                    assert isinstance(mirror, RangeInterval)
                    assert mirror.start == 1 - item.end
                    assert mirror.end == 1 - item.start
                    assert mirror.states == item.states


def test_randomized_profiles_match_reference_states():
    rng = random.Random(20260917)
    for _ in range(120):
        poly_a = _random_polygon(rng, rng.random() < 0.4)
        poly_b = _random_polygon(rng, rng.random() < 0.4)
        n_vertices = rng.randrange(2, 5)
        path = [(rng.randrange(-12, 12), rng.randrange(-12, 12))]
        while len(path) < n_vertices:
            nxt = (rng.randrange(-12, 12), rng.randrange(-12, 12))
            if nxt != path[-1]:
                path.append(nxt)

        profiles = line_transect(path, [poly_a], [poly_b])

        # The intervals tile [0,1] exactly: no gaps, no overlaps, ordered.
        assert [p.index for p in profiles] == list(range(len(path) - 1))
        for profile in profiles:
            cursor = F(0)
            point_params = set()
            for item in profile.items:
                if hasattr(item, "t"):
                    assert item.t >= cursor
                    assert item.t not in point_params
                    point_params.add(item.t)
                    cursor = item.t
                else:
                    assert item.start == cursor and item.end > item.start
                    cursor = item.end
            assert cursor == 1

        for seg_index in range(len(path) - 1):
            (x0, y0), (x1, y1) = path[seg_index], path[seg_index + 1]
            dx, dy = x1 - x0, y1 - y0

            # Fine rational grid: a missed boundary cut would leave two
            # different states inside one reported range and show up here.
            for k in range(1, 40):
                t = F(k, 40)
                point = (F(x0) + t * dx, F(y0) + t * dy)
                expected = (
                    _material_state(point, poly_a),
                    _material_state(point, poly_b),
                )
                assert _profile_state(profiles, seg_index, t) == expected, (
                    path, seg_index, t, expected
                )

            # Every reported contact parameter must actually land on a ring.
            for item in profiles[seg_index].items:
                if not hasattr(item, "t"):
                    continue
                point = (F(x0) + item.t * dx, F(y0) + item.t * dy)
                touched = False
                for poly in (poly_a, poly_b):
                    for ring in [poly.exterior, *poly.holes]:
                        pts = ring.points
                        n = len(pts)
                        if any(
                            point_on_segment(point, pts[i], pts[(i + 1) % n])
                            for i in range(n)
                        ):
                            touched = True
                assert touched, (path, seg_index, item.t)
