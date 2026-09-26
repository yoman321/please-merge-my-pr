"""Canonical actions, tiers, previews, and GitHub payloads."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote

from please_merge_my_pr.config import Config
from please_merge_my_pr.github.http import Request, Transport
from please_merge_my_pr.github.write import send
from please_merge_my_pr.store import Store
from please_merge_my_pr.text import clean, wrapped

PR = re.compile(r"^([^/\s]+/[^/#\s]+)#([1-9]\d*)$")
TIERS = {
    "open": 1,
    "hide": 1,
    "unhide": 1,
    "snooze": 1,
    "label": 2,
    "merge": 3,
    "comment": 3,
    "approve": 3,
    "set_weights": 3,
}


@dataclass(frozen=True)
class Action:
    name: str
    repo: str
    number: int
    requests: tuple[Request, ...]
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


def split_pr(reference: str) -> tuple[str, int]:
    match = PR.fullmatch(reference)
    if not match:
        raise ValueError("invalid pull request")
    return match.group(1), int(match.group(2))


def _request(
    config: Config, token: str, method: str, path: str, payload: object | None
) -> Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
        "User-Agent": "please-merge-my-pr/0.1",
    }
    body = (
        None
        if payload is None
        else json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    )
    if body is not None:
        headers["Content-Type"] = "application/json"
    return Request(method, config.github_api_url.rstrip("/") + path, headers, body)


def build(config: Config, token: str, name: str, args: dict[str, object]) -> Action:
    repo, number = split_pr(str(args["pr"]))
    root = f"/repos/{repo}"
    requests: list[Request] = []
    adds: tuple[str, ...] = ()
    removes: tuple[str, ...] = ()
    if name == "label":
        adds = tuple(sorted(str(v) for v in cast(list[object], args.get("add", []))))
        removes = tuple(
            sorted(str(v) for v in cast(list[object], args.get("remove", [])))
        )
        requests.extend(
            _request(
                config,
                token,
                "DELETE",
                f"{root}/issues/{number}/labels/{quote(label, safe='')}",
                None,
            )
            for label in removes
        )
        if adds:
            requests.append(
                _request(
                    config,
                    token,
                    "POST",
                    f"{root}/issues/{number}/labels",
                    {"labels": list(adds)},
                )
            )
    elif name == "merge":
        requests.append(
            _request(
                config,
                token,
                "PUT",
                f"{root}/pulls/{number}/merge",
                {"merge_method": args["method"]},
            )
        )
    elif name == "comment":
        requests.append(
            _request(
                config,
                token,
                "POST",
                f"{root}/issues/{number}/comments",
                {"body": clean(str(args["body"]))},
            )
        )
    elif name == "approve":
        payload = {"event": "APPROVE"}
        if args.get("body"):
            payload["body"] = clean(str(args["body"]))
        requests.append(
            _request(config, token, "POST", f"{root}/pulls/{number}/reviews", payload)
        )
    else:
        raise ValueError("unknown action")
    return Action(name, repo, number, tuple(requests), adds, removes)


def preview(action: Action) -> str:
    lines = [f"{action.name} {action.repo}#{action.number}"]
    for request in action.requests:
        path = request.url.split("/repos/", 1)[1]
        line = f"{request.method} /repos/{path}"
        if request.body is not None:
            line += " " + clean(request.body.decode())
        lines.extend(wrapped(line))
    return "\n".join(lines) + "\n"


def confirm() -> bool:
    print("Run this action? [y/N] ", end="", flush=True)
    if not sys.stdin.isatty():
        print()
        return False
    try:
        answer = sys.stdin.readline()
    except KeyboardInterrupt:
        print()
        return False
    return answer.strip().casefold() in {"y", "yes"}


def execute(
    action: Action, transport: Transport, *, dry_run: bool = False
) -> tuple[bool, str]:
    shown = preview(action)
    if dry_run:
        print(shown, end="")
        return True, "dry run"
    completed: list[str] = []
    for request in action.requests:
        result = send(transport, request)
        path = "/repos/" + request.url.split("/repos/", 1)[1]
        if not result.ok:
            return (
                False,
                f"failed {request.method} {path}: {result.status}; completed: {', '.join(completed) or 'none'}",
            )
        completed.append(path)
    return True, f"{action.name} complete for {action.repo}#{action.number}"


def permitted_without_prompt(action: Action, store: Store) -> bool:
    return action.name == "label" and store.rule_matches(
        action.repo, action.add, action.remove
    )


def open_pr(config: Config, reference: str) -> bool:
    repo, number = split_pr(reference)
    url = f"{config.github_web_url.rstrip('/')}/{repo}/pull/{number}"
    browser = os.environ.get("BROWSER")
    if browser:
        command = shlex.split(browser.replace("%s", url))
        if "%s" not in browser:
            command.append(url)
        try:
            return subprocess.run(command, check=False).returncode == 0
        except OSError:
            return False
    import webbrowser

    return webbrowser.open(url)
