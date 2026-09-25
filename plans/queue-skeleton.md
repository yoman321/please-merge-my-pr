<!-- role: Review the build | model: claude-opus-5-5 | base: 569eee1461ed51a4b4d639c61ee7ed1ae77bee3c | date: 2026-09-25 -->
Status: frozen
Phases: 7

# Queue skeleton

Week 1 of `PLAN.md` (1.1–1.4). Step 3 of the build order. No model code.

Revised 2026-09-24. The human asked for "the whole scaffolding of the CLI
without implementing the LLM". This revision:

- follows the `weights-research` decisions, except later decisions 10–12
  below supersede its dropped-signal and blocking rules;
- fixes its two Plan review findings about this plan (W8 fields, W12 ties);
- adds the package and the full command tree, with later plans' commands as
  inert stubs;
- moves demo data into the package, so `uvx please-merge-my-pr --demo` works
  from the wheel;
- records the human's later decisions about linked PRs and omitted signals;
- splits the two data sources (decision 16). Recent GH Archive PR payloads
  lost most PR fields. `Event` keeps the four fields both sources still
  carry. Every other current fact lives in `Reads`; `Reads.pr` is REST-only,
  while the other reads use the sources named in phase 5.

`weights-research` set no numbers. On 2026-09-24 the human picked the
weights from the 01:50 chat example (§ Defaults). The human omitted the
`author_group` and standalone `lockfile` signals for now. Lockfile patterns
remain only as a discount inside `diff_size`.

Screens follow `design/cli.md` once it exists. Until then they copy
`mock/queue_mock.py`. `cli-design` is still `draft`.

## Goal

`please-merge-my-pr list` prints the open PRs where a person asked me by
name to review. They are ranked, one line each. Each line has a reason built
from fixed templates. No model is involved.

`please-merge-my-pr --help` lists every retained command in phase 1. Commands
built by later plans say so and exit. Commands for omitted work do not appear.

Example line:
```
#412 touches auth · waiting 7d · 380 lines   [score 29]
```

## What "scaffolding" means here

Assumption. The Grade role or the human may overturn it.

- **Built for real:** the package, `list`, `why`, `show`, `watch`, the four
  cheap signals, the scorer, GitHub reads, the summary slot, and `--demo`.
- **Stubs only:** every retained command owned by `onboarding`,
  `queue-actions`, and `summaries`. A stub parses nothing, does nothing, and
  exits 2 (I13).
- **Not here at all:** the signals owned by `queue-signals`, replay beyond
  one fixture, and any model client.

## Out of scope

Handled by later plans or intentionally omitted. Do not build them here.

- `urgency`, people-waiting `blocks`, and `due_soon` →
  `plans/queue-signals.md`
- `blocks` uses assignees from both manually linked issues and GitHub issue
  dependencies, plus authors of open PRs above this PR in a stack.
  Linked-issue kinds are omitted for now.
- `label`, `merge`, `comment`, `approve`, `hide`, `snooze`, `open`, `rules`
  → `plans/queue-actions.md` (stubs here)
- The `author_group` and standalone `lockfile` signals. Omitted for now by
  the human on 2026-09-24. Lockfile discounting inside `diff_size` remains.
- `init`, `config`, and full config validation → `plans/onboarding.md`
  (stubs here)
- Replay beyond one fixture → `plans/replay-harness.md`
- Summaries, Token Factory, LangSmith, `egress` → `plans/summaries.md`
  (this plan builds the empty slot and an `egress` stub)
- The final look of each screen → `plans/cli-design.md`

## Invariants

Stated as absolutes. Every one gets at least one gate.

- **I1 — One event shape.** `Event` has exactly four fields: `repo`,
  `number`, `base_ref`, `head_ref`. For the same PR,
  `Event.from_github_rest(pr)` and `Event.from_gh_archive(event)` return
  equal `Event` objects (`==` is true). Every other current fact lives in
  `Reads` (phase 2), with sources fixed by phase 5. GH Archive says which PR
  changed and when. The live APIs say what the PR is now.
- **I2 — Scorer is pure.** `score(event, reads, weights, config, now)` does
  no I/O, no network, no clock read, and no randomness. Same inputs → same
  output, bit for bit. Time enters only through `now`.
- **I3 — Signals are bounded.** Every signal returns a `SignalResult` with
  `0.0 <= value <= 1.0` for every input. That includes zero-line diffs,
  empty file lists, a request time after `now`, and every `Unavailable`
  read.
- **I4 — PR text never ranks.** No signal and no gate reads `title` or
  `body`. Changing either one changes the score by exactly 0, the reason not
  at all, and queue membership not at all.
- **I5 — Reason lines are template-only.** A reason line is built only
  from fixed template strings, numbers computed by signals, and names from
  config (for example a risk group name). No string from PR data appears in
  it. That covers title, body, branch names, label names, file paths, and
  logins.
- **I6 — No PR content at rest.** SQLite holds metadata only: cursor, ETag,
  Last-Modified, poll interval, timestamps, repo names, PR numbers. It never
  holds titles, bodies, comments, file paths, or diff text.
- **I7 — Poll interval is respected.** The poller never sends a request
  sooner than the last `X-Poll-Interval` allows. Every request after the
  first carries `If-Modified-Since`, plus `If-None-Match` when an ETag is
  known. A `304` emits zero events.
- **I8 — Queue entry follows W8.** A PR is in the queue only when all of
  these hold. It is not a draft. The viewer has a current by-name review
  request on it. That request has `asCodeOwner` false. The matched
  `review_requested` event was requested by a user, not a bot. Any other
  case → out. A failed read of any of these → out, and counted in the
  `list` header as "could not check". Accepted limit: GitHub can turn a team
  request into named-member requests. If that result has the same fields as
  a manual by-name request, this version lets it in.
- **I9 — Unavailable is not absent (W10).** A candidate-scoped failed read
  (403, 404, 429 or rate limit, 5xx, network error, timeout, invalid
  response, or missing preview field) becomes `Unavailable(reason)`.
  It never becomes an empty value. Its signals score 0 points with status
  `unavailable`. The denominator stays the sum of all weights. That includes
  weights of signals not built yet, which score 0 with status `not_built`.
- **I10 — Ties are shared (W12).** The displayed score is an integer. Equal
  displayed scores share one rank, as competition ranking (1, 2, 2, 4).
  Inside a tied group the display order is fixed (§ Scorer). Every run
  prints the same order. `--limit N` never splits a group: it prints every
  PR whose rank is ≤ N.
- **I11 — `why` adds up.** For every PR, the `points` in `why --json` sum to
  the exact score, and 100 minus the `off` values equals it too, both
  within 1e-9. Rounding that exact score gives the score `list` prints.
- **I12 — No model code.** No module under `src/please_merge_my_pr/`
  imports `openai`, `anthropic`, `langsmith`, or any other model client.
  Nothing sends text to a model.
- **I13 — Stubs are inert.** When run, every retained command listed in
  phase 1 that this plan does not build prints one line to stderr,
  `not built yet — see plans/<name>.md`, and exits 2. It sends no network
  request and writes no file. Its `--help` is the only exception: help prints
  the command's one-line purpose to stdout and exits 0, with no I/O beyond
  stdout.
- **I14 — Demo runs anywhere.** `--demo` reads demo data shipped inside the
  package through `importlib.resources`. It needs no token and no config
  file, and it sends no network request.
- **I15 — Directions follow `weights-research`.** A bigger diff never gets a
  lower `diff_size` value (B1). Touching a risky path raises `risk_paths`
  (B2). A failing check or a merge conflict sets `ci_state` to 0 (B8). `age`
  reads only the current request time, and a re-request restarts it (B10).
- **I16 — Omitted signals stay omitted.** The weighted registry contains
  exactly `urgency`, `blocks`, `risk_paths`, `due_soon`, `age`, `diff_size`,
  and `ci_state`. It has no `author_group` or standalone `lockfile` signal.
  Lockfile patterns affect only the `diff_size` line count.
- **I17 — GitHub credentials stay secret.** The token is read at run time.
  It never appears in stdout, stderr, exceptions, SQLite, config, request
  URLs, or test snapshots. Every request URL starts with the configured
  `github.api_url`; URLs returned inside GitHub payloads are never followed.

## Phases

### 1. Package and command tree — `pyproject.toml`, `src/please_merge_my_pr/cli.py`

- `pyproject.toml`: package `please-merge-my-pr`, import name
  `please_merge_my_pr`, console script
  `please-merge-my-pr = "please_merge_my_pr.cli:main"`. `python -m
  please_merge_my_pr` also works, through `__main__.py`.
- No runtime dependencies. Everything uses the standard library:
  `argparse`, `urllib.request`, `sqlite3`, `tomllib`, `json` (decisions 3
  and 6). `requires-python = ">=3.13"` (decision 4).
- Dev dependencies, approved (decision 5): pytest, ruff, mypy, and the build
  backend `uv init --package` writes. No others. Read `uv init --help` and
  the installed tools' `--help` before writing their config.
- Command tree, with `--demo` and `--config PATH` as global flags:

| Command | Built here | Owner plan |
|---|---|---|
| `list [--limit N] [--all] [--json]` | yes | `queue-skeleton` |
| `why <pr> [--json]` | yes | `queue-skeleton` |
| `show <pr>` | yes | `queue-skeleton` |
| `watch` | yes | `queue-skeleton` |
| `init`, `config` | stub | `onboarding` |
| `label`, `merge`, `comment`, `approve`, `hide`, `snooze`, `open`, `rules` | stub | `queue-actions` |
| `egress` | stub | `summaries` |

- `<pr>` is a number, or `owner/repo#number`. A bare number that matches
  PRs in two repos → exit 1, listing the matches.
- A stub takes any arguments and ignores them (I13). Its `--help` gives the
  one-line purpose from its plan. The later plan defines its real arguments.
- `--limit` must be a positive integer. Zero or a negative value is a usage
  error and exits 2. `--all` overrides the default limit.
- `README.md`: a setup section with the §5 commands below (AGENTS.md §9).

### 2. Event and reads — `src/please_merge_my_pr/events.py`

- Frozen dataclass `Event`, with only the fields both sources carry:
  `repo`, `number`, `base_ref`, `head_ref` (I1).
  - Checked on hour 2026-09-24-15 UTC: in 1929 `PullRequestEvent`s,
    `payload.pull_request` has only `base`, `head`, `id`, `number`, `url`.
    `base` and `head` hold only `ref`, `sha`, `repo`. GitHub's live
    `/events` feed has the same shape, so no archive mirror has more.
  - `author_association` is dropped. W9 says no GitHub data sets a group.
  - `changed_files` moves to `Reads`.
- `Event.from_github_rest(pr: dict) -> Event`. Input is the REST
  `GET /repos/{owner}/{repo}/pulls/{number}` body.
- `Event.from_gh_archive(event: dict) -> Event`. Input is one GH Archive
  `PullRequestEvent`. `repo` is `repo.name`. `base_ref` and `head_ref` are
  `payload.pull_request.base.ref` and `.head.ref`.
- Frozen dataclass `Reads`. Each field is a value or `Unavailable(reason)`:
  - `pr: PRDetails`, from the REST PR body only. `PRDetails` is `author`,
    `title`, `body`, `labels`, `additions`, `deletions`, `milestone_due`,
    `created_at`, `updated_at`, `draft`.
  - `files: tuple[FileChange, ...]`. `FileChange` is `path`, `additions`,
    `deletions`, sorted by path.
  - `review: ReviewTurn`. It has `requested_at`, `by_name`, `as_code_owner`,
    and `requested_by_user` (a user, not a bot).
  - `ci: CIState`, one of `passing`, `failing`, `pending`, or `none`.
  - `mergeable: bool`. A REST `null` (GitHub still computing) →
    `Unavailable("computing")`.
- `Unavailable(reason)` has a fixed set of reasons: `forbidden`, `not_found`,
  `rate_limited`, `server_error`, `network_error`, `timeout`,
  `invalid_response`, `computing`, `preview_missing`, `unmatched`.
- Times are timezone-aware UTC. Labels are a sorted tuple of names.
- `PRDetails.from_github_rest(pr: dict) -> PRDetails`. Same input as
  `Event.from_github_rest`. There is no archive version.
- Fixtures in `tests/fixtures/`: one real GH Archive `PullRequestEvent` from
  a recent hour, and the real REST PR response for that same PR. A REST
  response from the archive's moment cannot be fetched. So fetch it right
  after taking the archive event, and pick a PR whose base branch did not
  change in between.

Risk: if one of the four `Event` fields is missing from the real archive
fixture, that is a plan defect. STOP and report. Do not work around it.

### 3. Signals — `src/please_merge_my_pr/signals/`

One module per signal. Each exports
`extract(event, reads, config, now) -> SignalResult(value, fragment, status)`.

- `status` is `ok`, `absent`, `unavailable`, or `not_built`.
- A signal with value 0 returns an empty fragment.
- `signals/__init__.py` holds the fixed order of all seven weighted signals:
  `urgency`, `blocks`, `risk_paths`, `due_soon`, `age`, `diff_size`,
  `ci_state`. This plan builds four of them. `urgency`, `blocks`, and
  `due_soon` come from `queue-signals`. Until then each returns value 0 with
  status `not_built`.
- `blocks` has one fixed meaning for the later plan:
  - Count distinct people, other than this PR's author, who wait on this PR.
  - Count authors of every open PR above this PR in GitHub's structured stack.
    An exact base/head branch chain may be used as the fallback.
  - Count assignees of issues returned by
    `closingIssuesReferences(userLinkedOnly: true)`.
  - Also count assignees of issues structurally blocked by those linked
    issues through GitHub issue dependencies.
  - Count each login once across both sources.
  - Only this prerequisite PR gets the boost. The PRs above it get no points
    from their link to this PR.
  - Issue kinds and prose links do not count.
  - Its fragment is `blocks 1 person` or `blocks <n> people`. The later plan
    sets the bounded count curve and cap without changing these sources.
- `urgency` has one fixed formula for the later plan:
  - Config maps the configured `low`, `medium`, `high`, and `urgent` label
    names to values in [0, 1]. `urgent` is exactly 1.
  - The highest configured urgency label on the PR wins.
  - If no configured urgency label is present, use the configured `medium`
    value.
  - Label applier, trust, author, and past label history have no effect.
  - `urgency_points = 100 × weights.urgency × x_urgency / Σw`. With the
    default weight 30 and `Σw = 100`, this is `30 × x_urgency`.
  - The later plan must set the provisional default values for `low`,
    `medium`, and `high`; this plan does not guess them.

| Signal | Reads | Value | Fragment |
|---|---|---|---|
| `risk_paths` | `reads.files`, config `risk_paths` (group name → globs) | 1 if any file matches any group, else 0 | `touches <group>`, the first matching group in config order |
| `age` | `reads.review.requested_at`, `now` | `min(1, max(0, hours) / (age_cap_days × 24))` | `waiting 5h` under 1 day, else `waiting 7d` (whole days, rounded down) |
| `diff_size` | `reads.pr`, `reads.files`, config `lockfiles` | `min(1, max(0, lines) / diff_cap_lines)`. `lines` = `additions + deletions`, minus the lines of files that match `lockfiles` | `380 lines` |
| `ci_state` | `reads.ci`, `reads.mergeable` | 0 if `failing` or not mergeable, else 1. `pending` and `none` count as 1 | empty |

- Any read a signal needs is `Unavailable` → value 0, status `unavailable`
  (I9).
- `diff_size` needs `reads.files` for the lockfile discount. So files
  `Unavailable` → `diff_size` `unavailable` too. It reads `additions` and
  `deletions` from `reads.pr`, never from `Event`. The discount is part of
  size ("lockfiles should count for less"). It is not the `lockfile` signal,
  which is left out.
- Globs match the full POSIX path with `PurePosixPath.full_match`, which
  supports `**` (decision 4). Check its docs for 3.13 before use. Do not use
  `fnmatch`: there `**/uv.lock` misses a top-level `uv.lock` (checked on
  3.14.4).

### 4. Scorer and ranking — `src/please_merge_my_pr/scoring.py`

- `score(event, reads, weights, config, now) -> Scored(score, exact, reason,
  rows)`. `rows` holds one entry per signal: `value`, `weight`, `points`,
  `off`, `fragment`, `status`.
- Formula 13 from `weights-research`, summed in the fixed signal order:
  - `points_i = 100 × w_i × x_i / Σw`
  - `off_i = 100 × w_i × (1 − x_i) / Σw`
  - `exact = Σ points_i`. The code computes it this way only.
  - The same number, in the human's frame: `exact = 100 − Σ off_i`. 100
    is the most important, and 0 means no importance. The defaults add up
    to 100, so each weight is the most points its signal can take off.
  - `score = floor(exact + 0.5)`, which rounds half up (decision 2).
- `Σw` is over all seven weights, built or not (I9). While only this plan's
  four signals exist, the highest possible score is 35.
- `reason` = the 3 non-empty fragments with the most points, joined with
  ` · `. Ties in points break by the fixed signal order. If there are no
  non-empty fragments, `reason` is the fixed string `nothing notable`.
- Raises `ValueError` naming the key when any of these holds: a weight is not
  finite, a weight is negative, all weights are 0, a weight key names none
  of the seven signals, or one of the seven has no weight. Numeric caps must
  also be finite and greater than 0.
- `rank(scored) -> list[RankGroup]`:
  - groups by `score`, highest first, with competition rank numbers (I10);
  - order inside a group: earlier `requested_at` first, then `repo`, then
    lower `number`. This is display order only. Every queued PR has a
    `requested_at`, because an `Unavailable` review read keeps it out (I8).
- Loads nothing itself. The caller passes config in (I2).

#### Worked example (default weights)

PR #412: 380 non-lockfile lines. It touches `auth/` and was requested 7
days before `now`. CI passes and the PR is mergeable.

| Signal | status | x | w | points | off |
|---|---|---|---|---|---|
| urgency | not_built | 0 | 30 | 0.0 | 30.0 |
| blocks | not_built | 0 | 25 | 0.0 | 25.0 |
| risk_paths | ok | 1 | 15 | 15.0 | 0.0 |
| due_soon | not_built | 0 | 10 | 0.0 | 10.0 |
| age | ok | 0.5 | 10 | 5.0 | 5.0 |
| diff_size | ok | 0.76 | 5 | 3.8 | 1.2 |
| ci_state | ok | 1 | 5 | 5.0 | 0.0 |

`exact` = 28.8 (= 100 − 71.2), `score` = 29, reason
`touches auth · waiting 7d · 380 lines`.

Rounding case: `files` `Unavailable`, CI failing, requested 3.5 days (84 h)
before `now`. Only `age` scores: 0.25 × 10 = 2.5. `exact` = 2.5, `score` = 3.
Python's `round(2.5)` gives 2, which is why the rule is `floor(x + 0.5)`.

### 5. GitHub reads — `src/please_merge_my_pr/github/`

- `http.py`: one `Transport` protocol, `send(Request) -> Response`. The real
  one uses `urllib.request`. Tests inject a fake. The base URL comes from
  config `github.api_url` (default `https://api.github.com`), never from PR
  data.
- `auth.py`: the token comes from the env var named by config
  `github.token_env` (default `GITHUB_TOKEN`). Otherwise it comes from
  `gh auth token` when `gh` is on `PATH`. Otherwise → exit 1 with one line.
  Empty tokens are treated as missing. The token is never logged, printed,
  written, placed in a URL, or included in an exception (I17).
- `read.py`, per run:
  1. Candidates: search `is:pr is:open review-requested:@me`, limited to
     config `repos` when that is set, and read every result page. This is a
     superset. The I8 gate does the real filtering.
  2. Per candidate, keyed only by `(repo, number)`, so the same reads can run
     for an archive `Event` later (`replay-harness`):
     - the REST PR → `Event` and `Reads.pr`, from one request. If it fails,
       there is no `Event`. The PR is out and counted as "could not check"
       (decision 7);
     - REST files, paginated → `Reads.files`;
     - all pages of GraphQL `reviewRequests`, with `asCodeOwner`,
       `requestedReviewer.__typename`, and the requested reviewer's login
       (A1). The same query reads `viewer.login`. `by_name` is true only for
       a `User` whose login equals `viewer.login`; its `asCodeOwner` supplies
       the matching value;
     - the GraphQL last-commit status rollup → `Reads.ci`;
     - REST PR `mergeable` → `Reads.mergeable`;
     - all pages of the REST issue timeline, `review_requested` events (A4)
       → the matched event.
  3. Match rule (A4): the latest `review_requested` event whose requested
     reviewer is the viewer. Its `created_at` is `requested_at`. Its
     requester's type is `User` → `requested_by_user`. No match while a
     current request exists → `Unavailable("unmatched")`.
  4. Each per-candidate read that fails → `Unavailable(reason)` (I9). A
     failed candidate read never aborts the run. A search failure, a 401, or
     a failure to identify `viewer.login` exits 1, because the run cannot
     discover or check candidates correctly.
- Build every request URL from `github.api_url` plus fixed endpoint pieces.
  Never send a request to `url`, `html_url`, or any other URL read from an
  API payload (I17).
- Before writing any request, read GitHub's current docs for that endpoint
  and field (AGENTS.md §8). Do not write a query from memory.
- `src/please_merge_my_pr/queue.py`: `eligible(event, reads) -> In | Out(reason)
  | Unknown(reason)` (I8), then score and rank.

### 6. Screens, summary slot, demo — `src/please_merge_my_pr/ui/`, `summary.py`, `demo/`

- `ui/theme.py`: color tokens. Plain text when stdout is not a terminal or
  `NO_COLOR` is set. `ui/screens.py`: one render function per screen. Logic
  modules return plain data and never format output.
- `list`:
  - header: `<repo or "N repos"> · <n> in queue`, plus
    ` · <k> could not check` when k > 0;
  - one line per PR: `#<number> <reason>   [score <n>]`;
  - `--limit N` (default 3), `--all`;
  - footer: `+<m> more · please-merge-my-pr list --all` when some are cut.
- `why <pr>`: one row per signal, all seven: value, weight, points, off,
  fragment, and the status when not `ok`. Then the exact total, shown both
  as `Σ points` and as `100 − Σ off`, and the rounded score.
- `show <pr>`: the header (title shown for display only), the reason line,
  then the summary slot.
- `--json` on `list` and `why` dumps the same plain data with sorted keys.
  - `list`: `{shown, total, could_not_check, items: [{rank, repo, number,
    score, reason}]}`
  - `why`: `{repo, number, score, exact, rows: [...]}`
- Summary slot, `summary.py`: a `Summarizer` protocol,
  `summarize(event, diff) -> Summary | None`, and `NullSummarizer`, which
  always returns `None`. `show` prints `summary: not enabled` for `None`.
- Config (`config.py`):
  - a minimal loader;
  - built-in defaults in code;
  - an optional user file at
    `$XDG_CONFIG_HOME/please-merge-my-pr/config.toml` (default
    `~/.config/...`);
  - `--config PATH` overrides;
  - no file → built-in defaults. `onboarding` O1 changes this later.
- Demo data: `src/please_merge_my_pr/demo/demo.json`, package data. It holds
  `Event` + `Reads` pairs modeled on `mock/queue_mock.py`, updated to this
  plan:
  - one injection PR, like #409;
  - one draft, one team-only request, one code-owner request, and one
    bot-requested PR (all four out, I8);
  - one PR with an `Unavailable` read;
  - one tie.
- Manual check, the Week 1 gate from `PLAN.md`: run `list` against one real
  repo. Paste the output into `handoff.md`. Record whether the A4 match rule
  held on real data. The human picks the repo after the build (decision 8),
  so this check is not part of the Build session's done.

### 7. Watch — `src/please_merge_my_pr/ingest/poll.py`, `store.py`

- Polls `GET /notifications` on an interval. Sends `If-Modified-Since` and
  `If-None-Match`. Obeys `X-Poll-Interval` (I7).
- Only notifications with reason `review_requested` about a PR lead to a
  fetch. The fetched PR must pass the I8 gate before a line prints:
  `+ owner/repo#412 <reason>   [score 29]`.
- The fetch URL is rebuilt from the configured base, notification repo, and
  PR number. The poller never follows `subject.url` from the notification
  payload (I17).
- `store.py`: SQLite at `$XDG_STATE_HOME/please-merge-my-pr/state.sqlite3`.
  Tests pass a temp path. Tables:
  - `poll_state(key, last_modified, etag, poll_interval, last_poll_at)`
  - `seen(repo, number, requested_at)`, so one request turn prints once.
  - Metadata only (I6).
- `watch --demo` prints each demo PR in the queue as a new-event line, then
  exits 0.
- Tests use a fake transport and a fake clock. No real network.

## Defaults

Weights picked by the human on 2026-09-24: the example set from the 01:50
chat, which adds up to 100. `author_group` and standalone `lockfile` are
omitted for now. `replay-harness` may tune the seven retained weights later.
Caps accepted as proposed on 2026-09-24 (decision 1).

| Key | Default | Bounds | Built in |
|---|---|---|---|
| `weights.urgency` | 30 | finite, ≥ 0 | `queue-signals` |
| `weights.blocks` | 25 | finite, ≥ 0 | `queue-signals` |
| `weights.risk_paths` | 15 | finite, ≥ 0 | this plan |
| `weights.due_soon` | 10 | finite, ≥ 0 | `queue-signals` |
| `weights.age` | 10 | finite, ≥ 0 | this plan |
| `weights.diff_size` | 5 | finite, ≥ 0 | this plan |
| `weights.ci_state` | 5 | finite, ≥ 0 | this plan |
| `age_cap_days` | 14 | finite, > 0 | this plan |
| `diff_cap_lines` | 500 | finite, > 0 | this plan |
| `risk_paths` | `auth = ["auth/**"]`, `billing = ["billing/**"]`, `migrations = ["migrations/**"]` | group → globs | this plan |
| `lockfiles` | `**/uv.lock`, `**/package-lock.json`, `**/yarn.lock`, `**/pnpm-lock.yaml`, `**/poetry.lock`, `**/Cargo.lock`, `**/go.sum` | globs | this plan (size discount) |
| `repos` | empty (all repos) | `owner/repo` list | this plan |

## Commands for AGENTS.md §5

AGENTS.md §5 is still placeholders, and only the human writes AGENTS.md.
Proposed values:

```bash
<setup>        uv sync
<test-fast>    uv run pytest -q -x
<test-full>    uv run pytest -q
<test-single>  uv run pytest -q <path>::<test>
<typecheck>    uv run mypy src
<lint>         uv run ruff check . && uv run ruff format --check .
<build>        uv build
```

If a required test or build tool is missing, the agent asks the human before
downloading or installing it. It never skips a required check because the tool
is missing.

### One-time gate bootstrap exception

Approved by the human on 2026-09-24. The Write-the-gates session may create
only the import-safe package structure needed to run the gates:

- `pyproject.toml` with the package and test configuration;
- `src/please_merge_my_pr/` and its package directories;
- `__init__.py` files and module shells needed by the gates;
- signature-only public stubs needed by gate imports, with bodies that raise
  `NotImplementedError`.

This exception adds no product behavior, I/O, defaults, parsing, or business
logic. Its only purpose is to make every gate fail on missing behavior instead
of a missing module, missing import, or unbuilt fixture. The later Build session
owns every implementation.

## Gates to write

For the Write-the-gates role. Each maps to an invariant. Assert numbers.

- `test_package_and_command_tree`: the built wheel has no runtime
  dependencies, both entry points work, and `--help` lists exactly the phase
  1 commands. Each stub's `--help` exits 0 and names its purpose.
- `test_event_parity`: API fixture and archive fixture give equal `Event`.
  `Event`'s field names are exactly `repo`, `number`, `base_ref`,
  `head_ref`, and each field equals the known fixture value (I1).
- `test_score_pure`: same inputs twice give equal output. Socket, clock
  reads, and `random` are patched to raise (I2).
- `test_signal_bounds`: a table of edge inputs, including every
  `Unavailable` reason, a request after `now`, and lockfile lines greater
  than the PR total. Every value is in [0, 1] (I3).
- `test_text_does_not_rank`: adversarial title and body. The score delta
  is exactly 0, the reason is identical, and the gate result is identical
  (I4).
- `test_reason_has_no_pr_text`: a canary in title, body, branch names, label
  names, file paths, and author login. It is absent from every reason (I5).
- `test_db_has_no_content`: run the poller on fixtures. Scan every SQLite
  table and column. Canary title, body, and file path are all absent (I6).
- `test_poll_interval`: the fake server says `X-Poll-Interval: 60`. No
  request is sent before 60 s of fake time (I7).
- `test_conditional_headers`: every request after the first carries
  `If-Modified-Since`, and `If-None-Match` once an ETag is known (I7).
- `test_304_emits_nothing`: the fake server returns 304. Zero events (I7).
- `test_queue_entry`, a table (I8):
  - by-name request from a user → in;
  - team-only → out;
  - a team assignment surfaced as the same named-user fields → in under the
    accepted limit;
  - `asCodeOwner` → out;
  - bot requester → out;
  - draft → out;
  - no current request → out;
  - review read `Unavailable` → out, with `could_not_check` = 1.
- `test_unavailable_scores_zero`: the rounding case. `exact` = 2.5,
  `score` = 3, with `risk_paths` and `diff_size` status `unavailable` (I9).
- `test_full_scale`: every built signal at 1 → `exact` = 35. The three
  unbuilt signals have status `not_built`, and `Σw` = 100 (I9).
- `test_shared_rank`: scores [50, 38, 38, 20] → ranks [1, 2, 2, 4]. The same
  display order across 20 shuffled inputs. `list --limit 2` prints 3 lines
  (I10).
- `test_why_adds_up`: on every demo PR, `Σ points` = `exact` within 1e-9,
  and `floor(exact + 0.5)` = the `list` score (I11).
- `test_worked_example`: the worked example gives `exact` 28.8 within 1e-9,
  `Σ off` 71.2 within 1e-9, `score` 29, and the reason
  `touches auth · waiting 7d · 380 lines` (I2, I11).
- `test_empty_reason_fallback`: zero points from every signal gives the
  exact fixed reason `nothing notable` in plain and JSON output (I5).
- `test_no_llm_imports`: an AST scan of `src/please_merge_my_pr/` finds no
  import of `openai`, `anthropic`, or `langsmith` (I12).
- `test_stubs_inert`: every stub command, with network and file writes
  patched to raise → exit 2, and stderr names its plan file (I13).
- `test_demo_offline`: `list`, `why`, `show`, and `watch` with `--demo`,
  with no token env, no config file, and network patched to raise → exit 0
  (I14).
- `test_demo_is_package_data`: demo data loads through
  `importlib.resources`. No path under `tests/` is read (I14).
- `test_signal_directions` (I15):
  - 400 lines > 10 lines for `diff_size`;
  - lockfile-only lines give `diff_size` 0;
  - risky path 1 versus 0;
  - failing CI → 0, conflict → 0, passing → 1;
  - changing `created_at` changes `age` by 0;
  - a later `requested_at` → a smaller `age`.
- `test_omitted_signals` (I16): the registry and default weights contain
  exactly the seven named signals. `weights.author_group` and
  `weights.lockfile` each raise `ValueError`, while lockfile-only lines still
  make `diff_size` 0.
- `test_github_reads`: fake paginated REST and GraphQL responses prove that
  every page is read, `viewer.login` selects only the matching user request,
  the latest matching timeline event sets `requested_at`, and each HTTP or
  decode failure maps to its exact `Unavailable` reason (I8, I9).
- `test_auth_secret`: use a canary token from the env and from fake
  `gh auth token`; after success and forced failures, the canary is absent
  from stdout, stderr, exceptions, request URLs, SQLite, and config (I17).
- `test_payload_urls_not_followed`: put a canary host in every API payload
  URL, including notification `subject.url`; every recorded request still
  starts with the configured API base (I17).
- `test_watch_filters_and_deduplicates`: only a `review_requested` PR
  notification can print; one request turn prints once, while a later
  `requested_at` for the same PR prints once again (I6, I8).
- `test_cli_contract`: `list --json` and `why --json` have the exact phase 6
  keys; ambiguous bare PR numbers exit 1 and list matches; limit 0 and -1
  exit 2; `--limit 2` keeps the full tied rank group.
- `test_bad_numeric_config_rejected`: negative, NaN, infinity, all-zero,
  unknown, and missing weights, plus zero, NaN, and infinity caps. Each
  raises `ValueError` naming the key.

## Risks

- **GH Archive shape.** If one of the four `Event` fields is missing from a
  recent archive payload, I1 fails by design → STOP (phase 2). GitHub
  already cut the other PR fields once.
- **Replay sees the future.** REST gives a PR as it is now, not as it was.
  An archive `Event` joined with today's `Reads.pr` shows today's size,
  title, body, and draft flag. This plan has no replay, so no gate here
  depends on it. `replay-harness` must set a rule (Later plan updates).
- **A4 match rule.** Not proven by the docs. The Week 1 manual check records
  whether it held. `Unavailable("unmatched")` keeps a miss visible.
- **Team assignment ambiguity.** GitHub may replace a team request with
  named-member requests. The available fields can then look like a manual
  request. The human accepted letting that named request into this version
  on 2026-09-24.
- **Issue assignees.** An assignee may be doing the work rather than waiting
  for it. The human accepted counting assignees from both manually linked
  issues and GitHub issue dependencies as waiting people on 2026-09-24.
- **`mergeable` is `null` while GitHub computes.** Under W10 that PR ranks
  lower until the next run.
- **Rate limit.** About five reads per candidate. The W8 queue is small (2–8
  PRs), but the candidate superset can be larger.
- **Search qualifier.** Check `review-requested:@me` in GitHub's search
  docs. The I8 gate filters either way.

## Assumptions

Stated so work can go on. The Grade role or a human may overturn them.

- The scaffolding scope above.
- Display order inside a tie: earlier request first, then repo, then number.
- `why` shows `unavailable` for a failed read. This is `weights-research`
  open question 7.
- No config file → built-in defaults.
- Auth: the env var first, then `gh auth token`.
- `list` fetches live every run. It reads no stored PR data.
- `watch` and `list` stay separate.
- `ci_state`: `pending` and no checks both count as passing.

## Decisions

Answered by the human on 2026-09-24: "pick as proposed", except 8.

1. Caps: `age` full at 14 days, `diff_size` full at 500 lines. Weights are
   in § Defaults.
2. Rounding: round half up, `floor(exact + 0.5)`.
3. CLI library: `argparse`. No dependency.
4. Python floor: 3.13, for `**` globs through `full_match`.
5. Dev dependencies: pytest, ruff, mypy, and the build backend
   `uv init --package` writes. `uv` 0.12.18 is installed on this machine;
   the unchecked `PLAN.md` Phase 0 box is stale.
6. Config format: TOML, read with `tomllib`. This also answers `onboarding`
   open question 1 for reading. Writing TOML is still `onboarding`'s call.
7. A failed gate read: the PR is left out, and the `list` header counts it
   as "could not check".
8. The real repo for the Week 1 run: the human picks it after the build.
9. Replay reads: `Event` keeps only the fields both sources share. Files,
   review turn, CI, and PR details come from the API only. How replay gets
   them is `replay-harness` open question 2. Decision 16 answers part of it.
10. `author_group` and standalone `lockfile` are omitted for now. Lockfile
    patterns remain only as a `diff_size` discount.
11. `blocks` counts distinct people other than the PR author: authors of open
    PRs above it in a stack, assignees of manually linked issues, and assignees
    from GitHub issue dependencies. Only the prerequisite PR gets the boost.
12. The team-assignment ambiguity in I8 is accepted for now.
13. If a test or build tool is missing, the agent asks before downloading or
    installing it. Missing tools never justify skipping verification.
14. Urgency uses the direct configured-label formula in phase 3. Trust,
    credibility, the label applier, and author history never change it.
15. The Write-the-gates session has the one-time bootstrap exception above.
    It may create import-safe scaffolding and `NotImplementedError` stubs only.
16. The two sources work together (human, 2026-09-24): GH Archive for which
    PRs changed and when, and the live APIs for what the PR is now. `Event`
    is the four shared fields. Everything else lives in `Reads`, using the
    REST and GraphQL sources fixed in phase 5.

## Open questions

None for this plan.

## Later plan updates

These do not block `queue-skeleton`. Update each item only when its owning
feature gets its own Plan or Grade session:

- `plans/queue-signals.md`: add manually linked issue assignees to `blocks`.
- `plans/queue-signals.md`: replace trust-times-credibility urgency with the
  direct configured-label formula.
- `plans/onboarding.md`: remove trust and people-group setup for the omitted
  `author_group` signal.
- `plans/replay-harness.md`: include stack authors and manually linked issue
  assignees in its blocking-source input contract.
- `plans/replay-harness.md` (decision 16):
  - take the PR number and event time from GH Archive; the event time is the
    archive envelope's `created_at`, not an `Event` field;
  - fill `Reads` by running phase 5's per-candidate reads on `(repo, number)`;
  - rebuild labels and review requests over time from the REST issue
    timeline (`labeled`, `unlabeled`, `review_requested` events);
  - human decision needed: size, title, body, and draft are final values
    only. Options: leave them out of replay, or use the final value and
    mark it as possibly from the future;
  - cost: about five requests per PR, so about 1,000 PRs per hour on one
    token (5,000 requests per hour).

## Plan review

- [accepted] high — AGENTS.md:154 — the required verification commands are literal placeholders, so Write the gates and Build cannot run §7 as written — the human must replace all seven placeholders with the commands proposed above before freezing this plan

## Build review

- [open] med — src/please_merge_my_pr/github/auth.py:20 — `gh auth token` is run with no host, so it gives the default-host (github.com) token; when `github.api_url` names another host and the env var is empty, that github.com token goes in `Authorization` to the configured host — ask `gh` for the token of the `github.api_url` host (`gh` is not installed on this machine, so read `gh auth token --help` for the host flag before writing the call)
- [open] med — tests/test_github.py:541 — `test_redirect_not_followed` and `test_api_url_must_be_https` (:580) were added for the build-review fixes (their docstrings cite it), but the only session recorded since is Build, whose writes are code only, and no run shows either one failing before the fix (AGENTS.md §7.1) — human confirms who wrote them, and a Write-the-gates session records each failing on the pre-fix code
- [open] low — src/please_merge_my_pr/cli.py:116 — `load_config` runs outside the `try`, so a bad config, now including an `http://` `github.api_url`, ends in a raw traceback, also under `--demo`, which never uses `api_url` (probe: `list --demo` with `api_url = "http://ghe.local/api/v3"` → `ValueError: github.api_url must use https` traceback, exit 1) — catch `ValueError` and `tomllib.TOMLDecodeError` from `load_config`, print one line to stderr, exit 1
- [open] low — src/please_merge_my_pr/config.py:63 — an explicit `--config PATH` that does not exist silently falls back to built-in defaults, so the user's `repos` and `risk_paths` are dropped with no message (probe: `list --demo --config typo.toml` → exit 0) — raise when `--config` names a missing file; keep the silent fallback only for the default path
- [open] low — src/please_merge_my_pr/cli.py:132 — `--demo` scores against the wall clock while demo request times are fixed (`demo/demo.json:9` is `2026-09-17T12:00:00Z`), so demo output changes every day, and from 2026-10-01 every demo age sits at the 14-day cap — store a fixed `now` in `demo.json` and use it under `--demo`
- [accepted] high — src/please_merge_my_pr/github/http.py:47 — `urlopen` follows 3xx redirects to any host and resends every header, `Authorization` included (stdlib `HTTPRedirectHandler.redirect_request`, Python 3.14.4), so one redirect sends the token to a URL outside `github.api_url` and breaks I17 — build the opener with a redirect handler that refuses redirects, so a 3xx comes back as a `Response` and maps to `invalid_response`
- [rejected] med — src/please_merge_my_pr/cli.py:334 — `watch` calls `poll_once` one time and exits, but phase 7 says it polls `/notifications` on an interval — loop `poll_once`, sleeping the stored `X-Poll-Interval`, with the sleep and clock injected so tests stay on fake time
- [rejected] med — src/please_merge_my_pr/ingest/poll.py:75 — `Last-Modified` and `ETag` are saved before the notifications are read; when `read_candidate` fails the item is skipped, the next poll gets `304`, and that review request never prints (probe: poll 1 → `[]` on a 502 PR read, poll 2 → `304`, `[]`) — save the new validators only after every notification is handled without a `GitHubError`
- [rejected] med — src/please_merge_my_pr/ingest/poll.py:58 — `transport.send` is not guarded, so a timeout or network error in `watch` ends in a raw `TimeoutError` traceback (probe confirmed) — catch `OSError` around the notifications request, print one line to stderr, exit 1
- [rejected] med — src/please_merge_my_pr/ingest/poll.py:84 — a `401` (or any non-200, non-304) from `/notifications` returns `[]`, so `watch` exits 0 with bad credentials; phase 5 says a 401 exits 1 — raise `GitHubError` on 401 and report other failures on stderr
- [rejected] med — src/please_merge_my_pr/cli.py:164 — live `why <pr>` or `show <pr>` on a PR whose REST read failed raises an uncaught `TypeError: candidate has no event` (probe: `why 7` with a 500 PR read) — print `could not check <repo>#<n>: <reason>` to stderr and exit 1
- [rejected] med — src/please_merge_my_pr/github/read.py:343 — a missing `asCodeOwner` becomes `False` and lets the PR in, and a missing requester at :368 becomes a bot and puts it out without the "could not check" count; I8 says a failed read → out and counted, and I9 lists `preview_missing`, which no code path returns — treat a missing or non-bool `asCodeOwner` and a missing requester `type` as `Unavailable("invalid_response")`
- [accepted] med — src/please_merge_my_pr/config.py:81 — `github.api_url` is taken from config without a scheme check, so `api_url = "http://..."` sends the token in the `Authorization` header unencrypted on every request — reject any `github.api_url` whose scheme is not `https` with `ValueError` naming `github.api_url`
- [rejected] med — src/please_merge_my_pr/cli.py:106 — bare `please-merge-my-pr --demo` exits 2 with a usage error, but the plan (line 18) says `uvx please-merge-my-pr --demo` works; handoff says "as chosen" with no recorded human decision — human picks: make no command mean `list`, or change the plan text to `list --demo`
- [rejected] low — src/please_merge_my_pr/cli.py:84 — `_stub` fires on any argv token equal to a stub name, so `--config open list --demo` prints the `queue-actions` stub line and exits 2 (probe confirmed) — check only the subcommand position, after global flags and their values
- [rejected] low — src/please_merge_my_pr/config.py:78 — a TOML string where a list is expected (`auth = "auth/**"`) is split into one-character globs, and `*` matches every top-level file, so every PR "touches auth" — reject non-list `risk_paths` groups and `lockfiles` with `ValueError` naming the key
- [rejected] low — src/please_merge_my_pr/github/read.py:90 — a GraphQL `RATE_LIMITED` error maps to `invalid_response`, and a 403 secondary rate limit (`retry-after` set, remaining not 0) maps to `forbidden`; the PR still stays out, but the reason is wrong — map both to `rate_limited`
- [rejected] low — src/please_merge_my_pr/ingest/poll.py:58 — only the first page of `/notifications` is read (GitHub pages it), so requests past page one are never seen — follow pages with `page=` like `_rest_pages`, built from `github.api_url`
- [rejected] low — src/please_merge_my_pr/cli.py:314 — `show` prints `summary: not enabled` as a fixed string and never calls a `Summarizer`, so the phase 6 slot is not wired — call `NullSummarizer().summarize` and print that line on `None`
- [rejected] low — src/please_merge_my_pr/ui/theme.py:9 — `color()` is never called, so phase 6's color tokens do nothing — use it in `screens.py` or delete it until `cli-design` lands
- [rejected] low — src/please_merge_my_pr/cli.py:310 — `show` prints the raw PR title, so terminal control and escape characters in a title reach the terminal — strip C0/C1 control characters before printing
- [rejected] low — mock/queue_mock.py — deleted in the working tree, but the plan (line 31) says screens copy it until `design/cli.md` exists, and the diff cannot show which session deleted it — human restores it or confirms the delete
- [rejected] low — tests/ — gates are untracked since base, so no diff can show that Build left them unchanged (AGENTS.md §11) — human compares against the Write-the-gates copy, or keeps a gate snapshot for future builds
