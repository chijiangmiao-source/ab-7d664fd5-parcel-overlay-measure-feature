"""Exact crossing profiles (transects) of a polyline through polygon groups.

Given an ordered polyline and the two validated multi-polygon groups, every
original polyline segment is split at *all* of its boundary contacts: proper
crossings, vertex / T-junction contacts, isolated tangencies, hole crossings
and collinear-overlap endpoints.  Each resulting open piece is classified for
each group as ``inside``, ``outside`` or ``boundary``; contact instants become
zero-length point intervals carrying per-group before/at/after relations.

Every intersection parameter is a :class:`fractions.Fraction`; states of open
pieces are derived with the same exact rational predicates used for validation
(point containment / point-on-segment), so vertex tangencies, fold vertices,
paths through holes and paths running along a boundary are all handled without
a special crossing-sign case.  Fractional intersections are never converted to
floating point.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .arrangement import active_rings
from .rationals import (
    Point,
    bboxes_disjoint,
    int_point,
    point_in_interior,
    point_on_segment,
)
from .validation import Polygon, Ring

ZERO = Fraction(0)
ONE = Fraction(1)

OUTSIDE = "outside"
INSIDE = "inside"
BOUNDARY = "boundary"

EXTERIOR = "exterior"
HOLE = "hole"


# ---------------------------------------------------------------------------
# Result structures (geometry layer; Fraction throughout, no JSON types)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Contact:
    """A single ring touched by the polyline at one parameter instant."""

    polygon: int
    role: str  # "exterior" | "hole"
    hole_index: Optional[int]


@dataclass(frozen=True)
class Event:
    """Before/at/after relation for one group at an isolated contact."""

    group: int  # 0 -> a, 1 -> b
    before: str
    after: str
    contacts: Tuple[Contact, ...]


@dataclass(frozen=True)
class PointInterval:
    """A zero-length interval at a contact instant."""

    t: Fraction
    states: Tuple[str, str]
    events: Tuple[Event, ...]


@dataclass(frozen=True)
class RangeInterval:
    """An open piece between two consecutive cut parameters."""

    start: Fraction
    end: Fraction
    states: Tuple[str, str]


IntervalItem = Union[PointInterval, RangeInterval]


@dataclass(frozen=True)
class SegmentProfile:
    """Ordered, gap-free profile of one original polyline segment."""

    index: int
    items: Tuple[IntervalItem, ...]


# ---------------------------------------------------------------------------
# Group indexing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _RingRef:
    polygon: int
    role: str
    hole_index: Optional[int]
    ring: Ring


def _group_refs(polys: Sequence[Polygon]) -> List[_RingRef]:
    """All semantically active rings of a group with stable reporting indices.

    Reuses :func:`app.geometry.arrangement.active_rings` so that a hole nested
    inside another hole contributes no boundary, matching overlap semantics
    (exterior minus the union of holes).
    """
    refs: List[_RingRef] = []
    for pi, poly in enumerate(polys):
        hole_index = {id(h): k for k, h in enumerate(poly.holes)}
        for ring, _semantic in active_rings(poly):
            if ring is poly.exterior:
                refs.append(_RingRef(pi, EXTERIOR, None, ring))
            else:
                refs.append(_RingRef(pi, HOLE, hole_index[id(ring)], ring))
    return refs


def _group_parts(
    polys: Sequence[Polygon],
) -> List[Tuple[Ring, Tuple[Ring, ...]]]:
    """(exterior, active holes) per polygon for midpoint classification."""
    parts: List[Tuple[Ring, Tuple[Ring, ...]]] = []
    for poly in polys:
        holes = tuple(
            ring for ring, semantic in active_rings(poly) if semantic < 0
        )
        parts.append((poly.exterior, holes))
    return parts


# ---------------------------------------------------------------------------
# Exact segment / ring contact parameters
# ---------------------------------------------------------------------------

def _edge_contact_params(p0: Point, p1: Point, a: Point, b: Point) -> List[Fraction]:
    """Parameters t in [0,1] where segment p0->p1 meets ring edge a->b.

    Returns one parameter for a point contact (proper crossing, T-junction,
    endpoint touch) and both endpoints of an open collinear overlap.  All
    values are reduced fractions; an empty list means the segments are apart.
    """
    rx, ry = p1[0] - p0[0], p1[1] - p0[1]
    ex, ey = b[0] - a[0], b[1] - a[1]
    denom = rx * ey - ry * ex

    if denom != 0:
        apx, apy = a[0] - p0[0], a[1] - p0[1]
        t = (apx * ey - apy * ex) / denom
        if t < ZERO or t > ONE:
            return []
        u = (apx * ry - apy * rx) / denom
        if u < ZERO or u > ONE:
            return []
        return [t]

    # Parallel: only a collinear edge can share a point with the segment.
    if rx * (a[1] - p0[1]) - ry * (a[0] - p0[0]) != 0:
        return []

    r2 = rx * rx + ry * ry  # > 0: consecutive polyline points are distinct
    ta = ((a[0] - p0[0]) * rx + (a[1] - p0[1]) * ry) / r2
    tb = ((b[0] - p0[0]) * rx + (b[1] - p0[1]) * ry) / r2
    lo, hi = (ta, tb) if ta <= tb else (tb, ta)
    lo = max(ZERO, lo)
    hi = min(ONE, hi)
    if lo > hi:
        return []
    if lo == hi:
        return [lo]
    return [lo, hi]


def _on_ring(point: Point, ring: Ring) -> bool:
    pts = ring.points
    n = len(pts)
    for i in range(n):
        if point_on_segment(point, pts[i], pts[(i + 1) % n]):
            return True
    return False


def _state_at(point: Point,
              parts: Sequence[Tuple[Ring, Tuple[Ring, ...]]]) -> str:
    """outside / inside / boundary of one group's material region."""
    for exterior, holes in parts:
        if _on_ring(point, exterior) or any(_on_ring(point, h) for h in holes):
            return BOUNDARY
    for exterior, holes in parts:
        if point_in_interior(point, exterior.points):
            if any(point_in_interior(point, h.points) for h in holes):
                continue
            return INSIDE
    return OUTSIDE


# ---------------------------------------------------------------------------
# Event scan
# ---------------------------------------------------------------------------

def _collect_contacts(
    p0: Point, p1: Point, refs: Sequence[_RingRef], group: int,
    contacts: Dict[Fraction, Tuple[List[_RingRef], List[_RingRef]]],
) -> None:
    """Register every ring contact of segment p0->p1 as a cut parameter."""
    for ref in refs:
        ring = ref.ring
        pts = ring.points
        n = len(pts)
        # A vertex contact is found from two adjacent ring edges; the set
        # records each (ring, parameter) only once.
        touched: set = set()
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            if bboxes_disjoint(p0, p1, a, b):
                continue
            for t in _edge_contact_params(p0, p1, a, b):
                touched.add(t)
        for t in touched:
            contacts.setdefault(t, ([], []))[group].append(ref)


def _contact_sort_key(ref: _RingRef) -> Tuple[int, int, int]:
    role_rank = 0 if ref.role == EXTERIOR else 1
    hole = ref.hole_index if ref.hole_index is not None else 0
    return (ref.polygon, role_rank, hole)


def _as_contacts(refs: Sequence[_RingRef]) -> Tuple[Contact, ...]:
    return tuple(
        Contact(polygon=ref.polygon, role=ref.role, hole_index=ref.hole_index)
        for ref in sorted(refs, key=_contact_sort_key)
    )


def line_transect(
    path: Sequence[Tuple[int, int]],
    group_a: Sequence[Polygon],
    group_b: Sequence[Polygon],
) -> List[SegmentProfile]:
    """Split every polyline segment at all group-boundary contacts."""
    points = [int_point(p) for p in path]
    refs_by_group = [_group_refs(group_a), _group_refs(group_b)]
    parts_by_group = [_group_parts(group_a), _group_parts(group_b)]

    profiles: List[SegmentProfile] = []
    for seg_index in range(len(points) - 1):
        p0, p1 = points[seg_index], points[seg_index + 1]
        rx, ry = p1[0] - p0[0], p1[1] - p0[1]

        # t -> (rings of group a touched at t, rings of group b touched at t)
        contacts: Dict[
            Fraction, Tuple[List[_RingRef], List[_RingRef]]
        ] = {}
        _collect_contacts(p0, p1, refs_by_group[0], 0, contacts)
        _collect_contacts(p0, p1, refs_by_group[1], 1, contacts)

        cuts = sorted(set(contacts) | {ZERO, ONE})

        # Classify every open piece at its exact midpoint: no midpoint can lie
        # on a boundary, since every boundary contact parameter is a cut.
        piece_states: List[Tuple[str, str]] = []
        for i in range(len(cuts) - 1):
            tm = (cuts[i] + cuts[i + 1]) / 2
            mid = (p0[0] + tm * rx, p0[1] + tm * ry)
            piece_states.append(
                (
                    _state_at(mid, parts_by_group[0]),
                    _state_at(mid, parts_by_group[1]),
                )
            )

        def status_at(group: int, cut_index: int) -> str:
            touched = contacts.get(cuts[cut_index], ([], []))[group]
            if touched:
                return BOUNDARY
            if cut_index < len(piece_states):
                return piece_states[cut_index][group]
            return piece_states[cut_index - 1][group]

        items: List[IntervalItem] = []
        last = len(cuts) - 1
        for j, t in enumerate(cuts):
            touched_a, touched_b = contacts.get(t, ([], []))

            if touched_a or touched_b:
                events: List[Event] = []
                for group, touched in ((0, touched_a), (1, touched_b)):
                    if not touched:
                        continue
                    if j == 0:
                        before = BOUNDARY
                    else:
                        before = piece_states[j - 1][group]
                    if j == last:
                        after = BOUNDARY
                    else:
                        after = piece_states[j][group]
                    events.append(
                        Event(
                            group=group,
                            before=before,
                            after=after,
                            contacts=_as_contacts(touched),
                        )
                    )
                items.append(
                    PointInterval(
                        t=t,
                        states=(status_at(0, j), status_at(1, j)),
                        events=tuple(events),
                    )
                )

            if j < last:
                items.append(
                    RangeInterval(
                        start=t,
                        end=cuts[j + 1],
                        states=piece_states[j],
                    )
                )

        profiles.append(SegmentProfile(index=seg_index, items=tuple(items)))

    return profiles
