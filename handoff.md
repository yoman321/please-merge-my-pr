# Handoff
<!-- role: state change (human instruction) | model: claude-opus-5-5 | base: 3b625c74b6c5118e0126cbdc6cc5febc9113d6a4 | date: 2026-10-05 -->

Feature:  <not named yet>          Plan: plans/<name>.md      Status: none (not started)
Phase:    0 of ? — no plan yet

State:    Chat (plans/chat.md, 16 of 16 phases) is done, per human instruction on 2026-10-05. Work moves to the next plan.
          The human marked chat done with 2 known lint/format fails left in (see Gates).
          AGENTS.md was replaced with the new template this session, per human instruction. §5 keeps the repo's uv commands.
Next:     Plan session for the next feature. The human names the feature first.
Blocked:  Next feature not named. The human names it.
          Open items for the human:
          - plans/weights-research.md has Status: reviewed. The new AGENTS.md allows only draft or frozen.
          - plans/chat.md gate 74 text does not state the exit code; the gate asserts 1.
Gates:    chat: 76/76 pass at last run (2026-09-26). Not rerun this session. Known §7 fails left in chat:
          lint: `TRY004 Prefer TypeError exception for invalid type` at src/please_merge_my_pr/onboarding.py:150 (`raise ValueError(f"invalid config: {key}")`).
          format: `1 file would be reformatted, 65 files already formatted` — src/please_merge_my_pr/tools.py (near line 63).
Verified: `uv run ruff check .` → Found 1 error (TRY004, above). `uv run ruff format --check .` → 1 file would be reformatted.
