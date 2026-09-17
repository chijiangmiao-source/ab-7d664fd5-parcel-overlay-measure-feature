"""Pydantic request/response models for the overlap / transect API."""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails

COORD_MIN = -1_000_000
COORD_MAX = 1_000_000
MIN_RING_POINTS = 3
MIN_PATH_POINTS = 2

Coordinate = Tuple[int, int]

RelationLabel = Literal["outside", "inside", "boundary"]
RelationTriple = List[Optional[RelationLabel]]


class PolygonIn(BaseModel):
    """One polygon: a single exterior ring and zero or more holes."""

    exterior: List[Coordinate] = Field(
        description="Exterior ring: >= 3 unique vertices, no closing duplicate.",
    )
    holes: List[List[Coordinate]] = Field(
        default_factory=list,
        description="Zero or more hole rings.",
    )

    @field_validator("exterior", mode="before")
    @classmethod
    def _check_exterior(cls, v: List[Coordinate]) -> List[Coordinate]:
        _validate_ring_points(v, loc="exterior")
        return v

    @field_validator("holes", mode="before")
    @classmethod
    def _check_holes(cls, v: List[List[Coordinate]]) -> List[List[Coordinate]]:
        # This runs before type coercion: None / a number / a string would
        # otherwise raise TypeError while iterating and escape as a 500.
        if v is None:
            raise ValueError("holes must be a list of rings (use [] for none)")
        if not isinstance(v, list):
            raise ValueError("holes must be a list of rings")
        for i, hole in enumerate(v):
            if not isinstance(hole, list):
                raise ValueError(f"holes[{i}] must be a ring (list of vertices)")
            _validate_ring_points(hole, loc="holes")
        return v


class OverlapRequest(BaseModel):
    a: List[PolygonIn] = Field(description="First multi-polygon group.")
    b: List[PolygonIn] = Field(description="Second multi-polygon group.")


class TransectRequest(BaseModel):
    a: List[PolygonIn] = Field(description="First multi-polygon group.")
    b: List[PolygonIn] = Field(description="Second multi-polygon group.")
    path: List[Coordinate] = Field(
        description="Survey polyline: at least two integer points; consecutive "
                    "points must differ.",
    )

    @field_validator("path", mode="before")
    @classmethod
    def _check_path(cls, v: List[Coordinate]) -> List[Coordinate]:
        if not isinstance(v, list):
            raise ValueError("path must be a list of [x, y] integer pairs")
        if len(v) < MIN_PATH_POINTS:
            raise ValueError(
                f"path must contain at least {MIN_PATH_POINTS} points, "
                f"got {len(v)}"
            )
        for i, p in enumerate(v):
            if (
                not isinstance(p, (list, tuple))
                or len(p) != 2
                or not all(isinstance(c, int) and not isinstance(c, bool) for c in p)
            ):
                raise ValueError(f"path point {i} must be an integer pair [x, y]")
            x, y = p
            if not (COORD_MIN <= x <= COORD_MAX and COORD_MIN <= y <= COORD_MAX):
                raise ValueError(
                    f"path point {i} ({x}, {y}) is outside the closed interval "
                    f"[{COORD_MIN}, {COORD_MAX}]"
                )
        return v

    @model_validator(mode="after")
    def _check_consecutive_path_points(self) -> "TransectRequest":
        # A separate after-validation pass (rather than a field_validator) so
        # the error loc pinpoints the offending request position ["path", i].
        details: List[InitErrorDetails] = []
        for i in range(1, len(self.path)):
            if self.path[i] == self.path[i - 1]:
                x, y = self.path[i]
                details.append(
                    InitErrorDetails(
                        type="value_error",
                        loc=("path", i),
                        ctx={
                            "error": ValueError(
                                f"path point {i} ({x}, {y}) repeats point "
                                f"{i - 1}; consecutive path points must differ"
                            )
                        },
                    )
                )
        if details:
            raise ValidationError.from_exception_data(self.__class__.__name__, details)
        return self


def _validate_ring_points(points: List[Coordinate], *, loc: str) -> None:
    if not isinstance(points, list):
        raise ValueError("ring must be a list of [x, y] integer pairs")
    if len(points) < MIN_RING_POINTS:
        raise ValueError(
            f"ring must contain at least {MIN_RING_POINTS} vertices, "
            f"got {len(points)}"
        )
    seen: set[Coordinate] = set()
    for i, p in enumerate(points):
        if (
            not isinstance(p, (list, tuple))
            or len(p) != 2
            or not all(isinstance(c, int) and not isinstance(c, bool) for c in p)
        ):
            raise ValueError(f"vertex {i} must be an integer pair [x, y]")
        x, y = p
        if not (COORD_MIN <= x <= COORD_MAX and COORD_MIN <= y <= COORD_MAX):
            raise ValueError(
                f"vertex {i} ({x}, {y}) is outside the closed interval "
                f"[{COORD_MIN}, {COORD_MAX}]"
            )
        if (x, y) in seen:
            if i == len(points) - 1 and tuple(points[0]) == (x, y):
                raise ValueError(
                    f"vertex {i} repeats the first vertex; do not close the ring"
                )
            raise ValueError(f"vertex {i} ({x}, {y}) is duplicated")
        seen.add((x, y))


class OverlapResponse(BaseModel):
    area_sq_mm: List[int] = Field(
        description="Overlap area as the reduced fraction [numerator, denominator] "
                    "in square millimetres."
    )
    numerator: int
    denominator: int
    decimal: str = Field(
        description="Area rounded half-up to exactly three decimal places."
    )
    rounding: Literal["half-up"] = "half-up"
    units: Literal["mm^2"] = "mm^2"


class TransectInterval(BaseModel):
    t0: List[int] = Field(
        description="Start parameter as a reduced fraction [numerator, denominator] "
                    "along the raw segment (0 at start, 1 at end)."
    )
    t1: List[int] = Field(description="End parameter as a reduced fraction.")
    a: RelationLabel
    b: RelationLabel


class TransectEvent(BaseModel):
    t: List[int] = Field(description="Event parameter as a reduced fraction.")
    point: List[int] = Field(
        description="Exact intersection coordinates as reduced fractions "
                    "[x_num, x_den, y_num, y_den].",
    )
    a: RelationLabel = Field(description="Relation to group A exactly at the event.")
    b: RelationLabel = Field(description="Relation to group B exactly at the event.")


class TransectContact(BaseModel):
    t: List[int] = Field(description="Contact parameter as a reduced fraction.")
    point: List[int]
    a: RelationTriple = Field(
        description="Relation to group A [before, at, after]; the endpoint side "
                    "is null.",
    )
    b: RelationTriple


class TransectSegment(BaseModel):
    index: int = Field(description="Index of this segment in the original path.")
    start: List[int]
    end: List[int]
    intervals: List[TransectInterval] = Field(
        description="Ordered, gap- and overlap-free partition of [0, 1] into "
                    "positive-length intervals.",
    )
    events: List[TransectEvent] = Field(
        description="All sweep cuts in parameter order (including path vertices "
                    "lying on a boundary).",
    )
    contacts: List[TransectContact] = Field(
        description="Isolated boundary contacts with their before/at/after "
                    "relations.",
    )


class TransectResponse(BaseModel):
    segments: List[TransectSegment]
