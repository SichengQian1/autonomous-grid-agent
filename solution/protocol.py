from __future__ import annotations

import json
from typing import Any

from .actions import Action, Decision
from .models import Turn
from .validation import ActionValidator, ValidationIssue


def safe_response() -> dict[str, dict[str, Any]]:
    return {"roleCommandMap": {}}


def action_to_raw(action: Action) -> dict[str, Any]:
    raw: dict[str, Any] = {"action": action.action_type.value}
    if action.controller_id is not None:
        raw["controllerId"] = str(action.controller_id)
    if action.targets:
        raw["targetPos"] = [target.to_raw() for target in action.targets]
    if action.name:
        raw["name"] = action.name
    if action.quantity is not None:
        raw["num"] = action.quantity
    if action.task_answer:
        raw["taskAnswer"] = action.task_answer
    if action.items:
        raw["item"] = list(action.items)
    return raw


def serialize_decision(
    turn: Turn,
    decision: Decision,
    validator: ActionValidator | None = None,
) -> tuple[dict[str, Any], tuple[ValidationIssue, ...]]:
    validation = (validator or ActionValidator()).validate(turn, decision)
    response: dict[str, Any] = {
        "roleCommandMap": {
            str(action.actor_id): action_to_raw(action)
            for action in validation.actions
        }
    }
    if decision.prompt:
        response["prompt"] = decision.prompt
    if decision.execute_command:
        response["executeCmd"] = decision.execute_command

    json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    return response, validation.issues
