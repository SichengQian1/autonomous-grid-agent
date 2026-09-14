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
