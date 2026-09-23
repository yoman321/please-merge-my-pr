# Handoff
<!-- role: Plan | model: claude-opus-5-5 | base: f314cd4 | date: 2026-09-22 -->

Feature:  weights-research        Plan: plans/weights-research.md    Status: draft
Phase:    0 of 5 — not started

State:    Project named please-merge-my-pr (PyPI package + command; import please_merge_my_pr).
          8 draft plans, in build order: weights-research → cli-design → queue-skeleton → onboarding →
          queue-signals → queue-actions → replay-harness → summaries. First two are research/design only;
          summaries is the only model code. Order also listed in PLAN.md.
          Direction: bring-your-own model via any OpenAI-compatible endpoint; default NVIDIA Nemotron
          on Nebius Token Factory (required by hackathon rules). See PLAN.md § Positioning.
          Research (competitors, hackathon rules, name checks): research/landscape.md.
          UX mockup: mock/queue_mock.py (fake data, not a phase).
Next:     Human picks which role runs weights-research (AGENTS.md has no Research/Design role), then run it.
Blocked:  Decisions for a human (each plan's "Open questions" has the detail) —
          - Role for weights-research and cli-design (add one to AGENTS.md, or run as Build limited to research/, design/, mock/)
          - weights-research Q2: is "blocking people first" a fixed rule or a changeable default?
          - cli-design Q1–2: Rich vs plain ANSI (Rich = new dependency); how playful the copy is
          - queue-skeleton Q1–6: Click/Typer, Python version, test repo, GitHub auth, GH Archive gaps, watch vs list
          - onboarding Q1–3: TOML vs YAML config, test model call in init, team-shared weights
          - queue-signals Q2–3, queue-actions Q1–2, replay-harness Q1, Q3
          - summaries Q1–3: approve openai/langsmith/pydantic deps; egress vs no-content-at-rest; schema fields
          - No git remote yet. No LICENSE file (rules require one; PLAN.md says MIT).
          - AGENTS.md §5 Commands and Stack are placeholders.
          - Plans written before git init say base "none"; onboarding and summaries say f314cd4.
Gates:    0/0. None written yet.
Verified: python3 mock/queue_mock.py list → prints 3-line queue. Secret scan of repo → none found. No product code exists.
