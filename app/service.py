"""Service layer: request geometry -> validated polygons -> exact overlap."""

from __future__ import annotations

from fractions import Fraction
from typing import List, Sequence

from .geometry.arrangement import overlap_area
from .geometry.validation import (
    GeometryValidationError,
    Polygon,
    build_polygon,
    validate_group,
)
from .models import PolygonIn


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


__all__ = [
    "GeometryValidationError",
    "compute_overlap",
    "round_half_up_thirds",
]
