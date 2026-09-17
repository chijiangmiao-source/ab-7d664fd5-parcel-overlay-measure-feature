"""Unit tests for exact rational primitives and the service helpers."""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.geometry.rationals import (
    P,
    cross,
    orientation,
    point_in_interior,
    point_in_ring,
    point_on_segment,
    proper_intersection,
    ring_self_intersections,
    ring_signed_area2,
    segments_intersect,
)
from app.service import round_half_up_thirds


SQ = [P(0, 0), P(4, 0), P(4, 4), P(0, 4)]


def test_orientation_exact():
    assert orientation(P(0, 0), P(1, 0), P(1, 1)) == 1
    assert orientation(P(0, 0), P(1, 0), P(1, -1)) == -1
    assert orientation(P(0, 0), P(2, 0), P(1, 0)) == 0


def test_cross_integer_no_float():
    v = cross(P(1, 1), P(3, 2), P(2, 5))
    assert isinstance(v, Fraction)
    assert v == 7


def test_point_on_segment():
    assert point_on_segment(P(1, 1), P(0, 0), P(3, 3))
    assert point_on_segment(P(0, 0), P(0, 0), P(0, 4))
    assert not point_on_segment(P(1, 2), P(0, 0), P(3, 3))
    assert not point_on_segment(P(4, 4), P(0, 0), P(3, 3))


def test_proper_intersection_is_fraction():
    p = proper_intersection(P(0, 0), P(3, 3), P(0, 3), P(3, 0))
    assert p == (Fraction(3, 2), Fraction(3, 2))
    assert all(isinstance(c, Fraction) for c in p)


def test_ring_area_signed():
    assert ring_signed_area2(SQ) == 32
    assert ring_signed_area2(list(reversed(SQ))) == -32


def test_point_in_ring_variants():
    assert point_in_ring(P(2, 2), SQ)
    assert point_in_ring(P(0, 2), SQ)          # boundary counts as in
    assert not point_in_ring(P(5, 2), SQ)

    assert point_in_interior(P(2, 2), SQ)
    assert not point_in_interior(P(0, 2), SQ)  # boundary excluded
    assert not point_in_interior(P(5, 2), SQ)


def test_ring_self_intersection_detection():
    bowtie = [P(0, 0), P(4, 4), P(4, 0), P(0, 4)]
    assert ring_self_intersections(bowtie)
    assert not ring_self_intersections(SQ)
    # Concave but simple ring.
    lshape = [P(0, 0), P(4, 0), P(4, 2), P(2, 2), P(2, 4), P(0, 4)]
    assert not ring_self_intersections(lshape)


def test_segments_intersect_cases():
    assert segments_intersect(P(0, 0), P(4, 4), P(0, 4), P(4, 0))      # diagonals
    assert segments_intersect(P(0, 2), P(4, 2), P(2, 0), P(2, 4))      # cross
    assert segments_intersect(P(0, 0), P(2, 0), P(1, 0), P(3, 0))      # collinear overlap
    assert segments_intersect(P(0, 0), P(2, 0), P(2, 0), P(2, 2))      # endpoint
    assert not segments_intersect(P(0, 0), P(1, 0), P(2, 0), P(3, 0))  # disjoint collinear
    assert not segments_intersect(P(0, 0), P(1, 1), P(2, 0), P(3, 1))  # parallel apart
    assert not segments_intersect(P(0, 0), P(2, 2), P(0, 3), P(1, 2))  # no crossing
    # Endpoint contacts through each of the four collinear branches.
    assert segments_intersect(P(0, 0), P(4, 0), P(2, 0), P(2, 1))  # c on ab
    assert segments_intersect(P(0, 0), P(4, 0), P(2, 1), P(2, 0))  # d on ab
    assert segments_intersect(P(2, 2), P(2, 0), P(0, 2), P(4, 2))  # a on cd
    assert segments_intersect(P(2, 0), P(2, 2), P(0, 2), P(4, 2))  # b on cd


@pytest.mark.parametrize(
    "value,expected",
    [
        (Fraction(0), "0.000"),
        (Fraction(1, 8000), "0.000"),       # 0.000125 -> 0.000
        (Fraction(1, 2000), "0.001"),       # 0.0005 -> half-up to 0.001
        (Fraction(1, 2), "0.500"),
        (Fraction(1, 3), "0.333"),
        (Fraction(2, 3), "0.667"),
        (Fraction(4999, 2000), "2.500"),    # 2.4995 -> 2.500
        (Fraction(1, 1000), "0.001"),
        (Fraction(10**9), "1000000000.000"),
    ],
)
def test_round_half_up_thirds(value, expected):
    assert round_half_up_thirds(value) == expected


def test_rounding_is_not_bankers():
    # Exactly .0005 must round UP, unlike Python's built-in round().
    assert round_half_up_thirds(Fraction(5, 10000)) == "0.001"
