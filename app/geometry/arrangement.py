"""Exact overlap area via a planar arrangement.

The two polygon groups are collections of oriented rings (exterior rings
counter-clockwise, holes clockwise) interpreted with winding-number semantics.
Every ring edge is split at all intersection / contact points, the resulting
atomic segments form a planar subdivision, and half-edge face walks recover
its boundary cycles.

Cycles are merged into planar faces (a face may carry an outer CCW cycle plus
CW hole cycles).  Crossing an atomic segment changes a group's winding number
by the signed contribution of its originating rings, so the winding numbers
of every face are obtained by propagation from the unbounded face.  The
overlap area is the signed-area sum over boundary cycles of faces whose
winding number is positive for *both* groups.

All coordinates and cut parameters are :class:`fractions.Fraction`; no
floating point is involved anywhere and the result is independent of the
order in which polygons, rings or vertices are supplied.
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from functools import cmp_to_key
from typing import Dict, List, Optional, Sequence, Tuple

from .rationals import Point, cross, point_on_segment, point_in_ring
from .validation import Polygon, Ring

ZERO = Fraction(0)
ONE = Fraction(1)


class _RawEdge:
    __slots__ = ("a", "b", "group", "winding", "cuts")

    def __init__(self, a: Point, b: Point, group: int, winding: int) -> None:
        self.a = a
        self.b = b
        self.group = group
        # Signed winding contribution when crossing this edge from right to
        # left relative to its stored direction (+1 CCW exterior, -1 hole).
        self.winding = winding
        # intersection parameter t -> point, with point = a + t*(b-a)
        self.cuts: Dict[Fraction, Point] = {ZERO: a, ONE: b}


def _ring_winding_sign(ring: Ring) -> int:
    """+1 when the stored vertex order of the ring is CCW, else -1."""
    return 1 if ring.ccw else -1


def active_rings(poly: Polygon) -> List[Tuple[Ring, int]]:
    """Rings bounding material area, as ``(ring, semantic)``.

    A hole nested strictly inside another hole contributes nothing under
    set-difference semantics (exterior minus the union of all holes).
    """
    active: List[Tuple[Ring, int]] = [(poly.exterior, +1)]
    for h, ring in enumerate(poly.holes):
        nested = any(
            k != h and point_in_ring(ring.points[0], poly.holes[k].points)
            for k in range(len(poly.holes))
        )
        if not nested:
            active.append((ring, -1))
    return active


def _polygon_edges(poly: Polygon, group: int) -> List[_RawEdge]:
    edges: List[_RawEdge] = []
    for ring, semantic in active_rings(poly):
        pts = ring.points
        n = len(pts)
        winding = semantic * _ring_winding_sign(ring)
        for i in range(n):
            edges.append(
                _RawEdge(pts[i], pts[(i + 1) % n], group, winding)
            )
    return edges


def _bboxes_disjoint(e: _RawEdge, f: _RawEdge) -> bool:
    return (
        max(e.a[0], e.b[0]) < min(f.a[0], f.b[0])
        or max(f.a[0], f.b[0]) < min(e.a[0], e.b[0])
        or max(e.a[1], e.b[1]) < min(f.a[1], f.b[1])
        or max(f.a[1], f.b[1]) < min(e.a[1], e.b[1])
    )


def _register_intersections(e: _RawEdge, f: _RawEdge) -> None:
    """Register every common point of two raw edges as cuts on both."""
    a, b = e.a, e.b
    c, d = f.a, f.b
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denom = rx * sy - ry * sx

    if denom != 0:
        cax, cay = c[0] - a[0], c[1] - a[1]
        t = (cax * sy - cay * sx) / denom
        if t < ZERO or t > ONE:
            return
        s = (cax * ry - cay * rx) / denom
        if s < ZERO or s > ONE:
            return
        if ZERO < t < ONE:
            e.cuts[t] = (a[0] + t * rx, a[1] + t * ry)
        if ZERO < s < ONE:
            f.cuts[s] = (c[0] + s * sx, c[1] + s * sy)
        return

    # Parallel: only collinear segments can share points.
    if cross(a, b, c) != 0 or cross(a, b, d) != 0:
        return

    r2 = rx * rx + ry * ry  # > 0: ring vertices are distinct
    tc = ((c[0] - a[0]) * rx + (c[1] - a[1]) * ry) / r2
    td = ((d[0] - a[0]) * rx + (d[1] - a[1]) * ry) / r2
    lo, hi = (tc, td) if tc <= td else (td, tc)
    lo = max(ZERO, lo)
    hi = min(ONE, hi)
    if lo > hi:
        return

    s2 = sx * sx + sy * sy  # > 0
    for t in (lo, hi):
        if ZERO < t < ONE:
            e.cuts[t] = (a[0] + t * rx, a[1] + t * ry)
        px = a[0] + t * rx - c[0]
        py = a[1] + t * ry - c[1]
        sp = (px * sx + py * sy) / s2
        if ZERO < sp < ONE:
            f.cuts[sp] = (c[0] + sp * sx, c[1] + sp * sy)


def _angle_cmp(u: Point, v: Point) -> int:
    """Compare direction vectors by polar angle, CCW starting at +x."""
    def half(p: Point) -> int:
        return 0 if (p[1] > 0 or (p[1] == 0 and p[0] >= 0)) else 1

    hu, hv = half(u), half(v)
    if hu != hv:
        return -1 if hu < hv else 1
    cr = u[0] * v[1] - u[1] * v[0]
    if cr > 0:
        return -1
    if cr < 0:
        return 1
    return 0


def _point_on_ring(p: Point, ring: Sequence[Point]) -> bool:
    n = len(ring)
    for i in range(n):
        if point_on_segment(p, ring[i], ring[(i + 1) % n]):
            return True
    return False


def overlap_area(group_a: Sequence[Polygon], group_b: Sequence[Polygon]) -> Fraction:
    raw_edges: List[_RawEdge] = []
    for poly in group_a:
        raw_edges.extend(_polygon_edges(poly, 0))
    for poly in group_b:
        raw_edges.extend(_polygon_edges(poly, 1))
    if not raw_edges:
        return ZERO

    # ---- Split every edge at all of its intersection / contact points. ----
    m = len(raw_edges)
    for i in range(m):
        ei = raw_edges[i]
        for j in range(i + 1, m):
            ej = raw_edges[j]
            if not _bboxes_disjoint(ei, ej):
                _register_intersections(ei, ej)

    # ---- Atomic segments, canonicalised so coincident pieces merge. --------
    # key (p, q) with p < q lexicographically -> aggregated tags
    # (group, winding delta in canonical direction)
    tag_map: Dict[Tuple[Point, Point], List[Tuple[int, int]]] = defaultdict(list)
    for e in raw_edges:
        params = sorted(e.cuts)
        for k in range(len(params) - 1):
            p1 = e.cuts[params[k]]
            p2 = e.cuts[params[k + 1]]
            if p1 < p2:
                key, aligned = (p1, p2), True
            else:
                key, aligned = (p2, p1), False
            delta = e.winding if aligned else -e.winding
            tag_map[key].append((e.group, delta))

    if not tag_map:  # pragma: no cover - every non-empty ring yields a segment
        return ZERO

    seg_keys = sorted(tag_map)
    n_seg = len(seg_keys)

    nodes: Dict[Point, int] = {}

    def node_id(p: Point) -> int:
        idx = nodes.get(p)
        if idx is None:
            idx = len(nodes)
            nodes[p] = idx
        return idx

    # Half-edges: 2k leaves node(p) towards node(q), 2k+1 is its twin.
    origin: List[int] = [0] * (2 * n_seg)
    outgoing: Dict[int, List[int]] = defaultdict(list)
    for k, (p, q) in enumerate(seg_keys):
        u, v = node_id(p), node_id(q)
        origin[2 * k] = u
        origin[2 * k + 1] = v
        outgoing[u].append(2 * k)
        outgoing[v].append(2 * k + 1)

    point_of = {idx: p for p, idx in nodes.items()}

    # ---- Face permutation: next half-edge keeping the face on the left. ----
    nxt: List[int] = [0] * (2 * n_seg)
    for u, hes in outgoing.items():
        def direction(he: int) -> Point:
            tail = point_of[origin[he ^ 1]]
            head = point_of[origin[he]]
            return (head[0] - tail[0], head[1] - tail[1])

        ordered = sorted(hes, key=cmp_to_key(
            lambda h1, h2: _angle_cmp(direction(h1), direction(h2))
        ))
        cnt = len(ordered)
        for r in range(cnt):
            # A dart entering u whose reverse ray is ordered[r] continues
            # along its immediate clockwise neighbour ordered[r - 1]: this
            # keeps the face on the dart's left, yielding CCW bounded cycles
            # and one CW cycle for the unbounded face.
            nxt[ordered[r] ^ 1] = ordered[(r - 1) % cnt]

    # ---- Enumerate boundary cycles (orbits of the face permutation). -------
    face_of: List[int] = [-1] * (2 * n_seg)
    cycles: List[List[int]] = []
    cycle_area2: List[Fraction] = []
    for start in range(2 * n_seg):
        if face_of[start] != -1:
            continue
        fid = len(cycles)
        he = start
        chain: List[int] = []
        area2 = ZERO
        while True:
            face_of[he] = fid
            chain.append(he)
            u = point_of[origin[he]]
            v = point_of[origin[he ^ 1]]
            area2 += u[0] * v[1] - v[0] * u[1]
            he = nxt[he]
            if he == start:
                break
        cycles.append(chain)
        cycle_area2.append(area2)
    n_cycles = len(cycles)

    # ---- Merge cycles into planar faces. ------------------------------------
    # Each geometric boundary is walked twice in opposite directions (once per
    # adjacent face): a CCW outer boundary and its CW twin.  Hence every
    # bounded face is owned by exactly one CCW cycle; CW cycles are hole
    # boundaries (the top-level CW cycle bounds the unbounded face).
    ccw_cycles = [c for c in range(n_cycles) if cycle_area2[c] > 0]
    cw_cycles = [c for c in range(n_cycles) if cycle_area2[c] < 0]
    cycle_ring = [[point_of[origin[he]] for he in cyc] for cyc in cycles]

    def innermost_ccw_container(c: int) -> Optional[int]:
        """Smallest CCW cycle strictly containing cycle c.

        The CCW twin of a CW cycle traces the same boundary: all tested
        vertices then lie on that ring, so it is skipped automatically.
        """
        best: Optional[int] = None
        best_area: Optional[Fraction] = None
        ring_c = cycle_ring[c]
        for x in ccw_cycles:
            ring_x = cycle_ring[x]
            inside: Optional[bool] = None
            for p in ring_c:
                if not _point_on_ring(p, ring_x):
                    inside = point_in_ring(p, ring_x)
                    break
            if inside is None or not inside:
                continue
            ax = cycle_area2[x]  # strictly nested CCW cycles shrink by area
            if best_area is None or ax < best_area:
                best, best_area = x, ax
        return best

    OUTER_FACE = -1
    face_of_cycle: List[int] = [0] * n_cycles
    face_owner: Dict[int, int] = {}
    next_face = 0
    for c in ccw_cycles:
        face_owner[c] = next_face
        face_of_cycle[c] = next_face
        next_face += 1
    for c in cw_cycles:
        owner = innermost_ccw_container(c)
        face_of_cycle[c] = OUTER_FACE if owner is None else face_owner[owner]

    # ---- Winding deltas per atomic segment. --------------------------------
    # Crossing canonical segment p->q from its right face to its left face
    # raises winding of group g by delta[g].
    delta: List[Tuple[int, int]] = [(0, 0)] * n_seg
    for k, key in enumerate(seg_keys):
        da = db = 0
        for group, d in tag_map[key]:
            if group == 0:
                da += d
            else:
                db += d
        delta[k] = (da, db)

    adjacency: Dict[int, List[Tuple[int, int, int]]] = defaultdict(list)
    winding: Dict[int, Tuple[int, int]] = {OUTER_FACE: (0, 0)}
    for k in range(n_seg):
        left = face_of_cycle[face_of[2 * k]]
        right = face_of_cycle[face_of[2 * k + 1]]
        da, db = delta[k]
        if left == right:
            # A slit would be required here; closed polygon arrangements
            # cannot produce one, so deltas must cancel.
            if da != 0 or db != 0:  # pragma: no cover - defensive
                raise RuntimeError("internal arrangement error: dangling edge")
            continue
        adjacency[right].append((left, da, db))   # winding[left] = right + d
        adjacency[left].append((right, -da, -db))

    # ---- Propagate exact winding numbers from the unbounded face. ----------
    stack = [OUTER_FACE]
    while stack:
        cur = stack.pop()
        wa, wb = winding[cur]
        for other, da, db in adjacency[cur]:
            candidate = (wa + da, wb + db)
            known = winding.get(other)
            if known is None:
                winding[other] = candidate
                stack.append(other)
            elif known != candidate:  # pragma: no cover - defensive
                raise RuntimeError("internal arrangement error: winding conflict")

    # ---- Sum signed areas of faces covered by both groups. -----------------
    total = ZERO
    for c in range(n_cycles):
        face = face_of_cycle[c]
        wa, wb = winding[face]
        if wa > 0 and wb > 0:
            total += cycle_area2[c] / 2
    return total
