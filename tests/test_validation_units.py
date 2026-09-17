"""Direct unit tests for the structural validation layer."""

from __future__ import annotations

import pytest

from app.geometry.validation import (
    GeometryValidationError,
    build_polygon,
    build_ring,
    validate_group,
)
from app.models import PolygonIn
from app.service import build_group


def test_ring_with_too_few_vertices_rejected():
    with pytest.raises(GeometryValidationError):
        build_ring([(0, 0), (1, 1)], is_hole=False)


def test_collinear_zero_area_ring_rejected():
    with pytest.raises(GeometryValidationError):
        build_ring([(0, 0), (1, 0), (2, 0)], is_hole=False)


def test_repeated_vertex_rejected_directly():
    with pytest.raises(GeometryValidationError, match="repeated"):
        build_ring([(0, 0), (2, 0), (2, 0)], is_hole=True)
    with pytest.raises(GeometryValidationError, match="repeated"):
        build_ring([(0, 0), (2, 0), (2, 2), (0, 0)], is_hole=False)


def test_ring_touching_nonadjacent_edges_rejected():
    # Two non-adjacent edges meet at a vertex.
    ring = [(0, 0), (3, 0), (3, 3), (1, 3), (1, 1), (2, 1), (2, 2), (0, 2)]
    with pytest.raises(GeometryValidationError):
        build_ring(ring, is_hole=False)


def test_hole_edge_crossing_exterior_rejected():
    # U-shaped (concave) exterior: every hole vertex is strictly inside the
    # material region, but its horizontal edges shortcut across the notch and
    # cross the exterior boundary.
    exterior = [(0, 0), (6, 0), (6, 6), (4, 6), (4, 2), (2, 2), (2, 6),
                (0, 6)]
    with pytest.raises(GeometryValidationError, match="touch the exterior"):
        build_polygon(exterior, [[(1, 4), (5, 4), (5, 5), (1, 5)]])


def test_group_polygon_nested_in_material_rejected():
    outer = PolygonIn(exterior=[(0, 0), (6, 0), (6, 6), (0, 6)])
    inner = PolygonIn(exterior=[(1, 1), (2, 1), (2, 2), (1, 2)])
    with pytest.raises(GeometryValidationError):
        build_group([outer, inner], "a")


def test_group_polygon_nested_in_material_reversed_rejected():
    outer = PolygonIn(exterior=[(0, 0), (6, 0), (6, 6), (0, 6)])
    inner = PolygonIn(exterior=[(1, 1), (2, 1), (2, 2), (1, 2)])
    with pytest.raises(GeometryValidationError):
        build_group([inner, outer], "a")


def test_validate_group_accepts_polygon_in_hole():
    g = build_group(
        [
            PolygonIn(
                exterior=[(0, 0), (10, 0), (10, 10), (0, 10)],
                holes=[[(3, 3), (7, 3), (7, 7), (3, 7)]],
            ),
            PolygonIn(exterior=[(4, 4), (6, 4), (6, 6), (4, 6)]),
        ],
        "a",
    )
    assert len(g) == 2


def test_error_carries_location():
    try:
        build_polygon(
            [(0, 0), (4, 0), (4, 4), (0, 4)],
            [[(5, 5), (6, 5), (6, 6), (5, 6)]],
        )
    except GeometryValidationError as exc:
        assert exc.loc == ("holes", 0)
        assert "strictly inside" in exc.message
    else:  # pragma: no cover
        raise AssertionError("expected GeometryValidationError")
