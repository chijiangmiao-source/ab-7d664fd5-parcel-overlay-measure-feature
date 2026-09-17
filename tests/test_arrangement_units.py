"""Direct unit tests for arrangement internals."""

from __future__ import annotations

from fractions import Fraction as F

from app.geometry.arrangement import (
    ONE,
    ZERO,
    _RawEdge,
    _angle_cmp,
    _register_intersections,
)
from app.geometry.rationals import P


def _cuts_of(e: _RawEdge):
    return sorted(e.cuts)


def test_proper_cross_registers_fractional_cuts():
    e = _RawEdge(P(0, 0), P(3, 3), 0, 1)
    f = _RawEdge(P(0, 3), P(3, 0), 1, 1)
    _register_intersections(e, f)
    assert _cuts_of(e) == [ZERO, F(1, 2), ONE]
    assert _cuts_of(f) == [ZERO, F(1, 2), ONE]
    assert e.cuts[F(1, 2)] == (F(3, 2), F(3, 2))


def test_t_junction_cuts_one_edge_only():
    e = _RawEdge(P(0, 0), P(4, 0), 0, 1)
    f = _RawEdge(P(2, 0), P(2, 2), 1, 1)
    _register_intersections(e, f)
    assert _cuts_of(e) == [ZERO, F(1, 2), ONE]
    assert _cuts_of(f) == [ZERO, ONE]  # touch at f's endpoint


def test_collinear_overlap_cuts_both():
    e = _RawEdge(P(0, 0), P(4, 0), 0, 1)
    f = _RawEdge(P(2, 0), P(6, 0), 1, 1)
    _register_intersections(e, f)
    assert _cuts_of(e) == [ZERO, F(1, 2), ONE]
    assert _cuts_of(f) == [ZERO, F(1, 2), ONE]  # e ends at f's midpoint


def test_collinear_disjoint_registers_nothing():
    e = _RawEdge(P(0, 0), P(1, 0), 0, 1)
    f = _RawEdge(P(2, 0), P(3, 0), 1, 1)
    _register_intersections(e, f)
    assert _cuts_of(e) == [ZERO, ONE]
    assert _cuts_of(f) == [ZERO, ONE]


def test_parallel_non_collinear_registers_nothing():
    e = _RawEdge(P(0, 0), P(4, 0), 0, 1)
    f = _RawEdge(P(0, 1), P(4, 1), 1, 1)
    _register_intersections(e, f)
    assert _cuts_of(e) == [ZERO, ONE]


def test_non_parallel_miss_registers_nothing():
    e = _RawEdge(P(0, 0), P(1, 1), 0, 1)
    f = _RawEdge(P(2, 0), P(3, 1), 1, 1)
    _register_intersections(e, f)
    assert _cuts_of(e) == [ZERO, ONE]


def test_angle_cmp_ordering():
    # half-plane split then cross product.
    assert _angle_cmp(P(1, 0), P(0, 1)) < 0
    assert _angle_cmp(P(0, 1), P(1, 0)) > 0
    assert _angle_cmp(P(-1, 0), P(0, -1)) < 0
    assert _angle_cmp(P(1, 0), P(-1, 0)) < 0
    assert _angle_cmp(P(2, 0), P(1, 0)) == 0
    assert _angle_cmp(P(1, 1), P(2, 2)) == 0
    # Within one half-plane, clockwise order: u at +x vs v pointing up-right.
    assert _angle_cmp(P(1, 0), P(1, 1)) < 0
    assert _angle_cmp(P(1, 1), P(1, 0)) > 0
