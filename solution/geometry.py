from __future__ import annotations

from dataclasses import dataclass

from .rules import TEAM_DEFENDER


@dataclass(frozen=True, slots=True, order=True)
class Pos:
    x: int
    y: int

    @classmethod
    def from_raw(cls, raw: object) -> Pos | None:
        if not isinstance(raw, dict):
            return None
        x = raw.get("x")
        y = raw.get("y")
        if isinstance(x, bool) or isinstance(y, bool):
            return None
        try:
            return cls(int(x), int(y))
        except (TypeError, ValueError, OverflowError):
            return None

    def to_raw(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}

    def distance_to(self, other: Pos) -> int:
        return max(abs(self.x - other.x), abs(self.y - other.y))


def station_footprint(anchor: Pos) -> tuple[Pos, Pos, Pos, Pos]:
    """Expand the raw top-left station anchor into its four occupied cells."""

    return (
        anchor,
        Pos(anchor.x + 1, anchor.y),
        Pos(anchor.x, anchor.y - 1),
        Pos(anchor.x + 1, anchor.y - 1),
    )


def neighbours(pos: Pos) -> tuple[Pos, ...]:
    return tuple(Pos(pos.x + dx, pos.y + dy) for dx in (-1, 0, 1)
                 for dy in (-1, 0, 1) if dx or dy)


def footprint_distance(pos: Pos, cells: tuple[Pos, ...]) -> int:
    return min((pos.distance_to(cell) for cell in cells), default=10**6)


def footprint_ring(cells: tuple[Pos, ...], radius: int) -> tuple[Pos, ...]:
    if not cells:
        return ()
    return tuple(
        Pos(x, y)
        for x in range(min(p.x for p in cells) - radius, max(p.x for p in cells) + radius + 1)
        for y in range(min(p.y for p in cells) - radius, max(p.y for p in cells) + radius + 1)
        if footprint_distance(Pos(x, y), cells) == radius
    )


def ray_entry(origin: Pos, target: Pos, cell: Pos) -> float | None:
    """Segment versus closed unit square; corner contacts are conservative hits."""
    low, high = 0.0, 1.0
    for start, end, centre in ((origin.x, target.x, cell.x), (origin.y, target.y, cell.y)):
        delta = end - start
        if not delta:
            if abs(start - centre) > 0.5:
                return None
            continue
        first, last = sorted(((centre - 0.5 - start) / delta, (centre + 0.5 - start) / delta))
        low, high = max(low, first), min(high, last)
        if low > high:
            return None
    return low


def ray_blocked(origin: Pos, target: Pos, cells: set[Pos] | tuple[Pos, ...]) -> bool:
    """True when a closed unit square on the segment is a conservative hit."""
    for cell in cells:
        if cell == origin:
            continue
        if ray_entry(origin, target, cell) is not None:
            return True
    return False


@dataclass(frozen=True, slots=True)
class CoordinateFrame:
    width: int
    height: int
    team_type: str

    @property
    def mirrored(self) -> bool:
        return self.team_type == TEAM_DEFENDER

    def normalize(self, pos: Pos) -> Pos:
        if not self.mirrored:
            return pos
        return Pos(self.width - 1 - pos.x, self.height - 1 - pos.y)

    def denormalize(self, pos: Pos) -> Pos:
        return self.normalize(pos)

    def normalize_cells(self, cells: tuple[Pos, ...]) -> tuple[Pos, ...]:
        return tuple(self.normalize(cell) for cell in cells)
