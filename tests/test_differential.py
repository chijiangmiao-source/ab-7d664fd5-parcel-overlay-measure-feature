"""Differential / property tests.

An independent exact reference computes overlap by vertical-slab integration
with mid-sample point-in-ring tests (a different algorithm from the planar
arrangement engine).  Random valid inputs must agree, results must be
symmetric, and self-overlap must equal the polygon's own material area.
"""

from __future__ import annotations

import random
from fractions import Fraction
from typing import List, Sequence, Tuple

from app.geometry.arrangement import overlap_area
from app.geometry.rationals import (
    Point,
    point_on_segment,
    ring_area,
    ring_signed_area2,
)
from app.models import PolygonIn
from app.service import build_group

F = Fraction


# ---------------------------------------------------------------------------
# Independent reference: vertical slabs + mid-sample containment
# ---------------------------------------------------------------------------

def _boundary_ys(edges, xm: F) -> List[F]:
    ys: List[F] = []
    for (x1, y1), (x2, y2) in edges:
        if y1 == y2:  # horizontal edge
            if min(x1, x2) < xm < max(x1, x2):
                ys.append(y1)
        elif x1 != x2 and min(x1, x2) < xm < max(x1, x2):
            t = (xm - x1) / (x2 - x1)
            ys.append(y1 + t * (y2 - y1))
        # vertical edges never meet a strictly interior slab midpoint
    return ys


def _material(polys, p: Point) -> bool:
    x, y = p
    for poly in polys:
        if _inside(p, poly.exterior.points) and not any(
            _inside(p, h.points) for h in poly.holes
        ):
            return True
    return False


def _inside(p: Point, ring) -> bool:
    # Interior-only point-in-ring (boundary never occurs at slab midpoints).
    from app.geometry.rationals import point_in_interior
    return point_in_interior(p, ring)


def reference_overlap(group_a, group_b) -> Fraction:
    edges: List[Tuple[Point, Point]] = []
    xs: List[F] = []

    def consume(poly):
        for ring in [poly.exterior, *poly.holes]:
            pts = ring.points
            n = len(pts)
            for k in range(n):
                a, b = pts[k], pts[(k + 1) % n]
                edges.append((a, b))
                xs.append(a[0])
                xs.append(b[0])

    for p in group_a:
        consume(p)
    for p in group_b:
        consume(p)

    # Proper (non-parallel) intersection x-coordinates.
    from app.geometry.rationals import cross as cr
    m = len(edges)
    for i in range(m):
        (ax, ay), (bx, by) = edges[i]
        rx, ry = bx - ax, by - ay
        for j in range(i + 1, m):
            (cx, cy), (dx, dy) = edges[j]
            sx, sy = dx - cx, dy - cy
            denom = rx * sy - ry * sx
            if denom == 0:
                continue
            t = ((cx - ax) * sy - (cy - ay) * sx) / denom
            u = ((cx - ax) * ry - (cy - ay) * rx) / denom
            if F(0) < t < F(1) and F(0) < u < F(1):
                xs.append(ax + t * rx)

    xs = sorted(set(xs))
    total = F(0)
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x0 == x1:
            continue
        xm = (x0 + x1) / 2
        ys = sorted(set(_boundary_ys(edges, xm)))
        for k in range(len(ys) - 1):
            y0, y1 = ys[k], ys[k + 1]
            if y0 == y1:
                continue
            ym = (y0 + y1) / 2
            if _material(group_a, (xm, ym)) and _material(group_b, (xm, ym)):
                total += (y1 - y0) * (x1 - x0)
    return total


# ---------------------------------------------------------------------------
# Random valid geometry on a spaced grid
# ---------------------------------------------------------------------------

def _ring_from_cell(cx: int, cy: int, kind: str, rng: random.Random):
    if kind == "rect":
        w, h = rng.choice([(6, 6), (5, 3), (3, 5), (4, 6)])
        ring = [(cx, cy), (cx + w, cy), (cx + w, cy + h), (cx, cy + h)]
    elif kind == "tri":
        ring = [
            (cx, cy),
            (cx + rng.choice([4, 5, 6]), cy),
            (cx, cy + rng.choice([4, 5, 6])),
        ]
    else:  # concave L shape
        ring = [
            (cx, cy), (cx + 6, cy), (cx + 6, cy + 2),
            (cx + 2, cy + 2), (cx + 2, cy + 6), (cx, cy + 6),
        ]
    if rng.random() < 0.5:
        ring = list(reversed(ring))
    return ring


def _random_group(rng: random.Random, cells):
    polys = []
    for cx, cy in cells:
        kind = rng.choice(["rect", "tri", "l"])
        ext = _ring_from_cell(cx, cy, kind, rng)
        holes = []
        if rng.random() < 0.35:
            # Ensure a 6x6 rectangle so the 2x2 hole fits strictly inside.
            ext = _ring_from_cell(cx, cy, "rect", rng)
            ext = [(cx, cy), (cx + 6, cy), (cx + 6, cy + 6), (cx, cy + 6)]
            if rng.random() < 0.5:
                ext = list(reversed(ext))
            hx, hy = cx + 2, cy + 2
            hole = [(hx, hy), (hx + 2, hy), (hx + 2, hy + 2), (hx, hy + 2)]
            if rng.random() < 0.5:
                hole = list(reversed(hole))
            holes.append(hole)
        polys.append(PolygonIn(exterior=ext, holes=holes))
    return polys


def _grid_cells(rng: random.Random, count: int):
    positions = [(10 * col, 10 * row)
                 for col in range(5) for row in range(5)]
    rng.shuffle(positions)
    return positions[:count]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reference_sanity():
    a = [PolygonIn(exterior=[(0, 0), (6, 0), (6, 6), (0, 6)],
                   holes=[[(2, 2), (4, 2), (4, 4), (2, 4)]])]
    b = [PolygonIn(exterior=[(1, 1), (5, 1), (5, 5), (1, 5)])]
    ga, gb = build_group(a, "a"), build_group(b, "b")
    assert reference_overlap(ga, gb) == F(12)
    assert overlap_area(ga, gb) == F(12)


def test_fuzz_matches_independent_reference():
    rng = random.Random(20260915)
    for trial in range(60):
        a = _random_group(rng, _grid_cells(rng, rng.randrange(1, 5)))
        b = _random_group(rng, _grid_cells(rng, rng.randrange(1, 5)))
        ga, gb = build_group(a, "a"), build_group(b, "b")
        engine = overlap_area(ga, gb)
        oracle = reference_overlap(ga, gb)
        assert engine == oracle, f"trial {trial}: engine={engine} oracle={oracle}"
        assert overlap_area(gb, ga) == engine
        assert engine >= 0


def test_self_overlap_equals_material_area():
    ext = [(0, 0), (8, 0), (8, 8), (0, 8)]
    hole = [(2, 2), (6, 2), (6, 6), (2, 6)]
    built = build_group([PolygonIn(exterior=ext, holes=[hole])], "a")
    assert overlap_area(built, built) == ring_area(built[0].exterior.points) - (
        ring_area(built[0].holes[0].points)
    )


def test_self_overlap_fuzz_equals_area():
    rng = random.Random(7)
    for _ in range(20):
        polys = _random_group(rng, _grid_cells(rng, rng.randrange(1, 4)))
        built = build_group(polys, "a")
        expected = F(0)
        for p in built:
            expected += ring_area(p.exterior.points)
            for h in p.holes:
                # Holes never nest in this generator; subtract every hole.
                expected -= ring_area(h.points)
        assert overlap_area(built, built) == expected
