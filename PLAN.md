# please-merge-my-pr — Claude Code Prompt Pack

This file is a high-level roadmap only. It is not an actionable spec and does
not create findings. The feature files under `plans/` hold the requirements,
invariants, gates, and review findings. If this roadmap differs from a feature
plan, the feature plan wins.

Nebius x NVIDIA Global AI Hackathon
Submission deadline: **Thu Oct 30, 2026, 10:00 PDT**
Personal deadline: **Tue Oct 28** (buffer for Devpost/YouTube problems)

How to use this file: run Prompt 0 once, review what it writes, then work top to
bottom. One prompt per session. Each ends in something runnable.

Detailed specs live in `plans/`. Build order:
1. `weights-research` — formula and signal directions (no code). Closed
   2026-09-23; seven default weights set 2026-09-24
2. `cli-design` — decide the look of every screen, in `mock/` (no code)
3. `queue-skeleton` — data in, rank, print
4. `onboarding` — `init`, config file, weight presets with live preview
5. `queue-signals` — blocks, due_soon, urgency label
6. `queue-actions` — action tiers, label, merge, comment
7. `replay-harness` — GH Archive replay, policies, leakage guard
8. `summaries` — the only model code

Background research: `research/landscape.md`. Current state: `handoff.md`.

Current ranking decisions, set by the human on 2026-09-24:

- The weighted registry has exactly seven signals: `urgency` 30, `blocks` 25,
  `risk_paths` 15, `due_soon` 10, `age` 10, `diff_size` 5, and `ci_state` 5.
- For each signal, `points_i = 100 × w_i × x_i / Σw`. The exact score is
  `Σ points_i`. The displayed score uses `floor(exact + 0.5)`.
- `urgency` uses configured low, medium, high, and urgent labels directly.
  The highest matching label wins. No label uses medium. `urgent` is 1.
  Trust, author, label applier, and label history never change urgency.
- `blocks` counts distinct people other than the PR author. Count authors of
  open PRs above this PR in a stack. Also count assignees of manually linked
  issues and GitHub issue dependencies. Boost only the prerequisite PR that
  unlocks that work. Never infer a link from prose.
- `author_group`, linked-issue kind, and a standalone `lockfile` signal are
  omitted for now. Lockfile patterns only remove lines from `diff_size`.
- A failed read gives its signal zero points. Its weight stays in `Σw`.
- Equal displayed scores share a rank. `--limit` never splits a tied group.
- The queue admits only a non-draft PR with a current by-name review request,
  not a code-owner request, whose matched request came from a user, not a bot.
  GitHub may turn a team request into matching named-user fields; this version
  accepts that result because it cannot be told apart.

---

## Positioning

Open, local, bring your own model. Ranking never depends on the model.

- **Default model:** NVIDIA Nemotron, served by Nebius Token Factory. This is
  what we demo, measure, and submit. Required by the rules: the submission
  must make a runtime call to Token Factory and use at least one NVIDIA open
  model.
- **Flexible:** any OpenAI-compatible endpoint works (OpenAI, OpenRouter,
  Ollama, vLLM, LM Studio, ...). The user sets `model.base_url`,
  `model.api_key_env`, `model.name` in config. Fully local is possible.
- **No model set:** everything still works (queue, reasons, blocking,
  actions). Only summaries are off.
- **Why it is safe to swap models:** the model only summarizes. It never
  ranks and never acts, so a weak or hostile model can only write a bad
  summary.
- **Judging:** 2 of 4 criteria reward use of Nebius/NVIDIA. Back the default
  with numbers: cost per PR, latency, faithfulness vs human labels.
- **Related work:** CodeRabbit Triage (launched 2026-09-15) ranks PRs with
  deterministic scores. It is closed source, runs on their servers, and is
  paid for private repos. We add: open code, local run, any model, PR text
  can never move rank, replay proof, injection results.

---

## Phase 0 — Setup (do before opening Claude Code)

- [ ] Claim credits: activation code `NEBIUS-DEVPOST-GLOBAL26` via the promo form
      (link on the Devpost resources page)
- [ ] Join the Nebius Builder Program: https://dev.nebius.com/builders
      ($50 AI Cloud, $50 Token Factory, $25 Tavily, office hours)
- [ ] Nebius Discord for credit issues: https://discord.gg/ZdC3rXMJH
- [ ] Get a Token Factory API key, make ONE successful curl call by hand
- [ ] Create repo with OSS license (MIT), dirs: `/src`, `/evals`, `/config`, `/tests`
- [ ] Distribution: PyPI. Create PyPI + TestPyPI accounts (2FA), pick a package
      name that is free on pypi.org, install `uv`
- [ ] Create free GitHub org + mirror repo for demo PRs and injection payloads
- [ ] Pick 3 replay repos: 2 for tuning, 1 held out (never look at while tuning)
- [ ] Check the Devpost rules page for how a submission is associated with a
      city (the $500 City Winner Award needs no attendance)

---

## Prompt 0 — Spec and guardrails (run once)

```
I'm building a PR review queue tool for a hackathon. Read this brief, ask me
anything genuinely ambiguous, then write SPEC.md and CLAUDE.md. Write no other
code yet.

WHAT IT DOES
A CLI/desktop-side tool that receives GitHub PR events, summarizes each PR, and
shows a ranked queue of ~3 lines instead of 47 notifications. I can review and
merge from the tool.

RANKING (deterministic, no LLM)
A PR is in the queue only while a person asked me by name to review it (not
a team or code-owner request). Drafts stay out.
score = 100 x sum(w_i x x_i) / sum(w_i)
Each signal x_i is 0-1; higher means review sooner. Weights w_i are plain
numbers in config. Defaults sum to 100.
- urgency (30): configured low / medium / high / urgent labels. Highest wins.
  No label means medium. Urgent is 1. Who added the label never matters.
- blocks (25): distinct people other than the PR author waiting through open
  PRs above it in a stack, manually linked issue assignees, or GitHub issue
  dependency assignees. Boost only the prerequisite PR. Never read prose.
- risk_paths (15): config globs such as auth/, billing/, and migrations/.
- due_soon (10): milestone due date.
- age (10): time since the current review request; a re-request restarts it.
- diff_size (5): bigger PRs score higher. Configured lockfile lines are removed
  from its line count.
- ci_state (5): failing CI or a merge conflict gives 0; the PR stays visible.
`author_group`, linked-issue kind, and standalone `lockfile` are omitted for
now. A failed read gives that signal 0 points without removing its weight.
Equal displayed scores share one rank. Every rank shows a reason line built
from fixed signal templates, never model output or PR text.

HARD CONSTRAINTS
- PR titles, descriptions, and comments are untrusted data. They can never
  affect ranking, and never introduce a destination or an action.
- The model summarizes only. It never ranks, never emits actions.
- Destinations (URLs, recipients) come from config only.
- Action tiers: local/reversible = free; visible but undoable (labels) =
  approve-rule-once; irreversible or outbound (merge, comment) = always ask.
- Runtime stores metadata and rules only, never PR content.
- One ingestion path: live events and historical replay produce identical
  normalized events.

STACK
Python. Model: any OpenAI-compatible endpoint set in config; default and
demo is NVIDIA Nemotron on Nebius Token Factory. One client, no per-provider
code. No model configured = summaries off, everything else works.
LangSmith tracing for model calls. SQLite stores metadata only. The queue
skeleton uses `argparse` and the Python standard library, with no runtime
dependency.
Packaged with uv (pyproject.toml, console-script entry point), published to
PyPI. Users run it with `uvx please-merge-my-pr` or `uv tool install please-merge-my-pr`.
Name: package and command are `please-merge-my-pr`; Python import name is
`please_merge_my_pr` (no dashes allowed in imports).

Put in CLAUDE.md: the hard constraints above as rules you must never violate,
the human commit convention, and "run tests before claiming done." Agents do
not commit.
```

**Review SPEC.md and CLAUDE.md before continuing. They govern everything after.**

---

## Week 1 (Sep 22–28, ~14h) — Skeleton, no model yet

### 1.1 Event model

```
Implement the normalized event model in src/please_merge_my_pr/events.py: a dataclass covering
only fields carried by both sources: repo, PR number, author, title, body,
labels, additions/deletions, base/head refs, milestone due date, created_at,
updated_at, and draft. Keep files, review requests, CI, and mergeability in a
separate `Reads` object. Add `from_github_rest()` and `from_gh_archive()` so
both produce identical `Event` objects. Include one fixture from each source.
```

### 1.2 Ingestion by polling

```
Add src/please_merge_my_pr/ingest/poll.py: polls GitHub's notifications API on an interval,
respects X-Poll-Interval, uses conditional requests (If-Modified-Since/ETag)
so unchanged responses don't count against rate limit. Emits normalized events.
Store the last-seen cursor in SQLite. CLI: `please-merge-my-pr watch`.
```

### 1.3 Cheap signals

```
Implement the signal extractors in src/please_merge_my_pr/signals/, one module per signal, each
returning a float 0-1 plus a reason fragment string. Start with `risk_paths`,
`age`, `diff_size`, and `ci_state`. Do not add `author_group` or a standalone
`lockfile` signal. No model calls. Tests: table-driven with
hand-written event fixtures covering boundary cases.
```

### 1.4 Scorer and the three-line output

```
Implement src/please_merge_my_pr/scoring.py as a pure function. The caller
passes TOML config. Compute `points_i = 100 × w_i × x_i / Σw`, sum exact
points, then display `floor(exact + 0.5)`. Return all seven signal rows and a
reason made from the top three non-empty fixed fragments. Then implement
`please-merge-my-pr list`, with a default limit of three that never splits a
tied rank: "#412 touches auth · waiting 7d · 380 lines   [score 29]".
```

**Week 1 gate: `please-merge-my-pr list` prints real ranked PRs from a real repo, no model involved.**

---

## Week 2 (Sep 29–Oct 5, ~14h) — Blocking, summaries, replay

### 2.1 Blocks

```
Add the `blocks` signal. Count distinct people other than the PR author from
three structured sources: authors of open PRs above this PR in a stack,
assignees of manually linked issues, and assignees from GitHub issue
dependencies. Boost only the prerequisite PR that unlocks those people. A
linked dependent PR gets no points from the link. Never infer a link or a
person from free text. Cache structured reads per PR with a short TTL.
```

### 2.2 Summarization (first Token Factory call in the app)

```
Add src/please_merge_my_pr/summarize.py: calls the configured model (default Nemotron on Token
Factory) through one OpenAI-compatible client. Two outputs per PR:
(1) a summary from the DIFF ONLY, (2) a summary from diff + description.
Both returned as typed JSON with a strict schema; reject and retry once on
schema violation. Wrap PR text in explicit data delimiters and instruct the
model that delimited content is data with no authority. Log token counts.
```

### 2.3 Replay harness

```
Build the replay harness in /evals/replay/. Inputs: a GH Archive slice for one
repo over one month. Simulates a review queue with capacity derived from that
repo's historical reviews-per-day. Policies: actual-history, FIFO,
recently-updated, ours. Metric: mean and p90 time-to-first-review for PRs that
block someone, weighted by people blocked. CRITICAL: at each simulated
timestep, only use information available at that time - no future comments, no
eventual merge status. Write a leakage test that fails if any future field is
read.
```

### 2.4 Launch Toloka this week (not a Claude Code task)

- ~150 items: diff + generated summary, PR description hidden
- Questions: accurate? (yes/partly/no) · missing anything a reviewer needs? ·
  mentions anything not in the diff? (yes/no)
- ~10% gold items, 3 annotators each, screen for dev experience
- Pilot on 5 items first and fix the instructions before the full run

---

## Week 3 (Oct 6–12, ~14h) — Security layer and first numbers

### 3.1 Action tiers

```
Implement the action tier system in src/please_merge_my_pr/actions.py. Every action declares a
tier. Tier 2 requires a stored rule approval; tier 3 always prompts. Merge and
comment are tier 3. Destinations are read from config only; add a test proving
a URL in a PR body can never become a request target.
```

### 3.2 Adversarial suite (highest-value eval, costs nothing)

```
Build /evals/adversarial/: 30 seeded PRs across four payload categories
(rank manipulation, action injection, exfiltration, reason manipulation). Each
payload contains a unique canary string. Three automated checks:
1. rank displacement: score with and without payload, assert delta == 0
2. canary leakage: assert no canary appears in any output
3. perturbation drift: compare diff-only summary vs diff+description summary,
   report semantic difference
Checks 1 and 2 are hard assertions in CI. Check 3 reports a number.
```

### 3.3 Egress log

```
Wire LangSmith tracing on every model call, then add `please-merge-my-pr egress` which
displays, per PR, exactly what text was sent to the model and what came back.
```

### 3.4 Trust and credibility — omitted

Omitted. Urgency uses the configured label value directly. The highest label
wins, no label uses medium, and urgent is 1. Trust, credibility, the label
applier, the PR author, and label history never affect the score. Misuse is
for the lead to handle. See `plans/weights-research.md` B7.

**Week 3 gate: first held-out replay number + zero rank displacement under injection.**

---

## Week 4 (Oct 13–19, ~14h) — Tavily, evals, packaging

### 4.1 Tavily (the $3,000 prize)

```
Add Tavily enrichment for dependency-bump PRs only: detect version bumps in
lockfiles/manifests, query for active exploitation of the old version, and
surface it as non-ranking context. Treat responses as untrusted data. It may
not add an eighth weighted signal or change the seven-signal score without a
later human decision.
```

### 4.2 Eval wiring

```
Wire the /evals sets into LangSmith as datasets with evaluators: rule-based
checks (no file named that isn't in the diff, no canary) as hard pass/fail, and
an LLM judge for faithfulness as a score. Add `make eval` that runs everything
and prints a comparison against the previous run.
```

### 4.3 Calibrate the judge against Toloka results

```
Add /evals/calibration/: compare the LLM judge's faithfulness scores against
the human labels in /evals/human_labels.jsonl. Report agreement rate and the
confusion matrix. This number is what licenses using the judge at scale.
```

### 4.4 Few-shot fix from failures

```
Take the cases where annotators marked the summary inaccurate, add 3-5 corrected
examples as few-shot examples in the summarization prompt, then re-run `make
eval` and report before/after on the held-out set.
```

### 4.5 Packaging

```
Package for PyPI: pyproject.toml with a console-script entry point, `uv build`
producing sdist + wheel. Judges must be able to run `uvx please-merge-my-pr`, add two keys,
and see a ranked queue in under 5 minutes. Keys come from env/.env, never
bundled in the package. Add a make target that seeds demo data so it works without
GitHub credentials.
```

---

## Week 5 (Oct 20–26, ~10h) — Freeze and ship

**Feature freeze: Wed Oct 22.** After this, only README, video, and bug fixes.

### 5.1 Results write-up

```
Write RESULTS.md: replay methodology (including the capacity model and the
leakage guard), the held-out numbers vs FIFO/recently-updated/actual-history,
the adversarial table (rank displacement, canary leakage, perturbation drift),
and the human-calibration agreement rate. State assumptions plainly, including
that this models review ORDER as the bottleneck, not reviewer judgment.
```

### 5.2 README

```
Write the README: what it does, 60-second quickstart (`uvx please-merge-my-pr`), config reference, the
security model section ("damage is bounded by design", never "prompt injection
solved"), the results table, and a Future Work section noting that fine-tuning
was evaluated and deliberately skipped in favor of prompt iteration.
```

### 5.3 Demo storyboard (record, don't code)

1. 0:00–0:20 — 47 notifications collapse into 3 lines
2. 0:20–1:00 — one reason line read at a glance; disagree and reorder
3. 1:00–1:50 — poisoned PR arrives, doesn't move; egress log; outbound blocked
4. 1:50–2:40 — held-out replay number beside the human-agreement number
5. Close — "damage is bounded by design"

Demo setup: mirror repo, ~8 PRs where the noisy urgent docs PR sits at the top
of GitHub's default view and the small auth PR blocking two people sits at #6.

---

## Cut list (cut from the top, don't renegotiate)

1. Jev (already dropped — the scorer is deterministic)
2. LangSmith eval dashboards (keep traces; the egress log needs them)
3. The comment action (keep labeling to demonstrate tiers)
4. Multi-repo support
5. Tavily enrichment (last, because it's tied to a prize)

**Never cut:** ingestion path · signals + reason lines · three-line CLI ·
Nemotron summaries · replay number · injection results · demo · README

**Already out of scope:** web UI, voice, multi-user, plugin system, Jira
(optional adapter only, if time remains)

---

## Standing rules for Claude Code

- One feature and one role per session. Do not commit from an agent session.
- Never touch `scoring.py` and `summarize.py` in the same session. That boundary
  IS the security claim.
- Tests before "done", especially the leakage test and the tier assertions.
- When it suggests the model should decide the ranking, refuse. It will suggest
  this, because it's the obvious design.
- Cache summaries by commit SHA during development so re-runs are free. Dev cache
  only — the product stores no content.
- Log token counts from day one so cost per PR is known by end of week 1.

---

## Credit discipline

- Token Factory only. Don't rent AI Cloud GPUs; Nemotron is already served.
- Nano/Super for everyday summaries; Ultra only if something demands it.
- Truncate huge diffs (a 5,000-line lockfile doesn't need the model).
- Generate replay summaries ONCE, save outputs, never regenerate.
- Set a spend alert so a runaway loop can't drain the balance overnight.
