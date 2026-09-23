<!-- role: Plan | model: claude-opus-5-5 | base: none (not a git repo) | date: 2026-09-22 -->
Status: draft
Phases: 5

# Weights research

Step 1 of the build order. Research only: no product code.

## Goal

Decide how the score is computed before any scorer is built:
the formula shape, the curve for each signal, default weights, presets, and
how we will know the defaults are good.

Output is one decision document, `research/weights.md`, that a human signs
off. `queue-skeleton` phase 3 and the onboarding presets are built from it.

## Out of scope

- Writing `src/please_merge_my_pr/scoring.py` (that is `queue-skeleton`)
- Real replay numbers (that is `replay-harness`; this plan only says how
  replay will be used to tune)
- Any model: the score never uses one

## Invariants

What the research must respect. A proposal that breaks one is rejected.

- **W1 — Deterministic.** Same inputs → same score. No model, no randomness.
- **W2 — PR text never moves rank.** Title, body, comments carry no weight.
  The only author-influenced input is the urgency label, gated by trust.
- **W3 — Explainable.** Every point of score traces to a named signal, so
  `why` can show it and the reason line can name the top 3.
- **W4 — Bounded.** Score has a fixed range (0–100 today). No signal can
  exceed its share.
- **W5 — Tunable by users.** Whatever formula wins, a user can change it
  through plain numbers in config. No hidden constants outside config.
- **W6 — Held-out stays held out.** Tuning uses only the 2 tuning repos.
- **W7 — Weights come from the user.** Weights load only from the user's
  config, or from a team file read from the repo's default branch. Never from
  a PR's branch: a PR that edits the weights file must not rank itself.

## Questions to answer

1. **Formula shape.** Weighted sum (today)? Multiplicative? Tiers (for
   example: anything blocking people always beats anything that does not)?
   Weighted sum lets many small signals outvote one big one. That is the
   #388 vs #412 problem in `mock/queue_mock.py`.
2. **Cost of delay ÷ effort.** Scheduling theory says: to cut total weighted
   waiting, do the job with the highest cost-per-hour ÷ hours first
   (Smith's rule / WSPT; the cμ rule; WSJF in lean practice). Here that is
   roughly `people blocked × urgency ÷ review effort`. Does a ratio beat a
   sum for our metric?
3. **Curve per signal.** Linear, capped, log, or step? Age: is day 30 really
   3× worse than day 10? Diff size: is 50 lines vs 500 lines linear? Binary
   signals (risk path) can dominate smooth ones; how to balance?
4. **Normalization.** Signals have very different spreads (almost every PR
   is "old"; few touch `auth/`). Raw 0–1 is not equal footing.
5. **Starvation and fairness.** Low-score PRs, often from first-time
   contributors, may never reach the top. Need an aging floor?
6. **Gaming.** Which inputs can an author push? (Splitting PRs to look small,
   self-applied labels.) What each weight rewards, and how it can be abused.
7. **Stability.** How much does the top 3 jump when a PR gets one new
   commit? Is some stickiness needed?
8. **Presets.** What 3–4 starting points cover most teams (unblock people,
   hit deadlines, safety first, balanced)?
9. **Sensitivity.** If each default weight moves ±20%, how much does the
   top 3 change? Defaults should not sit on a cliff.
10. **Prior art.** What do CodeRabbit Triage, PR Flow, Gerrit's attention
    set, and the research on overdue PRs (for example Microsoft's "Nudge")
    use, and what did they learn?

## Phases

### 1. Prior art — `research/weights.md` § Prior art

- Read public docs and papers for question 10. One paragraph each: what they
  rank by, what they found. Link every source.

### 2. Candidate formulas — `research/weights.md` § Candidates

- Write 3 candidates, each fully specified: weighted sum (current), tiered,
  and cost-of-delay ÷ effort. Each with curves per signal (questions 1–4).

### 3. Paper test on fake data — `mock/weights_lab.py`

- Stdlib-only script. Runs every candidate on the mock PRs plus ~20 hand-made
  edge cases (huge urgent PR, tiny stale PR, first-timer PR, poisoned PR).
- Prints each candidate's ranking side by side, and the ±20% sensitivity
  table (question 9).

### 4. Risks — `research/weights.md` § Risks

- Answer questions 5–7 for each candidate.

### 5. Recommendation — `research/weights.md` § Decision

- One chosen formula, its curves, default weights, 3–4 presets, and the plan
  for tuning it with `replay-harness` on the 2 tuning repos.
- List what still needs a human call.

## Done when

- `research/weights.md` answers all 10 questions, with sources linked.
- `mock/weights_lab.py` runs and its output is pasted into the doc.
- The Decision section is complete enough to write `queue-skeleton` phase 3
  and the onboarding presets from it, with no further questions.

## Open questions

1. AGENTS.md has no Research role. Which role runs this plan: Build (writes
   only `research/` and `mock/`), or a new role you add to AGENTS.md?
2. Is the "blocks people first" story from the demo a product rule (tiers),
   or a default the user can change (weights)?
