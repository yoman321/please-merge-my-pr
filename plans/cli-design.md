<!-- role: Plan | model: claude-opus-5-5 | base: none (not a git repo) | date: 2026-09-22 -->
Status: draft
Phases: 5

# CLI design

Step 2 of the build order, after `weights-research`. Design only: no product
code. All work happens in `mock/`.

## Goal

Find the look and feel ("vibe") of every screen before building it. Try a
few directions, pick one, and write it down as a spec the real `ui/` layer
copies.

Output: a finished `mock/` that shows every screen, and `design/cli.md`, the
spec.

## Out of scope

- Real GitHub data, real scoring, real config (mock data only)
- The `ui/` layer in `src/please_merge_my_pr/` (built in `queue-skeleton` phase 5 from this spec)

## Invariants

Every direction must meet these. A design that breaks one is rejected.

- **D1 — 80 columns.** Every screen fits in 80 columns with no wrap.
- **D2 — Both themes.** Readable on light and dark terminal backgrounds.
- **D3 — Plain when piped.** Not a terminal, or `NO_COLOR` set → no color
  codes at all, and the text still reads fine.
- **D4 — Color is never alone.** Every meaning shown by color is also shown
  by a word or symbol (for color-blind users and plain mode).
- **D5 — One-line queue.** Each PR in `list` is exactly one line.
- **D6 — Machine output exists.** `list` and `why` have a `--json` form, so
  scripts never parse the pretty output.
- **D7 — Numbers match the scorer.** Anything shown about weights or points
  comes from the chosen formula in `research/weights.md`.

## Screens

| Screen | What it must show |
|---|---|
| `list` | Top N, one line each: number, reason, score. Header with repo and counts. |
| `list --all` | Same, full list. |
| `why <n>` | Each signal: value, weight, points. How the total adds up. |
| `show <n>` | PR header, reason, summary slot, urgency prompt when flagged. |
| `watch` | New events streaming in, one line each. |
| `init` | Onboarding: GitHub login, repos, model (optional), risky paths, trust, weight presets with a live top-3 preview. |
| `merge <n>` | Tier 3 confirm prompt. |
| Empty and error states | No PRs, no config, bad token, rate limited, model off, `--demo` banner. |

## Phases

### 1. Mood board — `design/cli.md` § References

- Look at CLIs known for good terminal design (for example `gh`, `uv`,
  `lazygit`, `charm` tools, `rich` demos). Note what works: color use,
  spacing, symbols, density. Links and one line each.

### 2. Three directions — `mock/`

- Build the `list` and `why` screens three ways:
  - **Quiet:** mostly monochrome, one accent color, lots of space.
  - **Signal:** color-coded reasons (risk red, blocking amber, fresh green).
  - **Playful:** leans into the name. Friendly copy, a few symbols.
- `python3 mock/queue_mock.py --style quiet|signal|playful list`

### 3. Pick one — human

- Human runs the three and picks one, or mixes. Recorded in `design/cli.md`.

### 4. All screens in the chosen style — `mock/`

- Every screen in the table above, including `init` with the weight preview
  (uses presets from `research/weights.md`) and every empty/error state.

### 5. Spec — `design/cli.md`

- Color tokens (name → role → color), symbols, widths, spacing, copy tone.
- Captured output of every screen, in plain mode (paste) and color mode.
- Rich vs plain ANSI decision, with the reason.

## Done when

- Every screen in the table exists in `mock/` in the chosen style.
- Each screen checked against D1–D5, in a dark and a light terminal, and
  with `NO_COLOR=1`. Result written in `design/cli.md`.
- `design/cli.md` is complete enough to build `ui/` from without questions.

## Open questions

1. Rich or plain ANSI codes? Rich is a new dependency and needs your
   approval. Phase 2 could try both.
2. How playful should the copy be? The name is a joke; should the tool be?
3. Same role question as `weights-research`: AGENTS.md has no Design role.
