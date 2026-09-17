"""Exact polyline transects through validated multi-polygon groups.

For every raw polyline segment ``p[i] -> p[i+1]`` an event sweep is run
against the *active* rings of each group (exterior rings and non-nested hole
rings), matching the winding / set-difference semantics of the overlap engine
in :mod:`app.geometry.arrangement`.

Two kinds of interaction are distinguished:

* a positive-length **collinear overlap** with a ring edge becomes a boundary
  interval (a run along the boundary);
* every other common point (proper crossings, T-junctions, vertex tangencies,
  segment endpoints lying on the boundary) becomes an isolated contact.

All cut parameters and contact coordinates are reduced
:class:`fractions.Fraction` values -- no floating point is ever used.  The
resulting intervals form an ordered, gap- and overlap-free partition of
``[0, 1]``; isolated contacts additionally carry the relation immediately
before, at and after the contact.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Sequence, Set, Tuple

from .arrangement import active_rings
from .rationals import (
    Point,
    cross,
    int_point,
    point_in_interior,
    point_on_segment,
)
from .validation import Polygon

ZERO = Fraction(0)
ONE = Fraction(1)

OUTSIDE = "outside"
INSIDE = "inside"
BOUNDARY = "boundary"

# A relation triple is (before, at, after); the missing side of a contact at a
# segment endpoint is ``None``.
RelationTriple = Tuple[Optional[str], str, Optional[str]]


@dataclass(frozen=True)
class Interval:
    """A positive-length parameter interval with a constant relation pair."""

    t0: Fraction
    t1: Fraction
    a: str
    b: str


@dataclass(frozen=True)
class Event:
    """A sweep cut: the polyline meets a boundary of at least one group here."""

    t: Fraction
    point: Point
    a: str
    b: str


@dataclass(frozen=True)
class Contact:
    """An isolated (zero-length) boundary point with its surrounding relations."""

    t: Fraction
    point: Point
    a: RelationTriple
    b: RelationTriple


@dataclass(frozen=True)
class SegmentTransect:
    index: int
    start: Tuple[int, int]
    end: Tuple[int, int]
    intervals: List[Interval]
    events: List[Event]
    contacts: List[Contact]


def _point_on_ring(p: Point, ring: Sequence[Point]) -> bool:
    n = len(ring)
    for i in range(n):
        if point_on_segment(p, ring[i], ring[(i + 1) % n]):
            return True
    return False


class _Region:
    """Point classification for one validated multi-polygon group."""

    __slots__ = ("polygons", "boundary_rings")

    def __init__(self, polygons: Sequence[Polygon]) -> None:
        self.polygons = tuple(polygons)
        # Only active rings are part of the material region's boundary: a hole
        # nested strictly inside another hole contributes no boundary.
        self.boundary_rings: List[Sequence[Point]] = []
        for poly in self.polygons:
            for ring, _semantic in active_rings(poly):
                self.boundary_rings.append(ring.points)

    def status(self, p: Point) -> str:
        # Boundary is checked across every polygon first.  Group validation
        # forbids rings of distinct polygons to touch, so a point can be on at
        # most one polygon's boundary.
        for ring in self.boundary_rings:
            if _point_on_ring(p, ring):
                return BOUNDARY
        for poly in self.polygons:
            if point_in_interior(p, poly.exterior.points):
                # Material = inside exterior minus the union of all holes.  A
                # point inside a nested (inactive) hole is inside its active
                # parent hole as well and is outside material either way.
                for hole in poly.holes:
                    if point_in_interior(p, hole.points):
                        return OUTSIDE
                return INSIDE
        return OUTSIDE


def _merge_runs(
    runs: List[Tuple[Fraction, Fraction]],
) -> List[Tuple[Fraction, Fraction]]:
    """Union closed intervals; runs that merely touch at an endpoint merge."""
    if not runs:
        return []
    ordered = sorted(runs)
    merged: List[List[Fraction]] = [list(ordered[0])]
    for lo, hi in ordered[1:]:
        if lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def _scan_segment(
    rings: Sequence[Sequence[Point]], a: Point, b: Point
) -> Tuple[List[Tuple[Fraction, Fraction]], Set[Fraction]]:
    """Sweep one polyline segment a->b against one group's active rings.

    Returns ``(runs, contacts)``: merged positive-length collinear boundary
    runs and zero-length contact parameters not lying on (or at an endpoint
    of) a run.
    """
    rx, ry = b[0] - a[0], b[1] - a[1]
    r2 = rx * rx + ry * ry  # > 0: consecutive path points are distinct
    raw_runs: List[Tuple[Fraction, Fraction]] = []
    touches: Set[Fraction] = set()

    for ring in rings:
        n = len(ring)
        for i in range(n):
            c = ring[i]
            d = ring[(i + 1) % n]
            sx, sy = d[0] - c[0], d[1] - c[1]
            cax, cay = c[0] - a[0], c[1] - a[1]
            denom = rx * sy - ry * sx

            if denom != 0:
                # Non-parallel: at most one common point.  Both parameters are
                # computed exactly; an endpoint/T contact and a proper crossing
                # are registered identically.
                t = (cax * sy - cay * sx) / denom
                if t < ZERO or t > ONE:
                    continue
                s = (cax * ry - cay * rx) / denom
                if ZERO <= s <= ONE:
                    touches.add(t)
                continue

            # Parallel: only a collinear edge can share a point.
            if cross(a, b, c) != 0:
                continue
            tc = (cax * rx + cay * ry) / r2
            td = ((d[0] - a[0]) * rx + (d[1] - a[1]) * ry) / r2
            if tc > td:
                tc, td = td, tc
            lo = tc if tc > ZERO else ZERO
            hi = td if td < ONE else ONE
            if lo > hi:
                continue
            if lo < hi:
                raw_runs.append((lo, hi))
            else:
                # Collinear edge meeting the segment in a single endpoint.
                touches.add(lo)

    runs = _merge_runs(raw_runs)
    points = {t for t in touches if not any(lo <= t <= hi for lo, hi in runs)}
    return runs, points


def _point_at(a: Point, b: Point, t: Fraction) -> Point:
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


def transect_polyline(
    group_a: Sequence[Polygon],
    group_b: Sequence[Polygon],
    path: Sequence[Tuple[int, int]],
) -> List[SegmentTransect]:
    """Split every raw path segment into exactly classified parameter pieces."""
    region_a = _Region(group_a)
    region_b = _Region(group_b)

    results: List[SegmentTransect] = []
    for seg_index in range(len(path) - 1):
        a = int_point(path[seg_index])
        b = int_point(path[seg_index + 1])

        runs_a, points_a = _scan_segment(region_a.boundary_rings, a, b)
        runs_b, points_b = _scan_segment(region_b.boundary_rings, a, b)

        # Unified event scan: every run endpoint and every isolated contact is
        # a cut for both groups.  A point contact with one group that happens
        # to lie on the other group's boundary run is retained: it is still an
        # isolated contact for that group and may change its relation.
        cut_set: Set[Fraction] = {ZERO, ONE}
        for runs in (runs_a, runs_b):
            for lo, hi in runs:
                cut_set.add(lo)
                cut_set.add(hi)
        cut_set.update(points_a)
        cut_set.update(points_b)
        cuts = sorted(cut_set)

        # Classify each atomic span at its exact rational midpoint.  A span
        # never partially overlaps a run, so a midpoint on a ring means the
        # whole span is a boundary run.
        span_labels: List[Tuple[str, str]] = []
        intervals: List[Interval] = []
        for k in range(len(cuts) - 1):
            t0, t1 = cuts[k], cuts[k + 1]
            mid = (t0 + t1) / 2
            mp = _point_at(a, b, mid)
            label = (region_a.status(mp), region_b.status(mp))
            span_labels.append(label)
            intervals.append(Interval(t0, t1, label[0], label[1]))

        # Events: every interior cut, plus segment endpoints that lie on a
        # boundary (path vertices sitting on the boundary).
        events: List[Event] = []
        for t in cuts:
            point = _point_at(a, b, t)
            stat_a = region_a.status(point)
            stat_b = region_b.status(point)
            if ZERO < t < ONE or stat_a == BOUNDARY or stat_b == BOUNDARY:
                events.append(Event(t, point, stat_a, stat_b))

        # Isolated contacts, enriched with before/at/after relations.
        contacts: List[Contact] = []
        for t in sorted(points_a | points_b):
            k = cuts.index(t)
            point = _point_at(a, b, t)
            at_a = region_a.status(point)
            at_b = region_b.status(point)
            before = span_labels[k - 1] if k > 0 else None
            after = span_labels[k] if k < len(cuts) - 1 else None

            def triple(at: str, side: int) -> RelationTriple:
                return (
                    None if before is None else before[side],
                    at,
                    None if after is None else after[side],
                )

            contacts.append(
                Contact(
                    t,
                    point,
                    triple(at_a, 0),
                    triple(at_b, 1),
                )
            )

        results.append(
            SegmentTransect(
                index=seg_index,
                start=(int(path[seg_index][0]), int(path[seg_index][1])),
                end=(int(path[seg_index + 1][0]), int(path[seg_index + 1][1])),
                intervals=intervals,
                events=events,
                contacts=contacts,
            )
        )

    return results
