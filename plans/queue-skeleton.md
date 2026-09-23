<!-- role: Plan | model: claude-opus-5-5 | base: none (not a git repo) | date: 2026-09-22 -->
Status: draft
Phases: 5

# Queue skeleton

Week 1 of `PLAN.md` (1.1–1.4). No model calls.

Build order:
1. `weights-research` — decide the formula and default weights (no code)
2. `cli-design` — decide the look of every screen, in `mock/` (no code)
3. `queue-skeleton` (this) — data in, rank, print
4. `queue-signals` — blocked_people, due_soon, urgency + credibility
5. `queue-actions` — action tiers, label, merge, comment
6. `replay-harness` — GH Archive replay, policies, leakage guard

Phase 3 (scorer) follows `research/weights.md`. Phase 5 (screens) follows
`design/cli.md`.

The summary step is the only model code. It lands after all four.

## Goal

`please-merge-my-pr list` prints real open PRs from a real repo, ranked, one line each.
Every line has a reason built from fixed templates. No LLM is involved.

Example line:
```
#412 touches auth/ · 11d old · 38 lines   [score 45]
```

## Out of scope

Handled by later plans. Do not build them here.

- `blocked_people`, `due_soon`, `urgency_claim`, credibility → `plans/queue-signals.md`
- Actions: label, merge, comment → `plans/queue-actions.md`
- Replay beyond one fixture → `plans/replay-harness.md`
- Real summaries, Token Factory, LangSmith, `please-merge-my-pr egress` → later plan
  (this plan only builds the empty slot the summary will fill)

## Invariants

Stated as absolutes. Every one gets at least one gate.

- **I1 — One ingestion path.** `Event.from_github_api(x)` and
  `Event.from_gh_archive(y)` for the same PR at the same moment return equal
  `Event` objects (`==` is true).
- **I2 — Scorer is pure.** `score(event, weights, config, now)` does no I/O, no
  network, no clock read, no randomness. Same inputs → same output, bit for bit.
  Time enters only through the `now` argument.
- **I3 — Signals are bounded.** Every signal returns `(value, fragment)` with
  `0.0 <= value <= 1.0` for every input, including zero-line diffs, empty file
  lists, and missing fields.
- **I4 — PR text never ranks.** In this feature no signal reads `title`,
  `body`, or comments. Changing any of them changes the score by exactly 0 and
  the reason line not at all.
- **I5 — Reason lines are template-only.** A reason line is built only from
  fixed template strings, the PR number, numbers computed by signals, and
  strings from config (for example a risk glob). No substring of `title` or
  `body` ever appears in it.
- **I6 — No PR content at rest.** SQLite holds metadata only: cursor, ETag,
  Last-Modified, poll interval, timestamps, repo names, PR numbers. It never
  holds title, body, comments, or diff text.
- **I7 — Poll interval is respected.** The poller never sends a request sooner
  than the last `X-Poll-Interval` allows. Every request after the first carries
  `If-Modified-Since` (and `If-None-Match` when an ETag is known). A `304`
  emits zero events.
- **I8 — Order is total and stable.** Ties in score break by a fixed rule, so
  the same inputs always print the same order.
- **I9 — No model code.** Nothing in this feature imports an LLM client or
  sends text to a model.

## Phases

### 1. Event model — `src/events.py`

- Frozen dataclass `Event`: `repo`, `number`, `author`, `author_association`,
  `title`, `body`, `labels`, `changed_files`, `additions`, `deletions`,
  `base_ref`, `head_ref`, `milestone`, `created_at`, `updated_at`, `draft`.
- `from_github_api(pr: dict, files: list[dict]) -> Event`
- `from_gh_archive(event: dict) -> Event`
- Fixtures in `tests/fixtures/`: one real REST API response, one real GH
  Archive `PullRequestEvent`, for the same PR.
- Times are timezone-aware UTC. Labels are a sorted tuple. Files are a sorted
  tuple of paths.

Risk: GH Archive payloads may lack fields the REST API has (for example the
changed-file list). Check the real fixture before writing the constructor. If
a field cannot be filled from both sources, that is a product decision (see
Open questions), not a workaround.

### 2. Cheap signals — `src/signals/`

One module per signal. Each exports `extract(event, config, now) -> (float, str)`.

| Signal | Value | Fragment |
|---|---|---|
| `author_role` | role weight from config; fallback by `author_association` | `from maintainer` |
| `diff_size` | `1 - min(1, (additions + deletions) / cap)`, `cap` in config | `38 lines` |
| `risk_paths` | 1 if any changed file matches a config glob, else 0 | `touches auth/` |
| `age` | `min(1, days_since(created_at, now) / cap_days)` | `11d old` |

A signal with value 0 returns an empty fragment.

### 3. Scorer — `src/scoring.py`, `config/weights.yaml`

- `score(event, weights, config, now) -> Scored(score, reason)`.
- `score = round(100 * sum(w_i * v_i) / sum(w_i))`. Range 0–100.
- `reason` = the 3 non-empty fragments with the most points, joined with
  ` · `. Ties in points break by fixed signal order.
- Ranking helper sorts by score descending, then tie rule (I8).
- Loads nothing itself. The caller loads YAML and passes it in (keeps I2).

### 4. Polling ingestion — `src/ingest/poll.py`

- Polls `GET /notifications` on an interval.
- Sends `If-Modified-Since` / `If-None-Match`. Obeys `X-Poll-Interval`.
- For each PR notification, fetches the PR and its files, then builds an
  `Event` with `from_github_api`.
- Stores cursor, ETag, Last-Modified, interval in SQLite (metadata only, I6).
- CLI: `please-merge-my-pr watch` prints one line per new event.
- Tests use a fake HTTP layer. No real network in tests.

### 5. `please-merge-my-pr list` — `src/cli.py`

Screens follow `mock/queue_mock.py`. Look there for layout.

- `please-merge-my-pr list` — fetches open PRs for repos in config, builds `Event`s,
  scores, prints top N. Format: `#<number> <reason>   [score <n>]`.
  `--limit N` (default 3), `--all`. Drafts hidden, count shown.
- `please-merge-my-pr why <n>` — table of every signal: value, weight, points, fragment.
- `please-merge-my-pr show <n>` — header, reason line, then the summary slot.
- Summary slot: `src/summary.py` defines a `Summarizer` protocol,
  `summarize(event, diff) -> Summary | None`, and `NullSummarizer`, which
  always returns `None`. `show` prints `summary: not enabled` for `None`.
  No model client exists yet (I9).
- `--demo` on every command reads `tests/fixtures/demo/` instead of GitHub,
  so screens work with no credentials.
- Manual check: run against one real repo and paste the output into
  `handoff.md`. This is the Week 1 gate from `PLAN.md`.

## Gates to write

For the Write-the-gates role. Each maps to an invariant.

- `test_event_parity` — API fixture and Archive fixture give equal `Event` (I1)
- `test_score_pure` — same inputs twice, equal output; network and clock
  patched to raise if touched (I2)
- `test_signal_bounds` — table of edge events, every value in [0, 1] (I3)
- `test_text_does_not_rank` — change title/body to adversarial text; score
  delta is exactly 0 and reason is identical (I4)
- `test_reason_has_no_pr_text` — canary string in title/body never appears in
  reason (I5)
- `test_db_has_no_content` — run the poller on fixtures; scan every SQLite
  table and column; canary title/body absent (I6)
- `test_poll_interval` — fake server says `X-Poll-Interval: 60`; no request is
  sent before 60 s of fake time (I7)
- `test_304_emits_nothing` — fake server returns 304; zero events (I7)
- `test_tie_order` — equal scores print in the tie-rule order, every run (I8)
- `test_no_llm_imports` — no module under `src/` imports `openai`,
  `anthropic`, or `langsmith` (I9)
- `test_why_adds_up` — the points in `please-merge-my-pr why` sum to the score in
  `please-merge-my-pr list`, within rounding (I2)
- `test_demo_no_network` — every command with `--demo` runs with the
  network patched to raise (I9)

## Assumptions

Stated so work can go on. The Grade role or a human may overturn them.

- Score is shown as an integer 0–100.
- Tie rule: older `created_at` first, then lower PR number.
- `please-merge-my-pr list` fetches live from GitHub each run. It reads no stored PR data.
- `age` cap is 14 days; `diff_size` cap is 500 lines. Both live in config.

## Open questions

Product decisions. Not picked here.

1. Click or Typer for the CLI?
2. Python version? (Package tool decided: uv, published to PyPI — see `PLAN.md`.)
3. Which real repo is the Week 1 gate run against?
4. Auth: a personal access token in `.env`, or the `gh` CLI's token?
5. If GH Archive lacks a field the API has (for example changed files), do we
   (a) drop the field from `Event`, (b) allow `None` in both constructors, or
   (c) fetch the missing part from the API during replay?
6. Does `please-merge-my-pr watch` feed `please-merge-my-pr list`, or are they separate for now?
