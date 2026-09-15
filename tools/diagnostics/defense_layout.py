#!/usr/bin/env python3
"""Bounded ASCII summary of a synthetic frontline or legacy layout."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solution.configuration import load_config
from solution.geometry import Pos, footprint_distance
from solution.layout import DefenseMemory, observe_defense, plan_layout
from solution.models import Turn
from tests.scenarios import arena


MAX_BYTES = 8 * 1024
MAX_JSON_BYTES = 1 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise a synthetic defensive layout.")
    parser.add_argument("--scenario", choices=("left", "right"), default="left")
    parser.add_argument("--config", default="")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--json", dest="json_path", default="")
    return parser.parse_args()


def _sample(scenario: str) -> dict:
    raw = arena()
    if scenario == "right":
        raw["teamOur"]["type"] = "defender"
        for unit in raw["teamOur"]["roles"]:
            x, y = unit["pos"]["x"], unit["pos"]["y"]
            if unit["roleType"] == "station":
                unit["pos"] = {"x": 22 - x, "y": 20 - y}
            else:
                unit["pos"] = {"x": 23 - x, "y": 19 - y}
        for zone in raw["mapInfo"]["zones"]:
            zone["pos"] = {"x": 23 - zone["pos"]["x"], "y": 19 - zone["pos"]["y"]}
    return raw


def _load_json(path: str) -> dict:
    data = Path(path).read_bytes()
    if len(data) > MAX_JSON_BYTES:
        raise SystemExit("input JSON exceeds the local size limit")
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("input JSON must be an object")
    return payload


def _ascii(turn: Turn, layout) -> str:
    width, height = min(turn.map_info.width, 40), min(turn.map_info.height, 28)
    grid = [["." for _ in range(width)] for _ in range(height)]
    for cell in turn.team_our.station().footprint() if turn.team_our.station() else ():
        if 0 <= cell.x < width and 0 <= cell.y < height:
            grid[cell.y][cell.x] = "B"
    marks = {}
    if layout is not None:
        for gate in layout.gates:
            marks[gate] = "E"
        for wall in layout.flank_walls:
            marks[wall] = "F"
        for wall in layout.front_walls:
            marks[wall] = "W"
        for weapon in layout.weapons:
            marks[weapon.pos] = {"rocket": "K", "railgun": "R", "gatling": "G"}.get(weapon.role_type, "T")
            for cell in weapon.controller_cells:
                marks.setdefault(cell, "C")
    for pos, glyph in marks.items():
        if 0 <= pos.x < width and 0 <= pos.y < height:
            grid[pos.y][pos.x] = glyph
    rows = [f"y={y:02d} " + "".join(grid[y]) for y in range(height)]
    return "\n".join(["x:  " + "".join(str(i % 10) for i in range(width)), *rows])


def _summary(turn: Turn, layout, memory, config) -> str:
    lines = [
        f"mode={config.defense_layout} front_direction={config.front_direction}",
        f"map={turn.map_info.width}x{turn.map_info.height} team={turn.team_our.team_type}",
        f"reason={memory.last_reason or (layout.reason if layout else 'none')}",
    ]
    if layout is None:
        lines.append("layout=None fallback=legacy_or_unavailable")
        return "\n".join(lines)
    lines.append(f"front={layout.front} source={layout.source}")
    for weapon in layout.weapons:
        cells = ",".join(f"({c.x},{c.y})" for c in weapon.controller_cells)
        lines.append(f"weapon {weapon.role_type} ({weapon.pos.x},{weapon.pos.y}) controllers={cells}")
    lines.append("front_walls=" + ",".join(f"({p.x},{p.y})" for p in layout.front_walls[:8]))
    lines.append("flank_walls=" + ",".join(f"({p.x},{p.y})" for p in layout.flank_walls[:8]))
    lines.append("wall_order=" + ",".join(f"({p.x},{p.y})" for p in layout.wall_order[:12]))
    lines.append("gates=" + ",".join(f"({p.x},{p.y})" for p in layout.gates))
    lines.append(_ascii(turn, layout))
    return "\n".join(lines)


def _verify(turn: Turn, layout, config) -> list[str]:
    issues: list[str] = []
    if config.defense_layout != "frontline":
        return issues
    if layout is None:
        issues.append("frontline produced no layout")
        return issues
    base = turn.team_our.station().footprint() if turn.team_our.station() else ()
    for weapon in layout.weapons:
        if footprint_distance(weapon.pos, base) != 1:
            issues.append(f"weapon not on blue ring: {weapon.pos}")
        if not weapon.controller_cells:
            issues.append(f"weapon missing controller: {weapon.pos}")
    for wall in layout.front_walls + layout.flank_walls:
        if footprint_distance(wall, base) != 2:
            issues.append(f"wall not on yellow ring: {wall}")
        if wall in layout.gates:
            issues.append(f"gate walled: {wall}")
    controllers = [cell for weapon in layout.weapons for cell in weapon.controller_cells]
    if len(set(controllers)) < min(3, len(controllers)):
        issues.append("controller cells are not distinct")
    return issues


def main() -> int:
    args = parse_args()
    config = load_config(args.config or None)
    raw = _load_json(args.json_path) if args.json_path else _sample(args.scenario)
    turn = Turn.from_raw(raw)
    memory = DefenseMemory()
    observe_defense(turn, memory, config)
    layout = plan_layout(turn, memory, config, time.monotonic() + 1)
    text = _summary(turn, layout, memory, config)
    encoded = text.encode("utf-8")[:MAX_BYTES]
    sys.stdout.write(encoded.decode("utf-8", errors="ignore") + "\n")
    if args.verify:
        issues = _verify(turn, layout, config)
        if issues:
            sys.stderr.write("verify failed: " + "; ".join(issues[:8]) + "\n")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
