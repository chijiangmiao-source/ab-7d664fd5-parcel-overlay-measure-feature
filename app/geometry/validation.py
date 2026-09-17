"""Structural validation of multi-polygon groups.

All rules that make a request unprocessable are collected here and raised as
:class:`GeometryValidationError` (mapped to HTTP 422).  Validation works
exclusively with exact integer/rational arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .rationals import (
    Point,
    bboxes_disjoint,
    int_point,
    point_in_interior,
    ring_self_intersections,
    ring_signed_area2,
    segments_intersect,
)


class GeometryValidationError(ValueError):
    """Raised when a geometry violates the documented well-formedness rules."""

    def __init__(self, message: str, *, loc: Tuple[str | int, ...] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.loc = loc


@dataclass(frozen=True)
class Ring:
    """A simple ring of exact rational points, normalised by orientation."""

    points: Tuple[Point, ...]
    is_hole: bool
    ccw: bool  # whether stored points run counter-clockwise


@dataclass(frozen=True)
class Polygon:
    exterior: Ring
    holes: Tuple[Ring, ...]


def build_ring(raw: Sequence[Sequence[int]], *, is_hole: bool) -> Ring:
    pts = tuple(int_point((int(v[0]), int(v[1]))) for v in raw)

    if len(pts) < 3:
        raise GeometryValidationError(
            f"ring must contain at least 3 vertices, got {len(pts)}",
            loc=("holes",) if is_hole else ("exterior",),
        )

    # First/last repetition and any other repeated vertex make the ring
    # non-simple; the API contract explicitly forbids the closing duplicate.
    if len(set(pts)) != len(pts):
        raise GeometryValidationError(
            "ring contains repeated vertices (do not repeat the first vertex "
            "at the end)",
            loc=("holes",) if is_hole else ("exterior",),
        )

    if ring_self_intersections(pts):
        raise GeometryValidationError(
            "ring is not simple: non-adjacent edges cross or touch",
            loc=("holes",) if is_hole else ("exterior",),
        )

    signed = ring_signed_area2(pts)
    if signed == 0:
        raise GeometryValidationError(
            "ring encloses zero area",
            loc=("holes",) if is_hole else ("exterior",),
        )

    ccw = signed > 0
    return Ring(points=pts, is_hole=is_hole, ccw=ccw)


def ring_edges(ring: Ring):
    pts = ring.points
    n = len(pts)
    for i in range(n):
        yield pts[i], pts[(i + 1) % n]


def rings_touch(r1: Ring, r2: Ring) -> bool:
    """True if two ring boundaries share any point."""
    e1 = list(ring_edges(r1))
    e2 = list(ring_edges(r2))
    for a, b in e1:
        for c, d in e2:
            if bboxes_disjoint(a, b, c, d):
                continue
            if segments_intersect(a, b, c, d):
                return True
    return False


def build_polygon(raw_exterior: Sequence[Sequence[int]],
                  raw_holes: Sequence[Sequence[Sequence[int]]]) -> Polygon:
    exterior = build_ring(raw_exterior, is_hole=False)

    holes: List[Ring] = []
    for k, raw_hole in enumerate(raw_holes):
        hole = build_ring(raw_hole, is_hole=True)

        # Every hole vertex must be strictly inside the exterior ring ...
        for p in hole.points:
            if not point_in_interior(p, exterior.points):
                raise GeometryValidationError(
                    "hole must lie strictly inside its exterior ring "
                    "(boundary contact is not allowed)",
                    loc=("holes", k),
                )
        # ... which together with no boundary crossing guarantees full
        # containment (an edge could otherwise poke out between two vertices).
        if rings_touch(hole, exterior):
            raise GeometryValidationError(
                "hole boundary must not touch the exterior ring",
                loc=("holes", k),
            )

        # Holes must not touch one another.  (Strict nesting without contact
        # is accepted; the area engine treats holes via set difference.)
        for h, prior in enumerate(holes):
            if rings_touch(hole, prior):
                raise GeometryValidationError(
                    f"holes {h} and {k} touch or intersect",
                    loc=("holes", k),
                )
        holes.append(hole)

    return Polygon(exterior=exterior, holes=tuple(holes))


def validate_group(polys: Sequence[Polygon], group_name: str) -> None:
    """Polygons of one group must have disjoint interiors and must not touch.

    A polygon's region boundary is the union of all its rings.  Therefore any
    contact between any two rings of two polygons is forbidden.  With mutually
    disjoint boundaries, two non-empty regions can overlap only through
    containment, which is detected through a representative vertex.
    """

    def in_material_region(p: Point, poly: Polygon) -> bool:
        if not point_in_interior(p, poly.exterior.points):
            return False
        return not any(point_in_interior(p, h.points) for h in poly.holes)

    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            p1, p2 = polys[i], polys[j]
            rings1 = [p1.exterior, *p1.holes]
            rings2 = [p2.exterior, *p2.holes]
            for r1 in rings1:
                for r2 in rings2:
                    if rings_touch(r1, r2):
                        raise GeometryValidationError(
                            "polygons in one group must not intersect or touch",
                            loc=(group_name,),
                        )

            # Boundaries are disjoint: reject material containment in either
            # direction.  A polygon sitting inside the other's hole is fine:
            # its vertex then lies in a hole, i.e. outside the material region.
            if in_material_region(p1.exterior.points[0], p2):
                raise GeometryValidationError(
                    "polygons in one group must not intersect or touch",
                    loc=(group_name,),
                )
            if in_material_region(p2.exterior.points[0], p1):
                raise GeometryValidationError(
                    "polygons in one group must not intersect or touch",
                    loc=(group_name,),
                )
