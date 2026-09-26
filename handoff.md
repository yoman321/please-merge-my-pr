# Handoff
<!-- role: state change + gate edits (human instruction) | model: claude-opus-5-5 | base: 251926649600f0750c78f760549e2c2a5e4f1e37 | date: 2026-09-26 -->

Feature:  chat          Plan: plans/chat.md      Status: frozen
Phase:    16 of 16 — source built; all tests pass; lint and format fail

State:    Phases 1–16 source is built. The 22 Build review findings are [accepted]; zero [open] remain.
          Human overrides this session, logged here: (a) "accept all" findings despite AGENTS.md §4 "never all";
          (b) the gate edits below despite AGENTS.md §11 "never edit a gate". The human picked each gate fix by name.
          plans/chat.md:579 [open] → [accepted], per human instruction (src/please_merge_my_pr/chat.py:103)
          plans/chat.md:580 [open] → [accepted], per human instruction (src/please_merge_my_pr/chat.py:329)
          plans/chat.md:581 [open] → [accepted], per human instruction (src/please_merge_my_pr/config.py:353)
          plans/chat.md:582 [open] → [accepted], per human instruction (src/please_merge_my_pr/model.py:62)
          plans/chat.md:583 [open] → [accepted], per human instruction (src/please_merge_my_pr/chat.py:301)
          plans/chat.md:584 [open] → [accepted], per human instruction (src/please_merge_my_pr/cli.py:271)
          plans/chat.md:585 [open] → [accepted], per human instruction (src/please_merge_my_pr/chat.py:467)
          plans/chat.md:586 [open] → [accepted], per human instruction (src/please_merge_my_pr/onboarding.py:114)
          plans/chat.md:587 [open] → [accepted], per human instruction (src/please_merge_my_pr/onboarding.py:77)
          plans/chat.md:588 [open] → [accepted], per human instruction (src/please_merge_my_pr/actions.py:189)
          plans/chat.md:589 [open] → [accepted], per human instruction (src/please_merge_my_pr/github/read.py:318)
          plans/chat.md:590 [open] → [accepted], per human instruction (src/please_merge_my_pr/github/http.py:64)
          plans/chat.md:591 [open] → [accepted], per human instruction (src/please_merge_my_pr/tools.py:60)
          plans/chat.md:592 [open] → [accepted], per human instruction (src/please_merge_my_pr/overlay.py:50)
          plans/chat.md:593 [open] → [accepted], per human instruction (src/please_merge_my_pr/chat.py:407)
          plans/chat.md:594 [open] → [accepted], per human instruction (src/please_merge_my_pr/chat.py:413)
          plans/chat.md:595 [open] → [accepted], per human instruction (src/please_merge_my_pr/signals/age.py:19)
          plans/chat.md:596 [open] → [accepted], per human instruction (src/please_merge_my_pr/chat.py:169)
          plans/chat.md:597 [open] → [accepted], per human instruction (architecture/architecture.md:30)
          plans/chat.md:598 [open] → [accepted], per human instruction (architecture/architecture.md:47)
          plans/chat.md:599 [open] → [accepted], per human instruction (architecture/architecture.md:33)
          plans/chat.md:600 [open] → [accepted], per human instruction (architecture/architecture.md:56)
          Gate edits (human-chosen fixes for gate conflicts):
          g39 (tests/test_weights.py, 2 tests) — checks only the final `/list` output, `run.segments()[1]`, not preview rows.
          g38 (tests/test_weights.py) — config path compared through `compact()`, so an 80-column wrap is allowed.
          g03 (tests/test_chat.py), g17 (tests/test_tools.py, 2 tests) — call new `freeze_clock` (tests/chat_harness.py), which pins `datetime.now` in `cli` and `chat`.
          g74 (tests/test_actions.py) — direct `open` with a missing browser must exit 1; slash and tool paths stay 0.
Next:     Build session: fix `TRY004` at src/please_merge_my_pr/onboarding.py:150 and run `ruff format` on src/please_merge_my_pr/tools.py; rerun §7.
Blocked:  none for code. Open rule items for the human:
          - plans/chat.md gate 74 text does not state the exit code; the gate now asserts 1. Only Plan/Grade may add it to the plan.
          - Plan provenance recorded Plan work inside a Write-the-gates session (§0.6); Phases 12–16 were not graded.
          - AGENTS.md names the Build model `sol`; Build provenance says `gpt-5`.
Gates:    76/76 pass. Failing: none. Remaining §7 failures:
          lint: `TRY004 Prefer TypeError exception for invalid type` at `src/please_merge_my_pr/onboarding.py:150` (`raise ValueError(f"invalid config: {key}")`).
          format: `1 file would be reformatted` — src/please_merge_my_pr/tools.py (near line 62).
Verified: `uv run pytest -q` → 671 passed. `uv run mypy src` → Success, 38 files. `uv run ruff check .` → 1 error (above). `uv run ruff format --check .` → 1 file would be reformatted. `uv build` → built sdist and wheel. `uv run ruff check tests && uv run ruff format --check tests` → pass.
