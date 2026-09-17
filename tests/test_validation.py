"""Tests for 422 validation failures and structured error bodies."""

from __future__ import annotations

import pytest


def poly(exterior, holes=None):
    return {"exterior": exterior, "holes": holes or []}


def post(client, a, b):
    return client.post("/api/v1/overlap", json={"a": a, "b": b})


def assert_422(resp):
    assert resp.status_code == 422, resp.text
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] in {"invalid_geometry", "invalid_request"}
    assert isinstance(data["error"]["message"], str) and data["error"]["message"]
    return data


def test_self_intersecting_ring_rejected(client):
    bowtie = [(0, 0), (4, 4), (4, 0), (0, 4)]
    resp = post(client, [poly(bowtie)], [poly([(0, 0), (1, 0), (1, 1), (0, 1)])])
    data = assert_422(resp)
    assert data["error"]["code"] == "invalid_geometry"


def test_repeated_first_vertex_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_too_few_vertices_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (1, 1)])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_duplicate_vertex_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (2, 0), (2, 0), (2, 2), (0, 2)])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_middle_duplicate_message_is_422(client):
    resp = client.post(
        "/api/v1/overlap",
        json={"a": [{"exterior": [[0, 0], [2, 0], [0, 0], [0, 2]],
                     "holes": []}],
              "b": [{"exterior": [[0, 0], [1, 0], [1, 1]], "holes": []}]},
    )
    data = assert_422(resp)
    assert any("duplicated" in d.get("message", "")
               for d in data["error"].get("details", []))


def test_coordinate_out_of_range_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (1_000_001, 0), (1_000_001, 1), (0, 1)])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    data = assert_422(resp)
    assert data["error"]["code"] == "invalid_request"


def test_non_integer_coordinate_rejected(client):
    resp = client.post(
        "/api/v1/overlap",
        json={"a": [{"exterior": [[0, 0], [1.5, 0], [1.5, 1], [0, 1]],
                     "holes": []}],
              "b": [{"exterior": [[0, 0], [1, 0], [1, 1], [0, 1]],
                     "holes": []}]},
    )
    assert_422(resp)


def test_integer_float_and_bool_coordinates_rejected(client):
    for bad in (1.0, True, "2", None):
        resp = client.post(
            "/api/v1/overlap",
            json={"a": [{"exterior": [[0, 0], [bad, 0], [1, 1]], "holes": []}],
                  "b": [{"exterior": [[0, 0], [1, 0], [1, 1]], "holes": []}]},
        )
        assert resp.status_code == 422, bad


def test_missing_field_is_422(client):
    resp = client.post("/api/v1/overlap", json={"a": []})
    assert_422(resp)


def test_malformed_json_is_422(client):
    resp = client.post(
        "/api/v1/overlap",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422


def test_ring_not_a_list_is_422(client):
    resp = client.post(
        "/api/v1/overlap",
        json={"a": [{"exterior": None, "holes": []}],
              "b": [{"exterior": [[0, 0], [1, 0], [1, 1]], "holes": []}]},
    )
    assert_422(resp)


@pytest.mark.parametrize("bad_holes", [None, 5, "x", [None], [5], [[]]])
def test_bad_holes_field_is_422_not_500(client, bad_holes):
    resp = client.post(
        "/api/v1/overlap",
        json={"a": [{"exterior": [[0, 0], [2, 0], [2, 2], [0, 2]],
                     "holes": bad_holes}],
              "b": [{"exterior": [[0, 0], [1, 0], [1, 1]], "holes": []}]},
    )
    assert resp.status_code == 422, bad_holes
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["error"]["code"] in {"invalid_request", "invalid_geometry"}
    assert isinstance(data["error"]["message"], str)


def test_null_polygon_and_null_group_are_structured_422(client):
    for payload in (
        {"a": [None], "b": [{"exterior": [[0, 0], [1, 0], [1, 1]], "holes": []}]},
        {"a": None, "b": []},
        {"a": [], "b": None},
    ):
        resp = client.post("/api/v1/overlap", json=payload)
        assert resp.status_code == 422, payload
        assert "error" in resp.json()


def test_closing_duplicate_message_is_422(client):
    resp = client.post(
        "/api/v1/overlap",
        json={"a": [{"exterior": [[0, 0], [2, 0], [2, 2], [0, 0]],
                     "holes": []}],
              "b": [{"exterior": [[0, 0], [1, 0], [1, 1]], "holes": []}]},
    )
    data = assert_422(resp)
    assert any("do not close the ring" in d.get("message", "")
               for d in data["error"].get("details", []))


def test_hole_outside_exterior_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (4, 0), (4, 4), (0, 4)],
              [[(5, 5), (6, 5), (6, 6), (5, 6)]])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_hole_touching_exterior_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (4, 0), (4, 4), (0, 4)],
              [[(0, 0), (1, 0), (1, 1), (0, 1)]])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_holes_touching_each_other_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (10, 0), (10, 10), (0, 10)],
              [[(1, 1), (3, 1), (3, 3), (1, 3)],
               [(3, 1), (5, 1), (5, 3), (3, 3)]])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_group_polygons_touching_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)]),
         poly([(1, 0), (2, 0), (2, 1), (1, 1)])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_group_polygons_overlapping_rejected(client):
    resp = post(
        client,
        [poly([(0, 0), (3, 0), (3, 3), (0, 3)]),
         poly([(1, 1), (4, 1), (4, 4), (1, 4)])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    assert_422(resp)


def test_polygon_inside_hole_of_same_group_accepted(client):
    # A polygon placed strictly inside another polygon's hole has disjoint
    # material interior and does not touch it: this is legal.
    resp = post(
        client,
        [poly([(0, 0), (10, 0), (10, 10), (0, 10)],
              [[(3, 3), (7, 3), (7, 7), (3, 7)]]),
         poly([(4, 4), (6, 4), (6, 6), (4, 6)])],
        [poly([(0, 0), (1, 0), (1, 1), (0, 1)])],
    )
    # Inner polygon lies in the hole: no contact, disjoint interiors -> OK.
    assert resp.status_code == 200, resp.text


def test_nested_holes_without_contact_accepted(client):
    resp = post(
        client,
        [poly([(0, 0), (10, 0), (10, 10), (0, 10)],
              [[(2, 2), (8, 2), (8, 8), (2, 8)],
               [(4, 4), (6, 4), (6, 6), (4, 6)]])],
        [poly([(0, 0), (10, 0), (10, 10), (0, 10)])],
    )
    # Set-difference semantics: inner hole is inside the outer hole, so the
    # material area is 100 - 36 = 64 (inner ring does not resurrect material).
    assert resp.status_code == 200, resp.text
    assert resp.json()["area_sq_mm"] == [64, 1]


def test_collinear_vertex_simple_ring_accepted(client):
    # A collinear vertex in the middle of an edge keeps the ring simple.
    resp = post(
        client,
        [poly([(0, 0), (2, 0), (4, 0), (4, 4), (0, 4)])],
        [poly([(1, 1), (3, 1), (3, 3), (1, 3)])],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["area_sq_mm"] == [4, 1]
