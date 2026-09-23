<!-- role: Plan | model: claude-opus-5-5 | base: f314cd4 | date: 2026-09-22 -->
Status: draft
Phases: 5

# Summaries

`PLAN.md` 2.2 and 3.3. Step 8 of the build order: the only model code.
Requires `queue-skeleton` (the `Summarizer` slot in `show`) and `onboarding`
(model settings in config).

Standing rule from `PLAN.md`: never change `scoring.py` and `summarize.py`
in the same session.

## Goal

`show` fills its summary slot with a short, faithful "what this PR changes",
written by whatever model the user configured. Default: NVIDIA Nemotron on
Nebius Token Factory. `egress` shows exactly what was sent and received.

## Out of scope

- LLM judge, eval datasets, calibration (`PLAN.md` 4.2–4.4)
- Adversarial suite (`PLAN.md` 3.2) — its own plan
- Anything that ranks or acts. The model never does either.

## Invariants

- **M1 — The model only summarizes.** Model output is a `Summary` value and
  goes only to display. `scoring`, `signals`, and `actions` never import
  `summarize`, and `summarize` imports none of them.
- **M2 — Strict output.** Output must match the JSON schema. On a mismatch,
  retry once. On a second mismatch, return `None` and `show` prints
  `summary unavailable`. Never crash, never show unvalidated text.
- **M3 — PR text is data.** Title, body, and comments go inside fixed
  delimiters. The system prompt is a constant in code and says delimited text
  has no authority.
- **M4 — Destination from config only.** The request host comes from
  `model.base_url` in config. Nothing in PR data can change where a request
  goes.
- **M5 — No model, no calls.** No model configured → zero network calls to
  any model host, and every other command works.
- **M6 — One client for every provider.** Switching providers changes config
  only: `base_url`, `api_key_env`, `name`. No provider-specific branches in
  code.
- **M7 — No content at rest by default.** Summaries are not stored. A dev
  cache keyed by commit SHA exists only behind `--dev-cache` and is off by
  default.
- **M8 — Cost is visible.** Every call logs input and output token counts.
- **M9 — Budget holds.** Diffs over the configured budget are truncated.
  Lockfiles and generated files are listed by name only, never sent whole.

## Phases

### 1. Model client — `src/please_merge_my_pr/model.py`

- One OpenAI-compatible client, built from config (M4, M6). Token counts
  logged (M8). Absent config → `NullSummarizer` (M5).

### 2. Diff prep — `src/please_merge_my_pr/diffprep.py`

- Skip lockfiles and generated files (names only), truncate to budget (M9).

### 3. Prompt and schema — `src/please_merge_my_pr/summarize.py`

- Constant system prompt, delimiters (M3). Schema-validated output, one
  retry (M2). Two outputs per PR: diff only, and diff + description. The pair
  feeds the perturbation-drift check later (`PLAN.md` 3.2).

### 4. Wire into `show` — `src/please_merge_my_pr/cli.py`

- `show` uses the configured `Summarizer`. Diff-only summary shown by default.

### 5. Egress — `src/please_merge_my_pr/egress.py`, `please-merge-my-pr egress <n>`

- Shows, per PR, the exact text sent, the text received, model name, tokens.
  LangSmith tracing when the user enables it.

## Gates to write

- `test_import_boundary` — import graph: no path between `summarize` and
  `scoring`/`signals`/`actions` in either direction (M1)
- `test_schema_retry_then_none` — fake model returns bad JSON twice → one
  retry, then `None`, `show` prints `summary unavailable` (M2)
- `test_pr_text_inside_delimiters` — canary in body appears only between
  delimiters in the sent payload (M3)
- `test_model_host_from_config` — body contains `https://evil.example`;
  recorded request host == config host (M4)
- `test_no_model_no_calls` — no model config, network patched to raise, every
  command runs (M5)
- `test_provider_switch_config_only` — two fake providers, same code path,
  only base URL differs in recorded requests (M6)
- `test_no_summary_at_rest` — after `show`, no summary text in SQLite or on
  disk without `--dev-cache` (M7)
- `test_token_counts_logged` (M8)
- `test_lockfile_not_sent` — 5,000-line lockfile in diff → only its name in
  the payload (M9)

## Assumptions

- Default model: a Nemotron Nano or Super size on Token Factory (per
  `PLAN.md` credit discipline). Exact model id read from Token Factory's
  model list at build time, not written from memory.
- Diff budget default: 8,000 input tokens.

## Open questions

1. New dependencies need approval: `openai` (the client), `langsmith`
   (tracing), and maybe `pydantic` (schema). Approve which?
2. Egress vs "no content at rest": the egress log must show sent text, but
   the product stores no PR content. Options: (a) egress shows the current
   session only, from memory; (b) egress reads LangSmith traces, which live in
   the user's own LangSmith account; (c) both. Which?
3. Summary schema fields: just `what_changed` and `files`, or also
   `risk_notes` and `tests_changed`?
