"""Exact rational geometry primitives.

All coordinates are :class:`fractions.Fraction`, so every intersection and
area is computed without floating point rounding.  Integer input coordinates
(mm) embed exactly as fractions.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Sequence, Tuple

# A point is an immutable pair of exact rationals (units: millimetres).
Point = Tuple[Fraction, Fraction]
Segment = Tuple[Point, Point]


def P(x: int | Fraction, y: int | Fraction) -> Point:
    return (Fraction(x), Fraction(y))


def int_point(p: Tuple[int, int]) -> Point:
    return (Fraction(p[0]), Fraction(p[1]))


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

def cross(o: Point, a: Point, b: Point) -> Fraction:
    """Cross product of vectors o->a and o->b."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def orientation(a: Point, b: Point, c: Point) -> int:
    v = cross(a, b, c)
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def point_on_segment(p: Point, a: Point, b: Point) -> bool:
    if cross(a, b, p) != 0:
        return False
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def proper_intersection(a: Point, b: Point, c: Point, d: Point) -> Point:
    """Intersection point of two segments that properly cross (non-parallel)."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    # t = ((c - a) x s) / (r x s)
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / denom
    return (a[0] + t * r[0], a[1] + t * r[1])


# ---------------------------------------------------------------------------
# Ring helpers (rational coordinates)
# ---------------------------------------------------------------------------

def ring_signed_area2(ring: Sequence[Point]) -> Fraction:
    """Twice the signed area of a closed ring (shoelace)."""
    total = Fraction(0)
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total


def ring_area(ring: Sequence[Point]) -> Fraction:
    return abs(ring_signed_area2(ring)) / 2


def point_in_ring(point: Point, ring: Sequence[Point]) -> bool:
    """Interior containment for a boundary of a *simple* ring.

    Points on the boundary are considered contained.  Exact half-open ray
    casting (only upward edges, excluding their top vertex).
    """
    n = len(ring)
    inside = False
    px, py = point
    boundary = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if point_on_segment(point, ring[j], ring[i]):
            boundary = True
        if (yi > py) != (yj > py):
            x_cross = xi + (py - yi) * (xj - xi) / (yj - yi)
            if px < x_cross:
                inside = not inside
        j = i
    return inside or boundary


def point_in_interior(point: Point, ring: Sequence[Point]) -> bool:
    """Like :func:`point_in_ring` but the boundary counts as *outside*."""
    n = len(ring)
    inside = False
    px, py = point
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if point_on_segment(point, ring[j], ring[i]):
            return False
        if (yi > py) != (yj > py):
            x_cross = xi + (py - yi) * (xj - xi) / (yj - yi)
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def ring_self_intersections(ring: Sequence[Point]) -> bool:
    """True if a closed ring is NOT simple.

    Every pair of non-adjacent edges is tested for any common point (proper
    crossing, endpoint contact, collinear overlap).  Adjacent edges share only
    their common endpoint; input vertices are pairwise distinct (checked at the
    model boundary), so they cannot overlap or touch elsewhere.
    """
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        for j in range(i + 1, n):
            if (i + 1) % n == j or (j + 1) % n == i:
                continue
            c, d = ring[j], ring[(j + 1) % n]
            if segments_intersect(a, b, c, d):
                return True
    return False


def bboxes_disjoint(a: Point, b: Point, c: Point, d: Point) -> bool:
    return (
        max(a[0], b[0]) < min(c[0], d[0])
        or max(c[0], d[0]) < min(a[0], b[0])
        or max(a[1], b[1]) < min(c[1], d[1])
        or max(c[1], d[1]) < min(a[1], b[1])
    )


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """True if closed segments [a,b] and [c,d] share any point."""
    o1 = orientation(a, b, c)
    o2 = orientation(a, b, d)
    o3 = orientation(c, d, a)
    o4 = orientation(c, d, b)
    if o1 == 0 and point_on_segment(c, a, b):
        return True
    if o2 == 0 and point_on_segment(d, a, b):
        return True
    if o3 == 0 and point_on_segment(a, c, d):
        return True
    if o4 == 0 and point_on_segment(b, c, d):
        return True
    return ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0))
