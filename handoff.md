# Handoff
<!-- role: Plan | model: claude-opus-5-5 | base: 9d259c88909ee6005aa1c6fb3175984e81109d1e | date: 2026-10-05 -->

Feature:  user-init          Plan: plans/user-init.md      Status: draft
Phase:    0 of 5 — plan written, parked as draft

State:    plans/user-init.md written: setup inventory U1–U11, invariants I1–I13, 5 phases, 29 planned gates. Adds a setup-step registry (src/please_merge_my_pr/setup_steps.py), a `doctor` command that reports then offers 4 fixes with [y/N], an `init` closing hint, and a README Setup section kept in step by a gate.
          Rules changed per human instruction: AGENTS.md §1 Plan `done` now requires `## Setup impact`; §9 now says a user setup change updates the registry + README ## Setup. Rule: every change that adds, changes, or removes a user setup step must update the user-init registry.
          Live demo still up: FailingEngineBot/please-merge-my-pr-playground, PRs #1–#11 request review from yoman321. Seed tooling: ~/Desktop/pmmp-playground-seed (`seed.py plan|seed|teardown`). Bot token: ~/.config/pmmp-bot-token.
Next:     Plan session for the next feature, once the human names it. user-init is parked as draft on purpose (human, 2026-10-05): build it later, when most of the tool works. Do not freeze or build it until the human says so.
Blocked:  Next feature not named. The human names it.
          Other open items for the human:
          - plans/weights-research.md has Status: reviewed. AGENTS.md allows only draft or frozen.
          - plans/chat.md gate 74 text does not state the exit code; the gate asserts 1.
          - Singular grammar: "blocks 1 people" (signals/blocks.py), "1 lines" (signals/diff_size.py). Not changed.
          - `list` took ~33s wall time for 10 PRs on the live repo. Not investigated.
Gates:    user-init: none written yet (plan is draft). chat: 76/76 pass at last run (2026-09-26), not rerun. Known §7 fails left in chat:
          lint: `TRY004 Prefer TypeError exception for invalid type` at src/please_merge_my_pr/onboarding.py:150.
          format: `1 file would be reformatted, 65 files already formatted` — src/please_merge_my_pr/tools.py (near line 63).
Verified: Plan session; no code changed, no tests run. Earlier this session: `uv run please-merge-my-pr list --all` as yoman321 → 10 in queue, draft #11 filtered out.
