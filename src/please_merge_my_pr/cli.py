"""Command-line entry point and model-free service paths."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from please_merge_my_pr.github.http import Transport


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
    sub = parser.add_subparsers(dest="command")
    listing = sub.add_parser("list", description="List ranked review requests.")
    _runtime_flags(listing)
    listing.add_argument("--limit", type=_positive, default=None)
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

    sub.add_parser("init", description="Create the first config file.")
    config = sub.add_parser("config", description="View or change settings.")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show")
    config_sub.add_parser("path")
    setting = config_sub.add_parser("set")
    setting.add_argument("key")
    setting.add_argument("value")
    config_sub.add_parser("edit")

    label = sub.add_parser("label", description="Add or remove pull-request labels.")
    label.add_argument("pr")
    label.add_argument("--add", nargs="*", default=[])
    label.add_argument("--remove", nargs="*", default=[])
    label.add_argument("--dry-run", action="store_true")
    merge = sub.add_parser("merge", description="Merge a pull request.")
    merge.add_argument("pr")
    merge.add_argument("--method", choices=("merge", "squash", "rebase"), required=True)
    merge.add_argument("--dry-run", action="store_true")
    comment = sub.add_parser("comment", description="Add a pull-request comment.")
    comment.add_argument("pr")
    comment.add_argument("body")
    comment.add_argument("--dry-run", action="store_true")
    approve = sub.add_parser("approve", description="Approve a pull request.")
    approve.add_argument("pr")
    approve.add_argument("body", nargs="?", default="")
    approve.add_argument("--dry-run", action="store_true")
    purposes = {
        "hide": "Remove a pull request from the queue.",
        "unhide": "Return a hidden pull request to the queue.",
        "open": "Open a pull request in a browser.",
    }
    for name in ("hide", "unhide", "open"):
        item = sub.add_parser(name, description=purposes[name])
        item.add_argument("pr")
    snooze = sub.add_parser("snooze", description="Hide a pull request until later.")
    snooze.add_argument("pr")
    snooze.add_argument("until")
    rules = sub.add_parser("rules", description="View or change label rules.")
    rule_sub = rules.add_subparsers(dest="rules_command", required=True)
    add = rule_sub.add_parser("add")
    add.add_argument("repo")
    add.add_argument("--add", nargs="*", default=[])
    add.add_argument("--remove", nargs="*", default=[])
    rule_sub.add_parser("list")
    remove = rule_sub.add_parser("rm")
    remove.add_argument("rule_id", type=int)
    sub.add_parser("egress", description="Explain where chat egress is shown.")
    return parser


def main(argv: Sequence[str] | None = None, transport: Transport | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    if not args_list:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from please_merge_my_pr.chat import run

            return run(transport)
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(args_list)
    if args.command == "init":
        from please_merge_my_pr.onboarding import run_init

        return run_init(args.config)
    if args.command == "config":
        from please_merge_my_pr.onboarding import run_config

        values = [
            getattr(args, name) for name in ("key", "value") if hasattr(args, name)
        ]
        return run_config(args.config_command, values, args.config)
    try:
        from please_merge_my_pr.config import load_config

        config = load_config(args.config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    from please_merge_my_pr.github.http import UrllibTransport

    live_transport = transport or UrllibTransport()
    if args.command in {"label", "merge", "comment", "approve"}:
        return _action(args, config, live_transport)
    if args.command in {"hide", "unhide", "snooze", "rules"}:
        return _local(args, config)
    if args.command == "open":
        from please_merge_my_pr.actions import open_pr

        try:
            opened = open_pr(config, args.pr)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not opened:
            print("could not open browser", file=sys.stderr)
            return 1
        return 0
    if args.command == "egress":
        print("egress data is available only inside chat", file=sys.stderr)
        return 2
    return _read_command(args, config, live_transport)


def state_store() -> Any:
    from please_merge_my_pr.store import Store

    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return Store(root / "please-merge-my-pr" / "state.sqlite3")


def candidates(config: Any, transport: Transport, *, demo: bool = False) -> list[Any]:
    if demo:
        from please_merge_my_pr.demo_data import load_demo

        return load_demo()
    from please_merge_my_pr.github.auth import token
    from please_merge_my_pr.github.read import read_candidates

    return read_candidates(transport, config, token(config))


def _read_command(args: argparse.Namespace, config: Any, transport: Transport) -> int:
    from please_merge_my_pr.github.auth import AuthError, token
    from please_merge_my_pr.github.read import GitHubError

    try:
        if args.command == "watch" and not args.demo:
            return _watch_live(config, transport, token(config))
        found = candidates(config, transport, demo=bool(args.demo))
    except (AuthError, GitHubError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    now = datetime.now(UTC)
    if args.command == "list":
        return render_list(
            found, config, now, args.limit or config.display_limit, args.all, args.json
        )
    if args.command == "watch":
        return _watch_demo(found, config, now)
    selected = select(args.pr, found)
    if isinstance(selected, int):
        return selected
    scored = score_candidate(selected, config, now)
    if args.command == "why":
        return render_why(selected, scored, args.json)
    if args.command == "show":
        return render_show(selected, scored)
    return 2


def score_candidate(candidate: Any, config: Any, now: datetime) -> Any:
    from please_merge_my_pr.events import Event
    from please_merge_my_pr.scoring import score

    if not isinstance(candidate.event, Event):
        raise TypeError("candidate has no event")
    return score(candidate.event, candidate.reads, config.weights, config, now)


def queue_entries(
    found: list[Any], config: Any, now: datetime, *, use_state: bool = True
) -> tuple[list[Any], int]:
    from please_merge_my_pr.events import Event, ReviewTurn
    from please_merge_my_pr.queue import In, Unknown, eligible
    from please_merge_my_pr.scoring import Entry

    store = state_store() if use_state else None
    entries: list[Any] = []
    could_not_check = 0
    for candidate in found:
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
        if store is not None and store.filtered(
            candidate.repo, candidate.number, now.astimezone(UTC).isoformat()
        ):
            continue
        entries.append(
            Entry(
                candidate.repo,
                candidate.number,
                review.requested_at,
                score_candidate(candidate, config, now),
            )
        )
    return entries, could_not_check


def render_list(
    found: list[Any],
    config: Any,
    now: datetime,
    limit: int,
    show_all: bool = False,
    as_json: bool = False,
    *,
    overlay: Any = None,
) -> int:
    from please_merge_my_pr.scoring import rank
    from please_merge_my_pr.ui.screens import list_screen

    entries, could_not_check = queue_entries(found, config, now)
    groups = rank(entries)
    all_ranked = [(group.rank, entry) for group in groups for entry in group.entries]
    shown_count = (
        len(all_ranked)
        if show_all
        else sum(1 for group_rank, _ in all_ranked if group_rank <= limit)
    )
    ranked = all_ranked
    if overlay is not None:
        ordered = overlay.apply([entry for _, entry in ranked])
        ranks = {id(entry): rank_value for rank_value, entry in ranked}
        ranked = [(ranks[id(entry)], entry) for entry in ordered]
    ranked = ranked[:shown_count]
    items = [
        {
            "rank": group_rank,
            "repo": entry.repo,
            "number": entry.number,
            "score": entry.scored.score,
            "reason": entry.scored.reason,
        }
        for group_rank, entry in ranked
    ]
    payload = {
        "shown": len(items),
        "total": len(entries),
        "could_not_check": could_not_check,
        "items": items,
    }
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return 0
    repos = {entry.repo for entry in entries}
    repo_label = next(iter(repos)) if len(repos) == 1 else f"{len(repos)} repos"
    header = f"{repo_label} · {len(entries)} in queue"
    if could_not_check:
        header += f" · {could_not_check} could not check"
    more = len(entries) - len(items)
    footer = f"+{more} more · please-merge-my-pr list --all" if more else None
    if overlay is None:
        print(
            list_screen(
                header,
                (
                    (entry.number, entry.scored.reason, entry.scored.score)
                    for _, entry in ranked
                ),
                footer,
            ),
            end="",
        )
    else:
        from please_merge_my_pr.text import wrapped

        print(header)
        for item in items:
            number = item["number"]
            assert isinstance(number, int)
            reason = overlay.reason(str(item["repo"]), number)
            marker = " [moved by AI]" if reason is not None else ""
            line = (
                f"#{item['number']} {item['reason']}   [score {item['score']}]{marker}"
            )
            print("\n".join(wrapped(line)))
            if reason is not None:
                print("\n".join(wrapped(reason, prefix="AI: ", continuation="AI: ")))
        if footer:
            print(footer)
    return 0


def select(reference: str, found: list[Any]) -> Any | int:
    matches = []
    if "#" in reference:
        repo, raw = reference.rsplit("#", 1)
        try:
            number = int(raw)
        except ValueError:
            number = -1
        matches = [
            item for item in found if item.repo == repo and item.number == number
        ]
    else:
        try:
            number = int(reference)
        except ValueError:
            number = -1
        matches = [item for item in found if item.number == number]
    if len(matches) == 1:
        return matches[0]
    if matches:
        print("pull request number is ambiguous:", file=sys.stderr)
        for item in matches:
            print(f"  {item.repo}#{item.number}", file=sys.stderr)
    else:
        print(f"pull request not found: {reference}", file=sys.stderr)
    return 1


def render_why(candidate: Any, scored: Any, as_json: bool = False) -> int:
    from please_merge_my_pr.ui.screens import why_screen

    payload = {
        "repo": candidate.repo,
        "number": candidate.number,
        "score": scored.score,
        "exact": scored.exact,
        "rows": [asdict(row) for row in scored.rows],
    }
    if as_json:
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


def render_show(candidate: Any, scored: Any) -> int:
    from please_merge_my_pr.events import PRDetails
    from please_merge_my_pr.ui.screens import show_screen

    title = (
        candidate.reads.pr.title
        if isinstance(candidate.reads.pr, PRDetails)
        else f"{candidate.repo}#{candidate.number}"
    )
    print(show_screen(title, scored.reason, scored.score), end="")
    return 0


def _action(args: argparse.Namespace, config: Any, transport: Transport) -> int:
    from please_merge_my_pr.actions import (
        build,
        confirm,
        execute,
        permitted_without_prompt,
        preview,
    )
    from please_merge_my_pr.github.auth import AuthError, token

    values = vars(args).copy()
    try:
        action = build(config, token(config), args.command, values)
    except (AuthError, KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.dry_run:
        ok, message = execute(action, transport, dry_run=True)
        return 0 if ok else 1
    print(preview(action), end="")
    if not permitted_without_prompt(action, state_store()) and not confirm():
        print("declined")
        return 0
    ok, message = execute(action, transport)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def _local(args: argparse.Namespace, config: Any) -> int:
    from please_merge_my_pr.actions import split_pr
    from please_merge_my_pr.rules import add, listing

    store = state_store()
    if args.command == "rules":
        if args.rules_command == "list":
            print(listing(store), end="")
            return 0
        if args.rules_command == "rm":
            if not store.remove_rule(args.rule_id):
                print("rule not found", file=sys.stderr)
                return 1
            return 0
        if not args.add and not args.remove:
            print("a label set is required", file=sys.stderr)
            return 2
        add(store, args.repo, args.add, args.remove)
        return 0
    try:
        repo, number = split_pr(args.pr)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.command == "hide":
        store.hide(repo, number)
    elif args.command == "unhide":
        store.unhide(repo, number)
    else:
        try:
            stamp = datetime.fromisoformat(args.until)
            if stamp.tzinfo is None or stamp <= datetime.now(UTC):
                raise ValueError
        except ValueError:
            print("invalid snooze time", file=sys.stderr)
            return 2
        store.snooze(repo, number, stamp.astimezone(UTC).isoformat())
    return 0


def _watch_demo(found: list[Any], config: Any, now: datetime) -> int:
    from please_merge_my_pr.scoring import rank
    from please_merge_my_pr.ui.screens import watch_screen

    entries, _ = queue_entries(found, config, now, use_state=False)
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
    from please_merge_my_pr.ui.screens import watch_screen

    items = Poller(transport, state_store(), config, token_value).poll_once(
        datetime.now(UTC)
    )
    print(
        watch_screen(
            (item.repo, item.number, item.reason, item.score) for item in items
        ),
        end="",
    )
    return 0
