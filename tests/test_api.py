"""Endpoint-level tests for the overlap API."""

from __future__ import annotations

import copy
import random


SQ4 = [(0, 0), (4, 0), (4, 4), (0, 4)]


def body(a, b=None):
    return {"a": a, "b": b if b is not None else a}


def poly(exterior, holes=None):
    return {"exterior": exterior, "holes": holes or []}


def assert_area(resp, numerator, denominator, decimal):
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["area_sq_mm"] == [numerator, denominator]
    assert data["numerator"] == numerator
    assert data["denominator"] == denominator
    assert data["decimal"] == decimal
    assert data["rounding"] == "half-up"
    assert data["units"] == "mm^2"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_simple_overlap(client):
    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly(SQ4)],
            [poly([(2, 0), (6, 0), (6, 4), (2, 4)])],
        ),
    )
    assert_area(resp, 8, 1, "8.000")


def test_fractional_area_is_reduced(client):
    # Two right triangles overlap in a triangle of area 1/2.
    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly([(0, 0), (3, 0), (0, 3)])],
            [poly([(1, 1), (4, 1), (1, 4)])],
        ),
    )
    assert_area(resp, 1, 2, "0.500")


def test_hole_deduction(client):
    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly(SQ4, [[(1, 1), (3, 1), (3, 3), (1, 3)]])],
            [poly(SQ4)],
        ),
    )
    assert_area(resp, 12, 1, "12.000")


def test_edge_and_point_contact_are_zero(client):
    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
            [poly([(1, 0), (2, 0), (2, 1), (1, 1)])],
        ),
    )
    assert_area(resp, 0, 1, "0.000")

    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
            [poly([(1, 1), (2, 1), (2, 2), (1, 2)])],
        ),
    )
    assert_area(resp, 0, 1, "0.000")


def test_empty_groups(client):
    resp = client.post("/api/v1/overlap", json={"a": [], "b": []})
    assert_area(resp, 0, 1, "0.000")


def test_one_empty_group(client):
    resp = client.post(
        "/api/v1/overlap",
        json=body([poly(SQ4)], []),
    )
    assert_area(resp, 0, 1, "0.000")


def test_half_up_rounding_boundaries(client):
    # Triangle area 1/8 = 0.125 exactly.
    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly([(0, 0), (1, 0), (0, 1)])],
            [poly([(0, 0), (1, 0), (0, 1)])],
        ),
    )
    assert_area(resp, 1, 2, "0.500")


def test_cross_group_touching_polygons_are_allowed(client):
    # Two polygons touching only at an edge ACROSS groups is legal overlap 0;
    # each group itself is valid (single polygon).
    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly([(0, 0), (2, 0), (2, 2), (0, 2)])],
            [poly([(2, 0), (4, 0), (4, 2), (2, 2)])],
        ),
    )
    assert_area(resp, 0, 1, "0.000")


def test_coordinate_range_bounds_accepted(client):
    resp = client.post(
        "/api/v1/overlap",
        json=body(
            [poly([(-1_000_000, -1_000_000), (0, -1_000_000),
                   (0, 0), (-1_000_000, 0)])],
            [poly([(-1_000_000, -1_000_000), (-999_999, -1_000_000),
                   (-999_999, -999_999), (-1_000_000, -999_999)])],
        ),
    )
    assert_area(resp, 1, 1, "1.000")


def _permuted_geometry(payload, seed):
    rng = random.Random(seed)
    p = copy.deepcopy(payload)
    rng.shuffle(p["a"])
    rng.shuffle(p["b"])
    for group in (p["a"], p["b"]):
        for polygon in group:
            for ring in [polygon["exterior"], *polygon["holes"]]:
                if rng.random() < 0.5:
                    ring.reverse()
                else:
                    # Rotate the vertex list (same polygon, different start).
                    k = rng.randrange(len(ring))
                    ring[:] = ring[k:] + ring[:k]
    return p


def test_result_is_input_order_independent(client):
    payload = body(
        [
            poly([(0, 0), (5, 0), (5, 3), (0, 3)],
                 [[(1, 1), (2, 1), (2, 2), (1, 2)]]),
            poly([(7, -1), (9, -1), (9, 4), (7, 4)]),
        ],
        [
            poly([(2, 1), (8, 1), (8, 2), (2, 2)]),
            poly([(-2, -2), (-1, -2), (-1, -1), (-2, -1)]),
        ],
    )
    resp = client.post("/api/v1/overlap", json=payload)
    assert resp.status_code == 200, resp.text
    expected = resp.json()["area_sq_mm"]
    for seed in range(12):
        resp = client.post(
            "/api/v1/overlap", json=_permuted_geometry(payload, seed)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["area_sq_mm"] == expected


def test_orientation_winding_agnostic(client):
    # CW exterior rings and CCW holes must mean the same geometry.
    cw_square = list(reversed(SQ4))
    cw_hole = list(reversed([(1, 1), (3, 1), (3, 3), (1, 3)]))
    resp = client.post(
        "/api/v1/overlap",
        json=body([poly(cw_square, [cw_hole])], [poly(SQ4)]),
    )
    assert_area(resp, 12, 1, "12.000")


def test_concave_multiple_crossings(client):
    # Rectangle with two square notches cut from its top edge; a horizontal
    # band crosses the notches, entering/leaving material multiple times.
    notched = [(0, 0), (10, 0), (10, 4), (8, 4), (8, 2), (6, 2),
               (6, 4), (4, 4), (4, 2), (2, 2), (2, 4), (0, 4)]
    band = [(1, -1), (9, -1), (9, 3), (1, 3)]
    resp = client.post(
        "/api/v1/overlap",
        json=body([poly(notched)], [poly(band)]),
    )
    # y in [0,2]: width 8 -> 16; y in [2,3]: teeth widths 1+2+1 = 4 -> 4.
    assert_area(resp, 20, 1, "20.000")


def test_geometry_error_location_is_reported(client):
    bowtie = [(0, 0), (4, 4), (4, 0), (0, 4)]
    resp = client.post(
        "/api/v1/overlap",
        json=body([poly([(0, 0), (1, 0), (1, 1), (0, 1)]), poly(bowtie)],
                  [poly([(0, 0), (1, 0), (1, 1), (0, 1)])]),
    )
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert details[0]["loc"][:2] == ["a", 1]
