<!-- role: Plan | model: claude-opus-5-5 | base: f314cd4 | date: 2026-09-22 -->
Status: draft
Phases: 4

# Onboarding

Step 4 of the build order. Requires `queue-skeleton` built (scorer, `list`)
and `research/weights.md` (presets). Screens follow `design/cli.md`.

## Goal

A new user goes from install to their own ranked queue in one command:
`please-merge-my-pr init`. It asks a few questions, shows the effect of
their weight choice on their real PRs, and writes one config file. A
`config` command changes settings later.

## Out of scope

- Trust and credibility logic (uses what `init` writes; built in `queue-signals`)
- Model calls (`init` only records model settings; see `summaries`)
- Team-shared config files (open question 3)

## Invariants

- **O1 — Zero setup works.** `--demo` runs with no config. Any other command
  with no config prints one line pointing to `init` and exits nonzero. It
  never crashes or guesses.
- **O2 — No secrets in config.** The config stores environment variable
  names (`api_key_env: NEBIUS_API_KEY`), never keys or tokens. GitHub auth
  comes from `gh auth token` or an env var at run time.
- **O3 — Checked on load.** Unknown keys, negative weights, all-zero
  weights, NaN, or a missing required field → an error that names the key and
  the file. Never a silent default, never a silently wrong rank.
- **O4 — Re-runnable and safe.** `init` on an existing config starts from
  its current values and changes only what the user changes. Writes are
  atomic (temp file, then rename) and keep one backup.
- **O5 — Weights come from the user.** Weights load only from the user's
  config (W7 in `weights-research`). No repo or PR data changes them.
- **O6 — Scriptable.** Every question has a flag. `init --yes` plus flags runs
  with no prompts. Not a terminal and a needed answer missing → refuse, name
  the missing flag.
- **O7 — Preview is real.** The live top-3 preview uses the same scorer and
  data as `list`. Same config → same order in both.
- **O8 — No PR content in config.** Config holds repos, paths, logins, weights,
  model settings. Never titles, bodies, or diffs.
- **O9 — No spending without asking.** `init` makes no model call unless the
  user says yes to a test call.

## Phases

### 1. Config schema and loader — `src/please_merge_my_pr/config.py`

- One file at `$XDG_CONFIG_HOME/please-merge-my-pr/config.<ext>` (default
  `~/.config/...`). `--config PATH` overrides.
- Sections: `github` (auth source, repos), `model` (`base_url`,
  `api_key_env`, `name`, or absent), `risk_paths`, `trust` (logins per tier),
  `weights` (preset name + per-signal overrides), `display` (limit).
- Loader validates everything (O3). Replaces skeleton's `config/weights.yaml`.

### 2. `init` wizard — `src/please_merge_my_pr/onboarding.py`

In order, each skippable where it makes sense:
1. GitHub: detect `gh auth token`; else ask which env var holds a token.
2. Repos: list the user's recent repos, pick one or more.
3. Model: Nemotron on Token Factory (default), another OpenAI-compatible
   endpoint, or none. Records settings only (O9). Optional test call.
4. Risky paths: suggest `auth/`, `billing/`, `migrations/`, `security/` if
   they exist in the repo; user edits.
5. Trust: who is `lead` and `teammate` (logins).
6. Weights: step 3 below.

### 3. Weight presets and live preview — `src/please_merge_my_pr/onboarding.py`

- Presets from `research/weights.md` (for example unblock people, hit
  deadlines, safety first, balanced).
- After a pick, show the user's real top 3 with reasons (O7). "Custom" lets
  them change one weight at a time and see the top 3 update.

### 4. `config` command — `src/please_merge_my_pr/cli.py`

- `config show`, `config path`, `config set <key> <value>`, `config edit`
  (opens `$EDITOR`, validates on save).

## Gates to write

- `test_demo_without_config` — `--demo` runs with no config file (O1)
- `test_missing_config_message` — no config → exit nonzero, message names `init` (O1)
- `test_config_has_no_secrets` — run `init` with a real-looking token in env;
  the written file does not contain it (O2)
- `test_invalid_weights_rejected` — negative, all-zero, NaN, unknown key,
  each → error naming the key (O3)
- `test_rerun_keeps_values` — second `init --yes` with one flag changed →
  only that value differs (O4)
- `test_atomic_write` — write interrupted → old file intact (O4)
- `test_preview_matches_list` — preview order == `list` order (O7)
- `test_non_tty_missing_flag` — refused, message names the flag (O6)
- `test_no_model_call_by_default` — `init --yes` with model settings,
  network to model host patched to raise → passes (O9)

## Assumptions

- Config lives under XDG paths on macOS and Linux alike (like `gh`).
- One config per user. Per-repo overrides can come later.

## Open questions

1. Config format. TOML: Python reads it with no dependency, but writing it
   needs a small library or hand-written output. YAML: needs PyYAML to read
   and write. Which?
2. Test model call during `init`: offer it (costs a few tokens) or skip?
3. Team-shared weights from a repo file (read from the default branch only,
   per W7): in scope for the hackathon, or later?
