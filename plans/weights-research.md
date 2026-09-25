<!-- role: Grade the plan | model: gpt-5 | base: 569eee1461ed51a4b4d639c61ee7ed1ae77bee3c | date: 2026-09-24 -->
Status: reviewed
Phases: 5

# Weights research

Step 1 of the build order. Research only: no product code.

## Current state

The human stopped the research session on 2026-09-23 after making the
direction calls below. The research ran in chat, not through phases 1–5.
`research/weights.md` was not written, so this plan's done conditions remain
unmet.

Decided in that session, each marked below as changed or kept by the human
on 2026-09-23:

- Only people other than the PR's author count as waiting (B4, B9).
- No bot group and no bot rule (People groups, B5, B6).
- Waiting is time since the current review request only. Base branch drift
  is dropped (A).
- A failed check scores 0, and the PR ranks lower (W10).
- Starvation is accepted. A daily reminder to the lead belongs to a later
  plan (17).
- Misuse of an urgency label is for the lead to handle, not the formula (B7).
- Kept after the review-cost evidence: bigger PRs rank higher (B1), the
  weighted sum (B11, formula 13), and overlapping signals.

Still not done in this plan:

- This plan has no integrated defaults, curves, caps, horizons, or rounding
  rule. On 2026-09-24, the human picked provisional weights, two caps, and
  round-half-up in `plans/queue-skeleton.md`. That later choice also dropped
  the `author_group` and standalone `lockfile` signals for now.
- No source table, worked examples, or sensitivity table.
- The plan body still describes the dropped signals and does not yet make
  `plans/queue-skeleton.md` or another file the one source of truth.
- "Done when" is not met.
- Open questions 5–9 remain unresolved unless a later human decision below
  says otherwise.

## Goal

Decide how the score is computed before any scorer is built: the exact
formula, one curve and missing-data rule per signal, provisional default
weights, presets, and written examples that show how those choices behave.

The defaults are provisional until `replay-harness` tests them on the two
tuning repos. This plan cannot show that they improve real review time.

Output is one decision document, `research/weights.md`, that a human signs
off. `queue-skeleton` phase 3 and the onboarding presets are built from it.

## Out of scope

- Writing `src/please_merge_my_pr/scoring.py` (that is `queue-skeleton`)
- Real replay numbers (that is `replay-harness`; this plan only defines the
  later tuning method)
- Building the people-group command (that is `onboarding`; this plan only
  says what it must do)
- Writing scripts, fixtures, gates, or tests. Those start after the first
  prototype exists.
- Any model: the score never uses one

## Invariants

What the research must respect. A proposal that breaks one is rejected.

- **W1 — Deterministic.** Same complete inputs produce the same score. No
  model, clock read, network call, or randomness is inside the scorer.
- **W2 — PR prose never moves rank.** Title, body, and comments carry no
  weight. Structured metadata and changed paths can move rank, even when an
  author can affect them. The urgency label is the only explicit priority
  claim from a PR participant. Every configured urgency label counts,
  whoever added it. Decided by the human on 2026-09-23.
- **W3 — Explainable.** Every point traces to a named signal. `why` can show
  the complete arithmetic, and the reason line can name the top three
  contributions.
- **W4 — Bounded.** The displayed score is in 0–100. Each raw signal is in
  0–1. No signal can contribute more than its normalized weight share.
- **W5 — Tunable by users.** Weights, caps, horizons, path groups, urgency
  label names, and author-group values are plain numbers or names in config.
  Formula mechanics and numeric precision are fixed in code and documented.
- **W6 — Held-out stays held out.** Tuning uses only the two tuning repos.
  The held-out repo is used once for the final report.
- **W7 — Safe config source.** Weights come from the user's config. If the
  later onboarding decision adds a team file, it is read only from the
  repository's default branch. A PR branch can never change its own score.
- **W8 — Manual by-name review requests only.** A PR enters the queue only
  while the user has a current by-name `ReviewRequest`, its GraphQL
  `asCodeOwner` value is false, and the matching request event came from a
  person. Team requests, automatic code-owner requests, and all other
  notification reasons do not count. Draft PRs stay out. This is a gate,
  not a weight. Decided by the human on 2026-09-23.
- **W9 — People groups come from the user.** Every person is a teammate
  unless the user moved them to another group with a command. Groups live
  in the user's config. No GitHub data changes a person's group. Decided by
  the human on 2026-09-23.
- **W10 — A failed check scores 0.** A missing relationship and a failed,
  forbidden, rate-limited, or preview-only API read are different inputs,
  but both give that signal 0 points. The PR is still graded out of the
  full `sum(w_i)`, so it ranks lower. Making sure an urgent PR reads as
  urgent is on its author. Whether `why` shows "check failed" is open
  question 7. Changed by the human on 2026-09-23.
- **W11 — Only named structured sources rank.** Text parsing for “depends
  on,” closing keywords, urgency words, or similar prose is forbidden. If
  phase 1 cannot prove a stable structured source for a signal, the Decision
  section drops that signal and records why.
- **W12 — Ties are real.** Two or more PRs with the same displayed score
  share one rank. The UI may use a fixed order inside that tied group for
  stable output, but it must not claim that one tied PR outranks another.
  Decided by the human on 2026-09-23.

## Facts and assumptions

- **A1 — Confirmed in GitHub docs.** GraphQL `ReviewRequest.asCodeOwner`
  says whether the current request was created for a code owner. The REST
  requested-reviewers response does not expose this bit.
- **A2 — Confirmed in GitHub docs.** Once a requested reviewer submits a
  review, GitHub no longer considers that person requested. The person is
  requested again only through a later request.
- **A3 — Confirmed by the human on 2026-09-23.** No urgency label means
  medium. With two or more configured urgency labels, the most urgent wins.
- **A4 — Partly confirmed in docs.** REST timeline events expose
  `review_requested.created_at`, `requested_reviewer`, and
  `review_requester`. The docs do not prove every remove, review, and
  re-request sequence. Research records the intended match rule and risk.
  Live behavior is checked after the first prototype exists.
- **A5 — Confirmed in GitHub docs, but preview-only.** GitHub's Stacks API
  exposes stack order. It is in public preview, so phase 1 must define a
  no-stack-data fallback.
- **A6 — Confirmed in GitHub GraphQL docs.**
  `closingIssuesReferences(userLinkedOnly: true)` returns only manually
  linked issues. This is the allowed linked-issue source under W2.

## Research checked during plan review

- GitHub's [GraphQL pull request reference](https://docs.github.com/en/graphql/reference/pulls)
  documents `ReviewRequest.asCodeOwner` and current review requests.
- GitHub's [REST review-request reference](https://docs.github.com/en/rest/pulls/review-requests)
  says a submitted review removes the person from requested reviewers.
- GitHub's [pull-request review reference](https://docs.github.com/en/pull-requests/reference/pull-request-reviews)
  says team review assignment can request named team members and remove the
  team. A current named request alone therefore does not prove a direct
  manual request.
- GitHub's [issue event reference](https://docs.github.com/en/rest/using-the-rest-api/issue-event-types)
  documents request actors, requesters, reviewers, and timestamps.
- GitHub's [stack API reference](https://docs.github.com/en/pull-requests/reference/stacked-pull-requests-apis-and-webhooks)
  marks stack data as public preview.
- GitHub's [linked-issue docs](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)
  show that ordinary links can come from PR text. Only manual links are safe
  for W2.
- [CodeRabbit Triage](https://docs.coderabbit.ai/triage/prioritization)
  separates priority from next action. Its base score uses validated issue
  severity, linked external priority, and downstream dependencies. CI and
  conflicts affect action, not base priority.
- [PR Flow](https://prflow.app/pull-request-review-queue) classifies by who
  owes the next move, then uses review state, unresolved threads, and the age
  of that state.
- [Gerrit's attention set](https://gerrit-review.googlesource.com/Documentation/user-attention-set.html)
  removes a reviewer after a reply and does not treat a new patch set alone
  as a turn change.
- Microsoft's [Nudge paper](https://arxiv.org/abs/2011.12468) used predicted
  completion time, recent activity, and actor identification. Its randomized
  trial reduced mean resolution time by about 60 percent for the studied
  overdue PRs. This is evidence for later replay, not proof of these weights.
- A [controlled change-decomposition study](https://pmc.ncbi.nlm.nih.gov/articles/PMC7924728/)
  compares tangled changes with split changes. It does not compare large
  changes with small ones, so it supplies no evidence for B1.

## Research checked in chat on 2026-09-23

- Correction to the change-decomposition entry above: di Biase et al.
  (2019) compare tangled with split changes, not large with small. They
  found no difference in review time or defects found. Split changes had
  fewer false positives.
- [Smith's rule](https://statmath.wu.ac.at/~boehm/book/chapter2.pdf): with
  one reviewer, ordering by value ÷ effort gives the least total weighted
  waiting. B1 orders by effort the other way. Example: reviews of 120, 30,
  and 10 minutes. Biggest first gives a mean wait of 143 minutes. Smallest
  first gives 70.
- [Google's code review study](https://sback.it/publications/icse2018seip.pdf):
  median first feedback is under 1 hour for small changes and about 5 hours
  for very large ones.
- [SmartBear's Cisco study](https://static1.smartbear.co/support/media/resources/cc/book/code-review-cisco-case-study.pdf):
  defect finding drops past 200–400 lines per review.
- GitHub [issue dependencies](https://github.blog/changelog/2025-08-21-dependencies-on-issues/)
  are generally available, with GraphQL `blockedBy` and `blocking` on
  `Issue`. They name people who wait on an issue (open question 8).
- Dependabot's `reviewers` option [was replaced by code owners](https://github.blog/changelog/2025-08-08-dependabot-reviewers-configuration-option-is-replaced-by-code-owners/).
  Its review requests now come from code owners, which W8 keeps out.
- Applying labels and requesting reviews both need the Triage
  [repository role](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization)
  or higher. Outside contributors cannot label their own PRs. Teammates can.
- The human read these and kept B1, B7, and B11.

## Setup, for now

Decided by the human on 2026-09-23. Setup is only two manual things:

1. **Which PRs.** A person adds the user by name as a reviewer (W8).
   Nothing to configure.
2. **Which people.** Everyone is a teammate, the baseline. The user moves a
   person to another group only if needed (People groups).

No people data comes from GitHub. The tool never asks and never guesses.

## People groups

Decided by the human on 2026-09-23. Kept simple on purpose.

- Three groups, no others:
  - teammate — the default and the baseline
  - trusted maintainer
  - outside contributor
- No bot group. A bot's PRs score like a teammate's. Changed by the human
  on 2026-09-23.
- Everyone starts as a teammate. The tool never asks and never guesses.
- A command moves a person to another group, or back. The command's name
  and shape belong to `onboarding` and `cli-design` (for example
  `please-merge-my-pr people set <login> <group>`).
- The author signal has one configured 0–1 value per group. Teammate is the
  baseline. Presets may change all three values.

This removes a call from part B: who is trusted. It is now a user setting,
not a product rule.

## A. Signals and sources

**Gate** decides whether a PR is in the queue. **Weight** produces a 0–1
priority value. Higher always means “review sooner.” Phase 1 may drop a
weight that lacks a stable structured source. It may not add a signal.

| Group | Signal | Kind | Allowed source |
|---|---|---|---|
| My turn | Current manual by-name request (W8) | gate | GraphQL current `ReviewRequest` plus REST timeline request event |
| My turn | Draft PR | gate | GitHub PR `draft` field; draft means excluded |
| My turn | CI red or merge conflicts | weight, lowers score (B8) | GitHub checks and mergeability fields |
| Who waits | Open PRs above this PR in a stack, by people other than its author | weight | GitHub Stacks API; branch base/head fallback; never prose |
| Who waits | Manually linked issue kind: bug, incident, customer report | weight | GraphQL `closingIssuesReferences(userLinkedOnly: true)` plus configured issue labels |
| Who waits | Distinct people other than the PR's author assigned to manually linked issues | weight | Same manual links plus issue assignees |
| Who waits | Milestone due date | weight | GitHub milestone fields |
| Risk | Touches auth, payments, secrets, migrations, public API, CI, deploy | weight | Changed paths plus configured path groups |
| Risk | Changes lockfiles | weight | Changed paths plus configured lockfile patterns |
| Effort | Additions, deletions, and changed files | weight | GitHub diff counts; configured generated/lockfile discounts |
| Delay | Time since the current eligible review request | weight | Matched request event from A4 |
| Author | Group: teammate, trusted, outside | weight | User config (W9) |
| Urgency | Configured low, medium, high, urgent label | weight, heaviest | GitHub labels plus user config |

Changed by the human on 2026-09-23: base branch drift is dropped, so
waiting is time only. The bot group is gone. Only people other than the
PR's author count as waiting.

“Modules” is not a raw input. Phase 2 may add a module count only if it gives
“module” one deterministic, language-independent definition. Otherwise it
uses lines and files only.

How teams open PRs shapes the age signal:

- **Open when done.** The PR is ready from the start.
- **Open early as a draft.** “Opened at” says nothing about waiting.
- **Small stacked PRs.** One ticket becomes many PRs. The bottom can block
  the rest.

Under W8, the current eligible review request is the “ready now” signal in
all three styles. “New commits since my last review” is not a separate gate.
GitHub clears the request after review. A later by-name re-request starts a
new queue turn.

## B. Human calls

Product choices. All answered by the human on 2026-09-23. Each is a
direction or rule, not a number. The research sets the numbers.

1. **Big PR:** **bigger PRs rank higher.** This is the reverse of
   `diff_size` in `queue-skeleton` phase 2, where smaller PRs score more.
   That plan needs the change. Kept by the human on 2026-09-23 after the
   review-cost evidence in "Research checked in chat."
2. **Risky path:** **up.** A risky change is seen early.
3. **Blocks people:** **a weight, not a rule.** The user can turn it up or
   down. A blocking PR can be outranked.
4. **“Blocked” means:** **PRs stacked above it, and distinct people assigned
   to its manually linked issues.** Text references do not count. Only
   people other than the PR's author count: a person must be waiting on
   someone else. Changed by the human on 2026-09-23.
5. **Author groups vs. the teammate baseline:** **trusted a little down,
   outside up.** The bot group was removed by the human on 2026-09-23.
6. **Bot PRs:** **no rule, for now.** A bot's PRs score like a teammate's.
   Changed by the human on 2026-09-23.
7. **Urgency labels:** **four levels: low, medium, high, urgent,** as
   ordinary GitHub labels on the PR. Config maps label names to levels.
   Urgent has a priority value of 1. Low has the smallest value. Urgency is
   the heaviest single signal; its exact weight comes from the research.
   Every label counts, whoever added it (W2). No label uses A3. Misuse of
   the label is a people problem: the lead talks to that person or lowers
   their ranking (open question 5). Decided by the human on 2026-09-23.
8. **CI red or conflicts:** **lower the score, never hide.** The user must
   still see the PR.
9. **Stacks:** **boost the bottom PR** by how many open PRs sit above it.
   Under B4, only PRs by people other than its author count, so a stack by
   one author adds 0 (open question 6).
10. **Age clock:** **starts at the current eligible review request.** If the
    user is removed and added again, the clock restarts.
11. **Formula:** **a weighted sum.** The W8 queue is small, about 2–8 PRs.
    Kept by the human on 2026-09-23. A pile of small signals can outrank
    one big one, and signals can overlap (for example size and risky
    paths). Both are accepted.
12. **Tests:** **not part of the score.** Some teams write tests and some do
    not, so “tests changed with the code” is not a signal.

## C. How signals combine

Research proposes the curves, values, and weights. The human approves.

13. **Exact formula.** For retained signal `i`, phase 2 defines priority
    value `x_i` in `[0, 1]` and nonnegative weight `w_i`. At least one weight
    must be positive.

    `score = 100 × sum(w_i × x_i) / sum(w_i)`

    The same formula in the human's deduction frame is:

    `score = 100 − 100 × sum(w_i × (1 − x_i)) / sum(w_i)`

    This keeps 100 as the most urgent case. It also prevents weight totals
    above 100 from flattening many PRs at zero. Phase 2 must set one rounding
    rule and use it for the score, `why`, and sensitivity output.
14. **Curve per signal.** Linear, capped, log, or step? Age: is day 30
    really three times day 10? Diff size: is 50 versus 500 lines linear?
    Binary signals can dominate smooth ones.
15. **Normalization.** Each signal's raw unit, cap, curve, and 0–1 meaning
    must be explicit. A cap or horizon is config, not an unnamed constant.
16. **Presets.** Propose three or four starting points: unblock people,
    hit deadlines, safety first, and balanced. Each preset sets every signal
    weight and all three author-group values.

For each signal, phase 2 must also specify:

- true absence, such as no milestone;
- unavailable data, such as a 403, timeout, or missing preview field
  (0 points under W10);
- whether the signal is binary, ordinal, or continuous;
- exact config keys and validation bounds;
- the fixed explanation template;
- how the signal's displayed contribution adds back to the displayed score.

## D. Checks on the result

17. **Starvation.** In a fixed queue, show whether every nonzero-age PR can
    eventually reach the top. If not, state the exact class that can starve
    and propose an aging floor for human approval.
    Decided by the human on 2026-09-23: starvation is accepted, with no
    aging floor. Instead, the lead gets a daily reminder that PRs are open.
    That reminder belongs to a later plan (open question 9).
18. **Gaming.** List every input a PR author can affect, including size,
    paths, labels, links, assignees, and timing. State what each weight
    rewards and the cheapest way to abuse it.
19. **Stability.** Measure top-one changes, top-three membership changes,
    and top-three order changes when one new commit or one small metadata
    change lands. Do not add hidden stickiness.
20. **Sensitivity.** Move one default weight at a time by minus and plus 20
    percent. Record score deltas, top-rank-group changes, top-three score-band
    overlap, and score-band order changes. Ties remain ties. The human sees
    the full table; no result is called “stable” without a stated threshold.
21. **Prior art.** Compare CodeRabbit Triage, PR Flow, Gerrit's attention
    set, Nudge, and the large-change research cited above. Separate product
    documentation from experimental evidence. Do not claim a product's
    private formula or outcome.
22. **GitHub behavior.** Check A1–A6 against current GitHub REST and GraphQL
    docs. Record the API version, fields, permissions, preview status, and
    every behavior the docs do not prove. Defer live checks to the prototype.

## Phases

### 1. Source audit and prior art — `research/weights.md` § Sources

- Answer 21 and 22. Use primary docs and papers.
- Make a source table with: signal, endpoint or field, permission, preview
  status, absent shape, error shape, and keep/drop decision.
- For current manual requests, code-owner requests, team requests, submitted
  reviews, re-requests, manual issue links, and stacks, record what the docs
  prove and what must wait for prototype testing.
- Record facts and limits. Marketing pages are not outcome evidence.

### 2. Formula — `research/weights.md` § Formula

- Define every retained signal from raw input through 0–1 value.
- Define true-absence and unavailable-data behavior for every signal.
- Apply formula 13 and one exact rounding rule.
- Give every config key, allowed range, default, and explanation template.
- Show one hand-worked PR whose contributions reproduce its score.

### 3. Written examples — `research/weights.md` § Worked examples

- Make one table of at least ten fake PRs. Include a huge urgent PR, tiny new
  urgent hotfix, tiny stale PR, outside-contributor PR, bot PR, stack bottom,
  manual linked issue, text-only linked issue, missing-data PR, and two PRs
  with the same score.
- Show every normalized signal, weight, contribution, total score, and shared
  rank. Work one row by hand so a reader can check the arithmetic.
- Show each B1–B10 direction with a before-and-after pair where only that
  input changes.
- Show the default and preset results, starvation cases, and the sensitivity
  measures from 20. Remove presets that do not change any worked result.
- This phase writes prose and tables only. It writes no script, fixture,
  assertion, gate, or test.

### 4. Risks — `research/weights.md` § Risks

- Answer 17–20 for the chosen formula and provisional defaults.
- Cover API failure, rate limits, preview removal, gaming, saturation,
  ties, correlated signals, and the review-cost tradeoff from B1.
- State which risks are accepted, which need a human call, and which move a
  signal out of the formula.

### 5. Recommendation — `research/weights.md` § Decision

- Give the retained signals, formula, curves, provisional default weights,
  author-group values, and three or four distinct presets.
- Include a machine-copyable table of config keys, defaults, bounds,
  missing-data rules, and fixed explanation templates.
- Define the later replay objective and report: metrics, two tuning repos,
  one held-out repo, tuning procedure, and what result would cause a default
  to change. Do not report replay numbers in this phase.
- List every required follow-up edit to `queue-skeleton`, `onboarding`, and
  `queue-signals`. Those edits need their own Plan or Grade sessions.
- List remaining human calls. Record the human's sign-off or rejection.

## Done when

- Every part B call remains recorded.
- `research/weights.md` answers 13–22 with primary sources linked.
- Every retained signal has a proven structured source, raw unit, curve,
  normalization, config key, absent rule, unavailable rule, and template.
- The Worked examples section contains complete arithmetic for at least ten
  fake PRs, every B1–B10 direction, one tie, and the sensitivity table.
- Default weights are labeled provisional pending replay.
- The Decision section is complete enough to revise `queue-skeleton` phase
  3 and onboarding presets without guessing.
- The human's sign-off or rejection is recorded.

## Open questions

1. **How research runs.** Decided by the human on 2026-09-23. The human
   prompts a separate agent directly. It writes only `research/weights.md`.
   It writes no code, fixture, gate, or test. Testing begins after the first
   prototype exists.
2. `queue-skeleton` needs its own Plan session. It must add the W8 fields and
   filter, flip `diff_size`, start age at the request, and replace its event
   source assumptions with the source audit. It must also replace total-order
   tie breaking with W12's shared-rank display rule.
3. `onboarding` needs its own Plan session. It must add the three people
   groups, teammate default, move command, and final W7 config-source choice.
4. `queue-signals` needs its own Plan session. Its trust and credibility
   urgency formula conflicts with B7, and its linked-issue rule must use only
   manually linked issues.
5. **Lowering one person.** B7 lets the lead lower the ranking of a person
   who misuses the urgency label. How: a new people group below teammate, a
   per-person 0–1 value, or no change in the tool? Human to decide.
6. **Own stacks.** Under B4, a stack by one author adds 0 to its bottom PR.
   This changes B9. Human to confirm.
7. **Failed checks shown.** When W10 gives a signal 0, should `why` say
   "check failed"? Yes keeps a failure visible. Human to decide.
8. **Waiting source.** Assignees of a manually linked issue are usually the
   people doing the work, not people waiting. GitHub issue dependencies
   (`blocking`) name people who wait. `queue-signals` must pick the source.
9. **Daily reminder to the lead.** Who is the lead, and how is the reminder
   sent? A reminder sent to another person is an outbound action. A later
   plan decides.

## Plan review

- [open] high — plans/weights-research.md:52 — every phase writes `research/weights.md`, but AGENTS.md gives no role permission to write that file, so no allowed session can finish this plan — move the research result into this plan or add a human-defined research role before freezing
- [open] high — plans/weights-research.md:32 — the human later dropped `author_group` and standalone `lockfile` and picked seven weights in `queue-skeleton`, but this plan still requires both dropped signals and contains none of those defaults — revise the retained-signal list and make one file the source of truth
- [open] high — plans/weights-research.md:90 — `ReviewRequest.asCodeOwner == false` plus a user timeline event does not prove a manual by-name request because GitHub team review assignment can replace a team request with requests for named members — name a field that distinguishes this case or change W8's team-request rule
- [open] high — plans/weights-research.md:465 — the plan says linked-issue assignees count as waiting, then says they usually do not represent waiters; this leaves the `blocks` signal without one meaning — the human must choose issue assignees, issue dependencies, or no linked-issue people
- [open] high — plans/queue-signals.md:31 — its trust-times-credibility urgency rule contradicts B7, where every configured urgency label counts directly — revise that plan before freezing it
- [open] med — plans/weights-research.md:100 — W10 makes failed reads and true absence score the same but leaves failure display undecided, so `why` cannot meet W3's complete trace without a rule — decide that `why` shows unavailable status or explicitly accept hiding the failure
- [open] med — plans/weights-research.md:350 — the daily reminder is the only stated answer to accepted starvation, but no owner plan, recipient source, or outbound approval rule is named — assign it to a later plan with those rules or remove it from this plan's decision
- [open] med — plans/onboarding.md:37 — it says weights load only from user config while W7 still permits a later default-branch team file — the human must choose user-only or define team-file precedence before freezing onboarding
