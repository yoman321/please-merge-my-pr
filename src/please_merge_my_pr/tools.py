"""Closed model-tool schema and strict argument validation."""

from __future__ import annotations

import json
import math
import re
from typing import Any, cast

from please_merge_my_pr.config import WEIGHT_KEYS

NAMES = (
    "list_queue",
    "why",
    "show",
    "move",
    "open",
    "label",
    "merge",
    "comment",
    "approve",
    "set_weights",
)
PR = re.compile(r"^[^/\s]+/[^/#\s]+#[1-9]\d*$")
PARAMS = {
    "list_queue": ("limit",),
    "why": ("pr",),
    "show": ("pr", "summary"),
    "move": ("pr", "before", "after", "position", "reason"),
    "open": ("pr",),
    "label": ("pr", "add", "remove"),
    "merge": ("pr", "method"),
    "comment": ("pr", "body"),
    "approve": ("pr", "body"),
    "set_weights": ("weights",),
}


def schemas() -> list[dict[str, Any]]:
    required = {
        "list_queue": ["limit"],
        "why": ["pr"],
        "show": ["pr", "summary"],
        "move": ["pr", "reason"],
        "open": ["pr"],
        "label": ["pr", "add", "remove"],
        "merge": ["pr", "method"],
        "comment": ["pr", "body"],
        "approve": ["pr"],
        "set_weights": ["weights"],
    }
    pr = {"type": "string"}
    label_list = {
        "type": "array",
        "maxItems": 20,
        "items": {"type": "string", "minLength": 1, "maxLength": 50},
    }
    body = {"type": "string", "minLength": 1, "maxLength": 10_000}
    weights = {
        "type": "object",
        "properties": {
            key: {"type": "number", "minimum": 0, "maximum": 100}
            for key in WEIGHT_KEYS
        },
        "required": list(WEIGHT_KEYS),
        "additionalProperties": False,
    }
    properties: dict[str, dict[str, Any]] = {
        "list_queue": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        "why": {"pr": pr},
        "show": {"pr": pr, "summary": {"type": "boolean"}},
        "move": {
            "pr": pr,
            "before": pr,
            "after": pr,
            "position": {"type": "string", "enum": ["top", "bottom"]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 200},
        },
        "open": {"pr": pr},
        "label": {"pr": pr, "add": label_list, "remove": label_list},
        "merge": {
            "pr": pr,
            "method": {"type": "string", "enum": ["merge", "squash", "rebase"]},
        },
        "comment": {"pr": pr, "body": body},
        "approve": {
            "pr": pr,
            "body": {"type": "string", "minLength": 0, "maxLength": 10_000},
        },
        "set_weights": {"weights": weights},
    }
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"Local {name} operation.",
                "parameters": {
                    "type": "object",
                    "properties": properties[name],
                    "required": required[name],
                    "additionalProperties": False,
                },
            },
        }
        for name in NAMES
    ]


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values:
        if key in out:
            raise ValueError
        out[key] = value
    return out


def parse_arguments(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def valid(name: str, args: dict[str, Any]) -> bool:
    if name not in NAMES or set(args) - set(PARAMS[name]):
        return False
    if name == "list_queue":
        value = args.get("limit")
        return (
            isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 50
        )
    if name in {"why", "open"}:
        return set(args) == {"pr"} and _pr(args.get("pr"))
    if name == "show":
        return (
            set(args) == {"pr", "summary"}
            and _pr(args.get("pr"))
            and isinstance(args.get("summary"), bool)
        )
    if name == "move":
        if (
            not _pr(args.get("pr"))
            or not isinstance(args.get("reason"), str)
            or not 1 <= len(args["reason"]) <= 200
        ):
            return False
        placements = ["position" in args, "before" in args, "after" in args]
        if sum(placements) != 1:
            return False
        if "position" in args and args["position"] not in {"top", "bottom"}:
            return False
        if args.get("before") == args["pr"] or args.get("after") == args["pr"]:
            return False
        return ("before" not in args or _pr(args["before"])) and (
            "after" not in args or _pr(args["after"])
        )
    if name == "label":
        if set(args) != {"pr", "add", "remove"} or not _pr(args.get("pr")):
            return False
        add, remove = args.get("add"), args.get("remove")
        if not _labels(add) or not _labels(remove) or (not add and not remove):
            return False
        add_labels = cast(list[str], add)
        remove_labels = cast(list[str], remove)
        return not (set(add_labels) & set(remove_labels))
    if name == "merge":
        return (
            set(args) == {"pr", "method"}
            and _pr(args.get("pr"))
            and args.get("method") in {"merge", "squash", "rebase"}
        )
    if name == "comment":
        body = args.get("body")
        return (
            set(args) == {"pr", "body"}
            and _pr(args.get("pr"))
            and isinstance(body, str)
            and 1 <= len(body) <= 10_000
        )
    if name == "approve":
        body = args.get("body", "")
        return (
            set(args) in ({"pr"}, {"pr", "body"})
            and _pr(args.get("pr"))
            and isinstance(body, str)
            and len(body) <= 10_000
        )
    weights = args.get("weights")
    if set(args) != {"weights"} or not isinstance(weights, dict):
        return False
    return (
        set(weights) == set(WEIGHT_KEYS)
        and all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(float(v))
            and 0 <= float(v) <= 100
            for v in weights.values()
        )
        and any(float(v) > 0 for v in weights.values())
    )


def _pr(value: Any) -> bool:
    return isinstance(value, str) and PR.fullmatch(value) is not None


def _labels(value: Any) -> bool:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and 1 <= len(item) <= 50 for item in value
    ):
        return False
    labels = cast(list[str], value)
    return len(labels) <= 20 and len(set(labels)) == len(labels)
