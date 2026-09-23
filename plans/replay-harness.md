<!-- role: Plan | model: claude-opus-5-5 | base: none (not a git repo) | date: 2026-09-22 -->
Status: draft
Phases: 4

# Replay harness

`PLAN.md` 2.3. Plan 4 of 4 in the no-LLM scaffold.
Requires `queue-skeleton` built (`Event.from_gh_archive`, the scorer) and
`queue-signals` built.

## Goal

Answer one question with a number: on a real repo's past month, would our
order have gotten blocking PRs reviewed sooner than the order they actually
got?

## Out of scope

- Summaries and LLM judges (`PLAN.md` 4.2–4.3)
- Adversarial suite (`PLAN.md` 3.2) — separate plan
- Any change to the scorer to improve the number (that is tuning, done by
  a human on the tuning repos only)

## Invariants

- **R1 — One ingestion path.** Replay builds every `Event` with
  `Event.from_gh_archive`. It has no parser of its own.
- **R2 — No future.** At simulated time `t`, a policy can read only data
  with timestamp ≤ `t`. Merge status, later comments, later labels, and
  later reviews are out of reach.
- **R3 — Deterministic.** Same slice, config, and seed → the same metrics,
  to the last digit.
- **R4 — Capacity from history.** Reviews per day = the repo's own count of
  first reviews per day in the slice. Same capacity for every policy.
- **R5 — Metric is fixed.** Mean and p90 time-to-first-review, over PRs that
  block ≥ 1 person, weighted by people blocked. Defined once, used by every
  policy.
- **R6 — Held-out stays held out.** The held-out repo is named in config.
  Any command marked tuning refuses to load it.

## Phases

### 1. Slice loader — `evals/replay/load.py`

- Reads a GH Archive month for one repo, filters its events, orders by time.
- Builds `Event`s through R1 only.

### 2. Time-gated view — `evals/replay/view.py`

- `View(t)` exposes only data with timestamp ≤ `t`. Reading anything later
  raises `LeakError`.

### 3. Simulator and policies — `evals/replay/sim.py`, `evals/replay/policies.py`

- Steps day by day. Each day, pops `capacity` PRs from the policy's order.
- Policies: `actual` (history as it happened), `fifo`, `recently_updated`,
  `ours` (the real scorer on `View(t)`).

### 4. Report — `evals/replay/report.py`, `make replay`

- Prints a table: policy × (mean, p90, n PRs). Writes JSON next to it.

## Gates to write

- `test_replay_uses_archive_ctor` — patch `from_gh_archive` to count calls;
  count equals events loaded (R1)
- `test_leakage` — slice with a sentinel future field; every policy runs
  without `LeakError` and never reads it (R2)
- `test_view_raises_on_future` — direct read past `t` raises (R2)
- `test_replay_deterministic` — run twice, byte-equal JSON (R3)
- `test_capacity_from_history` — fixture with known reviews/day → that
  capacity (R4)
- `test_metric_hand_computed` — 4-PR fixture, metric matches a hand-worked
  number (R5)
- `test_heldout_refused` — tuning command on the held-out repo exits nonzero
  (R6)

## Assumptions

- One slice is one repo, one calendar month.
- A day is the unit of simulated time.

## Open questions

1. GH Archive has no issue dependency data. In replay, `blocked_people` can
   use stacked PRs only. Accept that, or fetch dependencies from the API as
   of each date (hard, may be impossible)?
2. GH Archive payloads may lack fields the API has (changed files,
   additions/deletions). Check a real 2026 slice before phase 1. If missing,
   which signals are off in replay? (Same as skeleton question 5.)
3. Which 3 repos (2 tuning, 1 held out)?
