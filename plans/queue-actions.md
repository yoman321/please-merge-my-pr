<!-- role: Plan | model: claude-opus-5-5 | base: none (not a git repo) | date: 2026-09-22 -->
Status: draft
Phases: 4

# Queue actions

`PLAN.md` 3.1. Step 6 of the build order (see `plans/queue-skeleton.md`).
Requires `queue-skeleton` built.

## Goal

Let the user act on a PR from the queue, with the cost of a mistake set by
tier. Nothing outbound happens without the user asking for it.

| Tier | Kind | Rule | Actions |
|---|---|---|---|
| 1 | local, reversible | free | hide, snooze, open in browser |
| 2 | visible, undoable | needs a stored approval rule | add/remove label |
| 3 | irreversible or outbound | asks every time | merge, comment, approve review |

## Out of scope

- Any model call, and any action proposed by a model
- Bulk actions across PRs

## Invariants

- **A1 — Every action has a tier.** Registering an action without a tier
  raises at import time. No default tier.
- **A2 — Tier 3 always asks.** Every tier 3 action shows a `[y/N]` prompt
  naming the action, PR, and target. Default is no. No flag, config, or
  stored rule skips it. Non-terminal → refused, nothing sent.
- **A3 — Tier 2 needs a rule.** A tier 2 action runs only if a stored rule
  matches (action, repo, label). No match → prompt to create the rule, or
  refuse.
- **A4 — Destinations come from config.** Every request's host and path come
  from config plus the PR number. No URL, host, or login from PR data (title,
  body, comments, labels, branch names) ever becomes a request target or
  recipient.
- **A5 — Only the user starts actions.** An action runs only from a CLI
  command the user typed. No code path turns data into an action.
- **A6 — Dry run sends nothing.** `--dry-run` prints the exact request and
  sends zero bytes.
- **A7 — Rules are metadata.** The rule table holds action, repo, label,
  created_at. No PR content.

## Phases

### 1. Tier registry — `src/please_merge_my_pr/actions.py`

- `@action(tier=...)` decorator, registry, dispatcher that enforces A1–A3.

### 2. GitHub write client — `src/please_merge_my_pr/github/write.py`

- `add_label`, `remove_label`, `merge(method)`, `comment(text)`,
  `approve`. Base URL from config only (A4). Honors `--dry-run` (A6).

### 3. Rule store — `src/please_merge_my_pr/rules.py`

- SQLite `rules(action, repo, label, created_at)`. `please-merge-my-pr rules` lists them,
  `please-merge-my-pr rules rm <id>` deletes one.

### 4. CLI — `src/please_merge_my_pr/cli.py`

- `please-merge-my-pr label <n> <label>`, `please-merge-my-pr merge <n> [--squash|--rebase]`,
  `please-merge-my-pr comment <n>` (opens `$EDITOR`), `please-merge-my-pr approve <n>`,
  `please-merge-my-pr hide <n>`, `please-merge-my-pr snooze <n> <days>`, `please-merge-my-pr open <n>`.
- Tier 3 prompt layout follows `mock/queue_mock.py merge`.

## Gates to write

- `test_untiered_action_fails` (A1)
- `test_tier3_prompts_every_time` — run merge twice, both prompt (A2)
- `test_tier3_non_tty_refused` — zero requests sent (A2)
- `test_tier3_default_no` — empty answer → nothing sent (A2)
- `test_tier2_needs_rule` — no rule → no request; add rule → request (A3)
- `test_pr_url_never_target` — body, title, comment, and branch name hold
  `https://evil.example/x`; run every action; recorded request hosts are
  only the config host (A4)
- `test_dry_run_sends_nothing` — every action with `--dry-run`, network
  patched to raise (A6)
- `test_rules_no_content` — canary absent from the rules table (A7)

## Assumptions

- `hide` and `snooze` are local only, stored as PR number + until-date.
- Merge method default is squash.

## Open questions

1. Keep `comment` at all? `PLAN.md` cut list puts it 3rd to cut.
2. Should `approve` exist, or is merge enough for the demo?
