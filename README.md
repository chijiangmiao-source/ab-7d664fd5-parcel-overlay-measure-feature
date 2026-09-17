# Exact Multi-Polygon Overlap API

A pure backend service that computes the **overlap area of two groups of
multi-polygons** using **exact integer / rational arithmetic only**. There is
no database, no asynchronous worker, no frontend, no call to external online
services, and **no third-party geometry library** is used for intersection or
area — every geometric operation is implemented in this repository on top of
Python's `fractions.Fraction`.

* Python 3.13 target (also runs on 3.11+)
* FastAPI + Pydantic v2 + Uvicorn
* Coordinates are integer millimetres in `[-1_000_000, 1_000_000]`
* Result: reduced fraction `p/q` in mm² plus a half-up, three-decimal string

## Why exact arithmetic

Clipping with floating point makes the same parcel produce different areas
when vertices are listed in a different order, especially around concave
corners and holes where boundaries cross many times. Here every intersection
parameter `t`, every split vertex and every shoelace term is a `Fraction`, so:

* fractional intersections are represented exactly;
* edge/point contacts contribute exactly zero;
* concave edges that cross another boundary arbitrarily many times, hole
  cut-outs and coincident collinear edges are all handled;
* the result is provably independent of polygon, ring and vertex order
  (covered by permutation, reversal and symmetry tests).

## Algorithm

`app/geometry/arrangement.py` builds one planar arrangement:

1. Every ring edge is tagged with a signed **winding contribution**
   (exterior ring `+1`, hole ring `-1`, with the stored orientation).
2. Every pair of edges is intersected exactly (proper crossings, endpoint /
   T-junction contacts, and collinear overlaps). All common points are
   registered as rational cut parameters.
3. Cut edges become atomic segments; coincident pieces (including identical
   edges running in opposite directions) merge and their tags are summed.
4. A half-edge structure is formed and its face permutation recovers all
   boundary cycles (bounded CCW outer cycles and CW hole cycles, including the
   cycle of the unbounded face).
5. CW cycles are attached to the face of the innermost CCW cycle containing
   them, which realises hole nesting and set-difference semantics.
6. Crossing a segment from its right face to its left face changes each
   group's winding number by the aggregated tag; winding numbers are then
   propagated exactly from the unbounded face (winding `0/0`).
7. The overlap area is the signed shoelace-area sum over all boundary cycles
   of faces whose winding is positive for **both** groups.

Validation (`app/geometry/validation.py`) rejects malformed input with 422:

* fewer than three vertices, a repeated/closing vertex, a non-simple ring
  (non-adjacent edges crossing or touching, including collinear overlap);
* a hole not strictly inside its exterior or touching it;
* holes touching each other;
* polygons of the same group whose interiors intersect or whose boundaries
  touch (a polygon strictly inside another polygon's *hole* is allowed).

Ring orientation (CW/CCW) carries no semantic meaning; it is normalised by the
signed area. A hole nested strictly inside another hole contributes nothing
(set difference: `exterior − ⋃ holes`).

## API

### `GET /health`

```json
{"status": "ok"}
```

### `POST /api/v1/overlap`

```json
{
  "a": [
    {
      "exterior": [[0, 0], [6, 0], [6, 6], [0, 6]],
      "holes": [[[2, 2], [4, 2], [4, 4], [2, 4]]]
    }
  ],
  "b": [
    {
      "exterior": [[1, 1], [5, 1], [5, 5], [1, 5]],
      "holes": []
    }
  ]
}
```

Response `200`:

```json
{
  "area_sq_mm": [12, 1],
  "numerator": 12,
  "denominator": 1,
  "decimal": "12.000",
  "rounding": "half-up",
  "units": "mm^2"
}
```

Fractional example (two triangles overlapping in a triangle of ½ mm²):

```json
{
  "area_sq_mm": [1, 2],
  "numerator": 1,
  "denominator": 2,
  "decimal": "0.500",
  "rounding": "half-up",
  "units": "mm^2"
}
```

`decimal` rounds the exact fraction **half-up** to exactly three digits
(`0.0005 → 0.001`), implemented with integer arithmetic rather than `round()`.

### `POST /api/v1/transect`

The transect endpoint tells a field surveyor **where the survey polyline is**
relative to each multi-polygon group — outside, inside or on the boundary —
rather than only how much area overlaps.  The request keeps the same `a` / `b`
groups and adds a `path` of at least two integer points (consecutive points
must differ):

```json
{
  "a": [
    {
      "exterior": [[0, 0], [4, 0], [4, 4], [0, 4]],
      "holes": [[[1, 1], [3, 1], [3, 3], [1, 3]]]
    }
  ],
  "b": [
    {"exterior": [[2, 2], [6, 2], [6, 6], [2, 6]], "holes": []}
  ],
  "path": [[-1, 2], [7, 2]]
}
```

The response lists one object per **raw path segment** in the original order
(segment `0` is `path[0] → path[1]`, …).  Every segment's `[0, 1]` parameter
range is split into ordered, gap- and overlap-free **intervals**; `t0`/`t1`
are reduced fractions `[numerator, denominator]` along that raw segment, and
`a`/`b` classify the interval for each group:

```json
{
  "segments": [
    {
      "index": 0,
      "start": [-1, 2],
      "end": [7, 2],
      "intervals": [
        {"t0": [0, 1], "t1": [1, 8], "a": "outside",  "b": "outside"},
        {"t0": [1, 8], "t1": [1, 4], "a": "inside",   "b": "outside"},
        {"t0": [1, 4], "t1": [3, 8], "a": "outside",  "b": "outside"},
        {"t0": [3, 8], "t1": [1, 2], "a": "outside",  "b": "boundary"},
        {"t0": [1, 2], "t1": [5, 8], "a": "inside",   "b": "boundary"},
        {"t0": [5, 8], "t1": [7, 8], "a": "outside",  "b": "boundary"},
        {"t0": [7, 8], "t1": [1, 1], "a": "outside",  "b": "outside"}
      ],
      "events": [
        {"t": [1, 8], "point": [0, 1, 2, 1], "a": "boundary", "b": "outside"}
      ],
      "contacts": [
        {
          "t": [1, 8],
          "point": [0, 1, 2, 1],
          "a": ["outside", "boundary", "inside"],
          "b": ["outside", "outside", "outside"]
        }
      ]
    }
  ]
}
```

* `events` — every sweep cut in parameter order.  `point` is the exact
  intersection as four integers `[x_num, x_den, y_num, y_den]`; fractional
  intersections are **never** converted to floating point.  A path vertex that
  lies on a boundary appears as an event at `t = [0, 1]` / `[1, 1]` on both
  adjacent segments.
* `contacts` — **isolated** boundary points (proper crossings, T-junctions and
  vertex tangencies; not the ends of a boundary run).  Each records the
  relation `[before, at, after]` for both groups; the side beyond a segment
  endpoint is `null`.
* A positive-length stretch that runs along a collinear ring edge is a
  `"boundary"` interval and produces no isolated contact.
* Each raw segment is fully covered from `[0, 1]` to `[1, 1]`; reversing the
  whole polyline yields the same intervals and events at `1 − t`, in reverse
  order, with each contact's before/after relations swapped.

Polygon validation is identical to the overlap endpoint (geometry errors keep
their `["a", i, …]` / `["b", i, …]` locations).  A malformed `path` is an
`invalid_request` 422 that pinpoints the offending point, e.g.
`loc: ["body", "path", 2]` for a repeated `path[2]`.

### Errors (all 422 use one structured envelope)

```json
{
  "error": {
    "code": "invalid_request",
    "message": "request payload does not satisfy the schema",
    "details": [
      {"loc": ["a", 0, "exterior", 2], "type": "value_error", "message": "..."}
    ]
  }
}
```

* `invalid_request` — schema/type/range problems (non-integers, out of range
  coordinates, wrong shape, malformed JSON).
* `invalid_geometry` — well-formed coordinates that violate a geometric rule
  (non-simple ring, hole not strictly inside, touching polygons, …).

## Running with Docker Compose

```bash
docker compose up --build
# API on http://localhost:${API_PORT:-8000}
```

Override the **host** port with `API_PORT`:

```bash
API_PORT=9090 docker compose up --build
```

### One-shot acceptance service

```bash
docker compose run --rm verify
```

`verify` waits until the API container is healthy, then runs the whole pytest
suite inside the image, including live HTTP acceptance tests
(`tests/test_http_acceptance.py`) against the running API, and exits non-zero
on the first failure.

## Local development

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload
pytest -q                                   # 110 pass, 11 skipped offline

EXACT_AREA_BASE_URL=http://127.0.0.1:8000 pytest -q   # with a server running:
                                                      # all 121 tests execute
```

## Test suite

* `tests/test_api.py` — endpoint behaviour, fraction reduction, half-up
  rounding, contacts = 0, and order/rotation/orientation independence.
* `tests/test_transect_units.py` — exact transect engine: outer-ring/hole
  crossings for two groups, vertex tangencies, collinear boundary runs, path
  vertices on a boundary, fractional intersections, reversal identity, full
  `[0, 1]` coverage and randomized agreement with an independent classifier.
* `tests/test_transect_api.py` — `/api/v1/transect` endpoint behaviour and
  error locations, plus continued compatibility of `/api/v1/overlap`.
* `tests/test_validation.py` — every 422 rule and the structured error body.
* `tests/test_geometry_units.py` — primitives: orientation, point-on-segment,
  fractional intersection, simplicity detection, rounding table.
* `tests/test_differential.py` — an independent exact reference (vertical-slab
  integration with mid-sample containment, a different algorithm) plus
  randomized differential testing and self-overlap identities.
* `tests/test_engine_heavy.py` — hundreds of random intersecting
  triangles/rectangles, multi-polygon grids, coincident/partial edges,
  T-junctions and multi-hole strips.
* `tests/test_http_acceptance.py` — live black-box checks used by `verify`.

## Repository layout

```
app/
  main.py                 FastAPI app, routes, structured error handlers
  models.py               Pydantic v2 request/response models + range checks
  service.py              validation orchestration, Fraction -> response
  geometry/
    rationals.py          exact predicates, intersections, ring primitives
    validation.py         simplicity / containment / disjointness rules
    arrangement.py        planar arrangement + winding-number overlap area
    transect.py           event-sweep polyline crossing profile (exact)
tests/                    pytest suite (incl. live HTTP acceptance tests)
Dockerfile                python:3.13-slim image (runtime + test deps)
docker-compose.yml        api service (API_PORT) + one-shot verify service
requirements*.txt         pinned major ranges for runtime / test deps
```
