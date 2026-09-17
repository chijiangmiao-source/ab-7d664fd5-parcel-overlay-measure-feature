"""Service layer: request geometry -> validated polygons -> exact overlap."""

from __future__ import annotations

from fractions import Fraction
from typing import List, Sequence

from .geometry.arrangement import overlap_area
from .geometry.transect import (
    Event,
    PointInterval,
    RangeInterval,
    SegmentProfile,
    line_transect,
)
from .geometry.validation import (
    GeometryValidationError,
    Polygon,
    build_polygon,
    validate_group,
)
from .models import (
    ContactOut,
    EventOut,
    IntervalPoint,
    IntervalRange,
    PolygonIn,
    SegmentProfileOut,
    TransectResponse,
)


def build_group(polys: Sequence[PolygonIn], name: str) -> List[Polygon]:
    built = []
    for i, p in enumerate(polys):
        try:
            built.append(
                build_polygon(p.exterior, [list(h) for h in p.holes])
            )
        except GeometryValidationError as exc:
            exc.loc = (name, i, *exc.loc)
            raise
    validate_group(built, name)
    return built


def compute_overlap(a: Sequence[PolygonIn], b: Sequence[PolygonIn]) -> Fraction:
    group_a = build_group(a, "a")
    # Validate group B independently as well; cross-group contact is legal
    # and always contributes zero area.
    group_b = build_group(b, "b")
    area = overlap_area(group_a, group_b)
    if area < 0:  # pragma: no cover - defensive; overlap is non-negative
        area = -area
    return area


def round_half_up_thirds(value: Fraction) -> str:
    """Format a non-negative fraction rounded half-up to 3 decimal places."""
    if value < 0:  # pragma: no cover - defensive
        raise ValueError("only non-negative areas are supported")
    scale = 1000
    scaled, rem = divmod(value.numerator * scale, value.denominator)
    if rem * 2 >= value.denominator:
        scaled += 1
    whole, frac = divmod(scaled, scale)
    return f"{whole}.{frac:03d}"


def _fraction_pair(value: Fraction) -> List[int]:
    # Fraction values are always reduced and denominator-positive; fractional
    # intersection parameters are serialized exactly, never as floats.
    return [value.numerator, value.denominator]


def compute_transect(a: Sequence[PolygonIn], b: Sequence[PolygonIn],
                     path: Sequence[tuple[int, int]]) -> TransectResponse:
    group_a = build_group(a, "a")
    group_b = build_group(b, "b")
    profiles = line_transect([tuple(p) for p in path], group_a, group_b)
    return TransectResponse(segments=[_segment_out(p) for p in profiles])


def _event_out(event: Event) -> EventOut:
    return EventOut(
        group="a" if event.group == 0 else "b",
        before=event.before,
        after=event.after,
        contacts=[
            ContactOut(
                polygon=c.polygon,
                boundary=c.role,
                hole_index=c.hole_index,
            )
            for c in event.contacts
        ],
    )


def _segment_out(profile: SegmentProfile) -> SegmentProfileOut:
    intervals: list = []
    for item in profile.items:
        if isinstance(item, PointInterval):
            intervals.append(
                IntervalPoint(
                    t=_fraction_pair(item.t),
                    a=item.states[0],
                    b=item.states[1],
                    events=[_event_out(e) for e in item.events],
                )
            )
        else:
            assert isinstance(item, RangeInterval)
            intervals.append(
                IntervalRange(
                    start=_fraction_pair(item.start),
                    end=_fraction_pair(item.end),
                    a=item.states[0],
                    b=item.states[1],
                )
            )
    return SegmentProfileOut(index=profile.index, intervals=intervals)


__all__ = [
    "GeometryValidationError",
    "compute_overlap",
    "compute_transect",
    "round_half_up_thirds",
]
