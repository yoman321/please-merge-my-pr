"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from please_merge_my_pr.github.http import Transport

STUBS = {
    "init": ("Create the first config file.", "onboarding"),
    "config": ("View or change settings.", "onboarding"),
    "label": ("Add or remove pull-request labels.", "queue-actions"),
    "merge": ("Merge a pull request.", "queue-actions"),
    "comment": ("Add a pull-request comment.", "queue-actions"),
    "approve": ("Approve a pull request.", "queue-actions"),
    "hide": ("Remove a pull request from the queue.", "queue-actions"),
    "snooze": ("Hide a pull request until later.", "queue-actions"),
    "open": ("Open a pull request in a browser.", "queue-actions"),
    "rules": ("View or change queue rules.", "queue-actions"),
    "egress": ("Show what summary data may leave the machine.", "summaries"),
}


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _runtime_flags(parser: argparse.ArgumentParser, *, root: bool = False) -> None:
    default = None if root else argparse.SUPPRESS
    parser.add_argument(
        "--demo", action="store_true", default=default, help="use bundled sample data"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default,
        metavar="PATH",
        help="read settings from PATH",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="please-merge-my-pr",
        description="Rank pull requests waiting for your review.",
    )
    _runtime_flags(parser, root=True)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", description="List ranked review requests.")
    _runtime_flags(listing)
    listing.add_argument("--limit", type=_positive, default=3)
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--json", action="store_true")

    why = sub.add_parser("why", description="Explain one pull request's score.")
    _runtime_flags(why)
    why.add_argument("pr")
    why.add_argument("--json", action="store_true")

    show = sub.add_parser("show", description="Show one pull request.")
    _runtime_flags(show)
    show.add_argument("pr")

    watch = sub.add_parser("watch", description="Watch for new review requests.")
    _runtime_flags(watch)

    for name, (purpose, _) in STUBS.items():
        sub.add_parser(name, description=purpose)
    return parser


def _stub(argv: list[str]) -> int | None:
    command = next((arg for arg in argv if arg in STUBS), None)
    if command is None:
        return None
    purpose, plan = STUBS[command]
    if "--help" in argv or "-h" in argv:
        parser = argparse.ArgumentParser(prog=f"please-merge-my-pr {command}")
        parser.description = purpose
        parser.print_help()
        return 0
    import sys

    print(f"not built yet — see plans/{plan}.md", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None, transport: Transport | None = None) -> int:
    import sys

    args_list = list(sys.argv[1:] if argv is None else argv)
    stub_result = _stub(args_list)
    if stub_result is not None:
        return stub_result
    args = _parser().parse_args(args_list)
    return _run(args, transport)


def _run(args: argparse.Namespace, transport: Transport | None) -> int:
    from please_merge_my_pr.config import load_config
    from please_merge_my_pr.github.auth import AuthError, token
    from please_merge_my_pr.github.http import UrllibTransport
    from please_merge_my_pr.github.read import GitHubError

    config = load_config(args.config)
    live_transport = transport or UrllibTransport()
    try:
        if args.command == "watch" and not args.demo:
            return _watch_live(config, live_transport, token(config))
        candidates = (
            _demo_candidates()
            if args.demo
            else _live_candidates(live_transport, config, token(config))
        )
    except (AuthError, GitHubError) as exc:
        import sys

        print(str(exc), file=sys.stderr)
        return 1

    now = datetime.now(UTC)
    if args.command == "list":
        return _list(args, candidates, config, now)
    if args.command in {"why", "show"}:
        candidate = _select(args.pr, candidates)
        if isinstance(candidate, int):
            return candidate
        scored = _score_candidate(candidate, config, now)
        if args.command == "why":
            return _why(args, candidate, scored)
        return _show(candidate, scored)
    if args.command == "watch":
        return _watch_demo(candidates, config, now)
    return 2


def _demo_candidates() -> list[Any]:
    from please_merge_my_pr.demo_data import load_demo

    return load_demo()


def _live_candidates(transport: Transport, config: Any, token_value: str) -> list[Any]:
    from please_merge_my_pr.github.read import read_candidates

    return read_candidates(transport, config, token_value)


def _score_candidate(candidate: Any, config: Any, now: datetime) -> Any:
    from please_merge_my_pr.events import Event
    from please_merge_my_pr.scoring import score

    if not isinstance(candidate.event, Event):
        raise TypeError("candidate has no event")
    return score(candidate.event, candidate.reads, config.weights, config, now)


def _queue(candidates: list[Any], config: Any, now: datetime) -> tuple[list[Any], int]:
    from please_merge_my_pr.events import Event, ReviewTurn
    from please_merge_my_pr.queue import In, Unknown, eligible
    from please_merge_my_pr.scoring import Entry

    entries = []
    could_not_check = 0
    for candidate in candidates:
        if not isinstance(candidate.event, Event):
            could_not_check += 1
            continue
        decision = eligible(candidate.event, candidate.reads)
        if isinstance(decision, Unknown):
            could_not_check += 1
        if not isinstance(decision, In):
            continue
        review = candidate.reads.review
        if not isinstance(review, ReviewTurn) or review.requested_at is None:
            continue
        entries.append(
            Entry(
                candidate.repo,
                candidate.number,
                review.requested_at,
                _score_candidate(candidate, config, now),
            )
        )
    return entries, could_not_check


def _list(
    args: argparse.Namespace, candidates: list[Any], config: Any, now: datetime
) -> int:
    from please_merge_my_pr.scoring import rank
    from please_merge_my_pr.ui.screens import list_screen

    entries, could_not_check = _queue(candidates, config, now)
    groups = rank(entries)
    shown_groups = (
        groups if args.all else [group for group in groups if group.rank <= args.limit]
    )
    items: list[dict[str, Any]] = [
        {
            "rank": group.rank,
            "repo": entry.repo,
            "number": entry.number,
            "score": entry.scored.score,
            "reason": entry.scored.reason,
        }
        for group in shown_groups
        for entry in group.entries
    ]
    payload = {
        "shown": len(items),
        "total": len(entries),
        "could_not_check": could_not_check,
        "items": items,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0
    repos = {entry.repo for entry in entries}
    repo_label = next(iter(repos)) if len(repos) == 1 else f"{len(repos)} repos"
    header = f"{repo_label} · {len(entries)} in queue"
    if could_not_check:
        header += f" · {could_not_check} could not check"
    more = len(entries) - len(items)
    footer = f"+{more} more · please-merge-my-pr list --all" if more else None
    print(
        list_screen(
            header,
            (
                (int(item["number"]), str(item["reason"]), int(item["score"]))
                for item in items
            ),
            footer,
        ),
        end="",
    )
    return 0


def _select(reference: str, candidates: list[Any]) -> Any | int:
    matches = []
    if "#" in reference:
        repo, raw_number = reference.rsplit("#", 1)
        try:
            number = int(raw_number)
        except ValueError:
            number = -1
        matches = [c for c in candidates if c.repo == repo and c.number == number]
    else:
        try:
            number = int(reference)
        except ValueError:
            number = -1
        matches = [c for c in candidates if c.number == number]
    if len(matches) == 1:
        return matches[0]
    import sys

    if matches:
        print("pull request number is ambiguous:", file=sys.stderr)
        for candidate in matches:
            print(f"  {candidate.repo}#{candidate.number}", file=sys.stderr)
    else:
        print(f"pull request not found: {reference}", file=sys.stderr)
    return 1


def _why(args: argparse.Namespace, candidate: Any, scored: Any) -> int:
    from please_merge_my_pr.ui.screens import why_screen

    payload = {
        "repo": candidate.repo,
        "number": candidate.number,
        "score": scored.score,
        "exact": scored.exact,
        "rows": [asdict(row) for row in scored.rows],
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            why_screen(
                candidate.repo,
                candidate.number,
                scored.score,
                scored.exact,
                scored.rows,
            ),
            end="",
        )
    return 0


def _show(candidate: Any, scored: Any) -> int:
    from please_merge_my_pr.events import PRDetails
    from please_merge_my_pr.ui.screens import show_screen

    title = (
        candidate.reads.pr.title
        if isinstance(candidate.reads.pr, PRDetails)
        else f"{candidate.repo}#{candidate.number}"
    )
    print(show_screen(title, scored.reason, scored.score), end="")
    return 0


def _watch_demo(candidates: list[Any], config: Any, now: datetime) -> int:
    from please_merge_my_pr.scoring import rank
    from please_merge_my_pr.ui.screens import watch_screen

    entries, _ = _queue(candidates, config, now)
    ordered = [entry for group in rank(entries) for entry in group.entries]
    print(
        watch_screen(
            (entry.repo, entry.number, entry.scored.reason, entry.scored.score)
            for entry in ordered
        ),
        end="",
    )
    return 0


def _watch_live(config: Any, transport: Transport, token_value: str) -> int:
    from please_merge_my_pr.ingest.poll import Poller
    from please_merge_my_pr.store import Store
    from please_merge_my_pr.ui.screens import watch_screen

    state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    store = Store(state_root / "please-merge-my-pr" / "state.sqlite3")
    items = Poller(transport, store, config, token_value).poll_once(datetime.now(UTC))
    print(
        watch_screen(
            (item.repo, item.number, item.reason, item.score) for item in items
        ),
        end="",
    )
    return 0
