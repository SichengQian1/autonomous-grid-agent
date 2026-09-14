from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .geometry import Pos


class ActionType(str, Enum):
    MOVE = "move"
    ATTACK = "attack"
    SELL = "sell"
    BUY = "buy"
    BUILD = "build"
    REMOVE = "remove"
    ACCEPT_TASK = "acceptTask"
    SUBMIT_ANSWER = "submitAnswer"
    SUMMON_TREASURE = "summonTreasure"
    USE = "use"
    DROP = "drop"
    COLLECT = "collect"


@dataclass(frozen=True, slots=True)
class Action:
    actor_id: int
    action_type: ActionType
    controller_id: int | None = None
    targets: tuple[Pos, ...] = ()
    name: str = ""
    quantity: int | None = None
    task_answer: str = ""
    items: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    actions: tuple[Action, ...] = ()
    prompt: str = ""
    execute_command: str = ""
