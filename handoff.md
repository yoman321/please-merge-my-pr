# Handoff
<!-- role: Plan | model: claude-opus-5-5 | base: none (not a git repo) | date: 2026-09-22 -->

Feature:  weights-research        Plan: plans/weights-research.md    Status: draft
Phase:    0 of 5 — not started

State:    6 draft plans. Order: weights-research → cli-design → queue-skeleton →
          queue-signals → queue-actions → replay-harness. First two are research/design, no product code.
          Summaries (the only model code) come after all six. Mockup in mock/queue_mock.py.
          Direction: bring-your-own model (any OpenAI-compatible endpoint); default Nemotron on Token Factory. See PLAN.md § Positioning.
Next:     Human picks which role runs weights-research (AGENTS.md has no Research role), then run it.
Blocked:  Project folder renamed to please-merge-my-pr. Not a git repo, so no base sha (`git init` fixes). AGENTS.md §5 Commands and Stack are placeholders.
Gates:    0/0. None written yet.
Verified: python3 mock/queue_mock.py list → prints 3-line queue. No product code exists.
