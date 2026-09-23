<!-- role: Plan | model: claude-opus-5-5 | base: none (not a git repo) | date: 2026-09-22 -->
Status: draft
Phases: 4

# Queue signals

`PLAN.md` 2.1 and 3.4. Step 5 of the build order (see `plans/queue-skeleton.md`).
Requires `queue-skeleton` built: `Event`, the signal interface, the scorer.

## Goal

The three signals that need more than the PR itself: who is blocked, when it
is due, and whether "urgent" can be trusted. Plus the one-keystroke loop that
teaches the tool whose "urgent" means something.

## Out of scope

- Actions of any kind → `plans/queue-actions.md`
- Replay → `plans/replay-harness.md`
- Any model call

## Invariants

- **S1 — Bounded.** `blocked_people`, `due_soon`, `urgency` each return a
  value in [0, 1] for every input, including missing milestones, deleted
  users, and zero links.
- **S2 — Structure only for blocking.** `blocked_people` counts only
  links GitHub stores as structure: issue dependencies (`blocked by`), and open
  PRs whose base branch is this PR's head branch. Text the author typed does
  not count. The same person blocked twice counts once.
- **S3 — Urgency is gated by trust.** `urgency = trust(applier) ×
  credibility(author)` when the urgency label is present, else 0. The
  applier comes from the `labeled` event actor in the timeline. Unknown
  applier → the lowest trust tier in config.
- **S4 — Credibility formula.** `credibility = (confirmed + 1) / (flagged + 2)`,
  per author, exactly. A new author is 0.5.
- **S5 — Only the user moves credibility.** Counts change only on a `y` or
  `n` keystroke in `please-merge-my-pr show`. `s` (skip), non-terminal runs, and every
  other path change nothing.
- **S6 — No content at rest.** The credibility table holds author login,
  `flagged`, `confirmed`, timestamps. Nothing else. (Same rule as I6.)
- **S7 — Cache is bounded.** A cached `blocked_people` value is never used
  after its TTL. TTL lives in config.
- **S8 — PR text still never ranks.** Changing title, body, or comments
  changes no signal value. Urgency reads the label and its timeline event,
  never the title (so "URGENT:" in a title counts for nothing).

## Phases

### 1. `due_soon` — `src/please_merge_my_pr/signals/due_soon.py`

- Reads `milestone.due_on`. No milestone → `(0, "")`. Past due → 1.
- Else `1 - min(1, days_left / horizon_days)`. `horizon_days` in config.
- Fragment: `due in 2d` or `overdue 3d`.

### 2. `blocked_people` — `src/please_merge_my_pr/signals/blocked_people.py`, `src/please_merge_my_pr/github/graphql.py`

- One GraphQL query per PR for issue dependencies and stacked PRs.
- Distinct people = assignees + authors of the blocked items, minus the PR
  author.
- `value = min(1, count / cap)`. Fragment: `blocks 2`.
- TTL cache in SQLite, keyed by repo + PR number. Stores the count only.

### 3. Credibility store — `src/please_merge_my_pr/credibility.py`

- SQLite table `credibility(author, flagged, confirmed, updated_at)`.
- `get(author) -> float`, `record(author, confirmed: bool)`.

### 4. `urgency` signal and the prompt — `src/please_merge_my_pr/signals/urgency.py`, `src/please_merge_my_pr/cli.py`

- Label names and trust tiers (`lead`, `teammate`, `self`) come from config.
- Applier found through the timeline API.
- `please-merge-my-pr show <n>` on an urgent PR asks `[y] yes [n] not really [s] skip`,
  then calls `record`. Only in a real terminal.
- Fragment when value ≥ config threshold: `urgent (lead-set)`.

## Gates to write

- `test_signal_bounds_extra` — edge table, all three values in [0, 1] (S1)
- `test_blocked_ignores_text` — "blocks #12, #13" in the body, no structural
  links → count 0 (S2)
- `test_blocked_distinct` — one person on two blocked items → count 1 (S2)
- `test_urgency_self_vs_lead` — same PR, label by `self` vs `lead` → values
  equal `trust_self × c` and `trust_lead × c` (S3)
- `test_urgency_unknown_applier` — no timeline actor → lowest trust (S3)
- `test_credibility_formula` — (0,0)→0.5, (2 flagged, 2 confirmed)→0.75,
  (5, 0)→1/7 (S4)
- `test_skip_changes_nothing` — `s`, non-tty, and `why`/`list` leave counts
  unchanged (S5)
- `test_db_has_no_content_signals` — canary title/body absent from every
  table after a full run (S6)
- `test_cache_ttl` — fake clock past TTL → fresh fetch (S7)
- `test_urgent_title_ignored` — "URGENT:" in title, no label → urgency 0 (S8)

## Assumptions

- Trust tiers are set per login in config. No org-role lookup.
- `blocked_people` cap is 3; `due_soon` horizon is 14 days.
- Weights, caps, and horizons come from `research/weights.md`. The numbers
  above are placeholders until then.

## Open questions

1. Should "blocks 2 people" outrank "due in 2d + lead says urgent"? In the
   mock, #388 (due + urgent) beats #412 (blocks 2 + auth). The demo story
   wants #412 on top. Moved to `weights-research` (questions 1 and 2 there).
2. GitHub's "closing issues" links usually come from words in the PR body
   ("Fixes #12"). That is author text. Count it or not? S2 says no as written.
3. Are GitHub issue dependencies available on the demo repos' plan? If not,
   stacked PRs are the only blocking source.
