"""Heavy engine tests: random intersecting polygons, degenerate contacts."""

from __future__ import annotations

import random
from fractions import Fraction

from app.geometry.arrangement import overlap_area
from app.geometry.rationals import ring_area
from app.models import PolygonIn
from app.service import build_group

from tests.test_differential import reference_overlap  # noqa: E402

F = Fraction


def _random_triangle(rng):
    while True:
        pts = [(rng.randrange(0, 9), rng.randrange(0, 9)) for _ in range(3)]
        (x1, y1), (x2, y2), (x3, y3) = pts
        if (x2 - x1) * (y3 - y1) != (x3 - x1) * (y2 - y1):
            break
    if rng.random() < 0.5:
        pts.reverse()
    return PolygonIn(exterior=pts)


def _random_rect(rng):
    x1, x2 = sorted(rng.sample(range(0, 10), 2))
    y1, y2 = sorted(rng.sample(range(0, 10), 2))
    if x1 == x2 or y1 == y2:
        return _random_rect(rng)
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    if rng.random() < 0.5:
        pts.reverse()
    return PolygonIn(exterior=pts)


def _random_shape(rng):
    return rng.choice([_random_triangle, _random_rect, _random_rect])(rng)


def test_random_heavily_intersecting_pairs():
    rng = random.Random(99)
    for trial in range(250):
        a = [_random_shape(rng)]
        b = [_random_shape(rng)]
        ga, gb = build_group(a, "a"), build_group(b, "b")
        engine = overlap_area(ga, gb)
        oracle = reference_overlap(ga, gb)
        assert engine == oracle, f"trial {trial}: {a} vs {b}: {engine} != {oracle}"
        assert overlap_area(gb, ga) == engine


def test_random_multi_polygon_shared_region():
    rng = random.Random(77)
    for trial in range(120):
        # Within a group polygons must not touch: place them on a 2x2 macro
        # grid of 8x8 cells offset so B's grid is shifted by (4, 4), yielding
        # many fractional / multiple crossings between groups.
        def group(shift):
            polys = []
            for r in range(2):
                for c in range(2):
                    x0, y0 = 12 * c + shift, 12 * r + shift
                    shape = rng.choice(["rect", "tri", "l"])
                    if shape == "rect":
                        pts = [(x0, y0), (x0 + 8, y0), (x0 + 8, y0 + 8),
                               (x0, y0 + 8)]
                    elif shape == "tri":
                        pts = [(x0, y0), (x0 + 8, y0), (x0, y0 + 8)]
                    else:
                        pts = [(x0, y0), (x0 + 8, y0), (x0 + 8, y0 + 3),
                               (x0 + 3, y0 + 3), (x0 + 3, y0 + 8),
                               (x0, y0 + 8)]
                    if rng.random() < 0.5:
                        pts.reverse()
                    holes = []
                    if shape == "rect" and rng.random() < 0.5:
                        h = [(x0 + 3, y0 + 3), (x0 + 5, y0 + 3),
                             (x0 + 5, y0 + 5), (x0 + 3, y0 + 5)]
                        if rng.random() < 0.5:
                            h.reverse()
                        holes.append(h)
                    polys.append(PolygonIn(exterior=pts, holes=holes))
            return polys

        a, b = group(0), group(4)
        ga, gb = build_group(a, "a"), build_group(b, "b")
        engine = overlap_area(ga, gb)
        oracle = reference_overlap(ga, gb)
        assert engine == oracle, f"trial {trial}: {engine} != {oracle}"
        assert engine >= 0


def test_coincident_polygons_cross_groups():
    sq = [(0, 0), (5, 0), (5, 5), (0, 5)]
    ga = build_group([PolygonIn(exterior=sq)], "a")
    gb = build_group([PolygonIn(exterior=list(reversed(sq)))], "b")
    assert overlap_area(ga, gb) == F(25)


def test_partial_coincident_edges():
    # Two rectangles sharing a sub-segment of an edge while overlapping.
    a = [(0, 0), (4, 0), (4, 4), (0, 4)]
    b = [(2, 0), (6, 0), (6, 4), (2, 4)]
    ga = build_group([PolygonIn(exterior=a)], "a")
    gb = build_group([PolygonIn(exterior=b)], "b")
    assert overlap_area(ga, gb) == F(8)


def test_t_junction_contact_cross_groups():
    # Vertex of B lands in the middle of an edge of A; overlap is a triangle.
    a = [(0, 0), (6, 0), (6, 6), (0, 6)]
    # B: triangle with base along the middle of A's top edge, dipping in.
    b = [(2, 6), (4, 6), (3, 3)]
    ga = build_group([PolygonIn(exterior=a)], "a")
    gb = build_group([PolygonIn(exterior=b)], "b")
    # Triangle area = base 2 * height 3 / 2 = 3.
    assert overlap_area(ga, gb) == F(3)


def test_cross_group_edge_overlap_zero_area():
    a = [(0, 0), (3, 0), (3, 3), (0, 3)]
    b = [(1, 3), (2, 3), (2, 6), (1, 6)]
    ga = build_group([PolygonIn(exterior=a)], "a")
    gb = build_group([PolygonIn(exterior=b)], "b")
    assert overlap_area(ga, gb) == F(0)


def test_many_holes_strip():
    # Big rectangle with a row of holes; overlapping band crosses them all.
    holes = [[(x, 2), (x + 1, 2), (x + 1, 7), (x, 7)] for x in (1, 3, 5, 7)]
    a = [PolygonIn(exterior=[(0, 0), (10, 0), (10, 9), (0, 9)], holes=holes)]
    b = [PolygonIn(exterior=[(0, 1), (10, 1), (10, 8), (0, 8)])]
    ga, gb = build_group(a, "a"), build_group(b, "b")
    # band area 70 minus four holes of 5 each = 50
    assert overlap_area(ga, gb) == F(50)


def test_self_area_identity_with_holes():
    ext = [(0, 0), (10, 0), (10, 10), (0, 10)]
    h1 = [(1, 1), (3, 1), (3, 3), (1, 3)]
    h2 = [(5, 6), (8, 6), (8, 9), (5, 9)]
    g = build_group([PolygonIn(exterior=ext, holes=[h1, h2])], "a")
    expected = ring_area(g[0].exterior.points) - ring_area(
        g[0].holes[0].points
    ) - ring_area(g[0].holes[1].points)
    assert overlap_area(g, g) == expected
