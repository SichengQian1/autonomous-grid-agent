from __future__ import annotations

from dataclasses import dataclass

from .rules import TEAM_CHALLENGER, TEAM_DEFENDER


NEIGHBOUR_DELTAS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


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

    def neighbours(self) -> tuple[Pos, ...]:
        return tuple(Pos(self.x + dx, self.y + dy) for dx, dy in NEIGHBOUR_DELTAS)


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
    mirrored_override: bool | None = None

    @property
    def mirrored(self) -> bool:
        if self.mirrored_override is not None:
            return self.mirrored_override
        return self.team_type == TEAM_DEFENDER

    @classmethod
    def from_station(
        cls,
        width: int,
        height: int,
        team_type: str,
        station_anchor: Pos | None,
    ) -> CoordinateFrame:
        """Use observed base quadrant when it clearly identifies the side.

        The known V1 map places bases in the upper-left and lower-right regions.
        Runtime geometry is preferred over a possibly missing team label, while an
        ambiguous central position falls back to that label.
        """

        override: bool | None = None
        if station_anchor is not None and width > 0 and height > 0:
            if station_anchor.x < width // 2 and station_anchor.y >= height // 2:
                override = False
            elif station_anchor.x >= width // 2 and station_anchor.y < height // 2:
                override = True
        effective_type = team_type or (
            TEAM_DEFENDER if override else TEAM_CHALLENGER
        )
        return cls(width, height, effective_type, override)

    def normalize(self, pos: Pos) -> Pos:
        if not self.mirrored:
            return pos
        return Pos(self.width - 1 - pos.x, self.height - 1 - pos.y)

    def denormalize(self, pos: Pos) -> Pos:
        return self.normalize(pos)

    def normalize_cells(self, cells: tuple[Pos, ...]) -> tuple[Pos, ...]:
        return tuple(self.normalize(cell) for cell in cells)

    def normalize_vector(self, dx: int, dy: int) -> tuple[int, int]:
        return (-dx, -dy) if self.mirrored else (dx, dy)

    def denormalize_vector(self, dx: int, dy: int) -> tuple[int, int]:
        return self.normalize_vector(dx, dy)
