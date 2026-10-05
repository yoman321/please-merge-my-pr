<!-- role: Plan | model: claude-opus-5-5 | base: 9d259c88909ee6005aa1c6fb3175984e81109d1e | date: 2026-10-05 -->
Status: draft
Phases: 5

# User init

## Goal

Record everything a user must do to get `please-merge-my-pr` running after download, in one place in code. Build a `doctor` command that checks each step, says how to fix what is missing, then offers to fix the steps it can, one `[y/N]` at a time. Keep the README setup section in step with that same list.

Later features that add a setup step add it to the same list. See "Keeping it current" below.

## Current baseline

- `init` asks for repos, GitHub API URL, web URL, token env name, and optional model settings, then writes the config after `[y/N]` (`src/please_merge_my_pr/onboarding.py:70`). It checks nothing on the machine.
- No config file is fine. `load_config` falls back to defaults (`src/please_merge_my_pr/config.py:78`).
- The GitHub token comes from the env var named by `github.token_env`, else `gh auth token` (`src/please_merge_my_pr/github/auth.py:15`).
- `watch` reads `/notifications` (`src/please_merge_my_pr/ingest/poll.py:61`).
- Chat starts only when stdin and stdout are terminals (`src/please_merge_my_pr/cli.py:116`) and opens `/dev/tty` (`src/please_merge_my_pr/chat.py:554`).
- Local state lives at `$XDG_STATE_HOME/please-merge-my-pr/state.sqlite3`, else `~/.local/state/...` (`src/please_merge_my_pr/cli.py:169`).
- `config edit` needs `VISUAL` or `EDITOR` (`src/please_merge_my_pr/onboarding.py:160`). `open` uses `BROWSER`, else the system default (`src/please_merge_my_pr/actions.py:187`).
- README has a short Setup section that clones and runs `uv sync`.

## Setup inventory

Everything a user does from download to first ranked list. U1–U2 happen before the tool exists on the machine, so they live only in README. U3–U11 are registry steps (I1).

| Id | Step | Required | Needed for | How the user does it |
|---|---|---|---|---|
| U1 | Get Python 3.13+ via `uv` | yes | install | Install `uv`. It fetches Python by itself. |
| U2 | Install the tool | yes | everything | `uv tool install please-merge-my-pr` (D1). |
| U3 `github-auth` | GitHub token found | yes | all live reads and actions | `gh auth login`, or set the env var named by `github.token_env` (default `GITHUB_TOKEN`). |
| U4 `github-access` | Token works and can search review requests | yes | `list`, `why`, `show`, chat | Token must reach `api_url` and see the repos where reviews are asked. A `gh` login or a classic token with `repo` works. A fine-grained token sees only one owner's private repos. |
| U5 `config` | Config file is absent or valid | yes | everything | Optional file. `init` makes one. Absent → defaults. Invalid → every command stops. |
| U6 `state-dir` | State directory is writable | yes | hide, snooze, rules, watch, `list` filter | `$XDG_STATE_HOME` or `~/.local/state` must be writable. |
| U7 `model` | Model endpoint configured | no | plain-language chat | Set `model.base_url`, `model.name`, and, if the endpoint needs a key, the env var named by `model.api_key_env`. Without it, slash commands still work. |
| U8 `notifications` | Token can read notifications | no | `watch` | `gh` login or a classic token with `notifications` or `repo`. Fine-grained tokens cannot read `/notifications`. |
| U9 `terminal` | Interactive terminal | no | chat | Run in a real terminal, not a pipe. |
| U10 `editor` | Editor set | no | `config edit` | Set `VISUAL` or `EDITOR`. |
| U11 `browser` | Browser found | no | `open` | Set `BROWSER`, or have a system default browser. |

## Out of scope

- Publishing to PyPI or any registry. That is a human action.
- Changing `init` prompts, their order, or their defaults.
- Changing any existing error message.
- Fixes beyond the four in I8. `doctor` never installs software, edits shell profiles, or sets env vars.
- A `gh` extension, Homebrew formula, or installer script.

## Terms

- **Registry:** the ordered tuple of setup steps in `src/please_merge_my_pr/setup_steps.py`.
- **Step:** one registry entry: `id`, `title`, `required`, `needed_for`, `fix` (text), a check function, and an optional fixer.
- **Check pass:** one run of every check in registry order, then one printed report (I3).
- **Fixer:** code that changes the machine to make one step `ok`. It runs only after the user answers `y` (I8).
- **Status:** the result of one check. Exactly one of `ok`, `missing`, `fail`, `skip`.
  - `ok`: set up.
  - `missing`: an optional step is not set up.
  - `fail`: a required step is not set up, or any check found a broken setup (for example invalid config, rejected token).
  - `skip`: the check could not run because an earlier step it needs is not `ok`.

## Invariants

### I1. One registry

Every post-install setup step is defined once, in `src/please_merge_my_pr/setup_steps.py`, as an entry of one ordered tuple. `doctor` and the README Setup section draw from it. No other module repeats a step's title or fix text.

### I2. Registry covers the inventory

The registry contains at least the ids `github-auth`, `github-access`, `config`, `state-dir`, `model`, `notifications`, `terminal`, `editor`, `browser`, in that order, with `required` as in the inventory table. Ids are unique. New steps may be added later; none of these may be removed without a plan.

### I3. `doctor` output is fixed-shape

`please-merge-my-pr doctor` prints one line per registry step, in registry order:

```text
<status> <title>[ — <detail>]
```

`<status>` is padded to 7 characters. When the status is not `ok`, the next line is `        fix: <fix>` (8 spaces). Apart from the I8 fix prompts, fixer output, and the I10 to-do list, nothing else is printed to stdout. Exit code comes from the last check pass: 0 when every `required` step is `ok`, else 1. A `missing` optional step never changes the exit code.

### I4. Check rules

- `github-auth`: `ok` with detail `via <ENV_NAME>` when that env var is non-empty, else `ok` with detail `via gh` when `gh auth token` returns a token, else `fail`. The `fail` detail and fix name the cause:

  | Cause | Detail | Fix |
  |---|---|---|
  | `gh` not on `PATH` | `<ENV_NAME> is not set and GitHub CLI is not installed` | `install GitHub CLI from https://cli.github.com, then run gh auth login; or set <ENV_NAME>` |
  | `gh` on `PATH`, not logged in | `<ENV_NAME> is not set and gh is not logged in` | `run gh auth login; or set <ENV_NAME>` |
- `github-access`: `skip` unless `github-auth` is `ok`. One GraphQL `viewer { login }` request, then one search request for `is:pr is:open review-requested:@me` (plus the configured `repo:` filters) with `per_page=1`. `ok` with detail `logged in as <login>, <n> review requests`. Any other result → `fail`, with detail and fix by cause. The first matching row wins:

  | Cause | Detail | Fix |
  |---|---|---|
  | 401 | `token rejected (expired or revoked)` | via gh: `run gh auth login`; via env: `make a new token and set <ENV_NAME>` |
  | 403 with `X-RateLimit-Remaining: 0` | `GitHub rate limit reached` | `wait and run doctor again` |
  | other 403 | `token not allowed (missing scope or SSO not authorized)` | `use gh auth login, or a token with repo scope; authorize SSO for your org` |
  | 404 | `API not found at <api_url>` | `check github.api_url with please-merge-my-pr config show` |
  | network error or timeout | `cannot reach <api_url>` | `check your network or github.api_url` |
  | any other status, or bad JSON | `unexpected response from <api_url>` | `run doctor again; check github.api_url` |

  The detail never includes response bodies or headers other than the rate-limit count.
- `config`: `ok` with detail `using defaults` when the file is absent, `ok` with the path when it loads, `fail` with the loader's message when it does not.
- `state-dir`: `ok` when the state directory exists and is writable, or does not exist and its nearest existing parent is writable. Else `fail`. Checked with `os.access`; nothing is created.
- `model`: `missing` when `model.base_url` is unset. `fail` when `model.api_key_env` names an env var that is empty or unset. Else `ok` with detail `<model.name>`.
- `notifications`: `skip` unless `github-access` is `ok`. One GET of `/notifications?per_page=1`. 200 → `ok`. 401, 403, or 404 → `missing`. Other errors → `fail`.
- `terminal`: `ok` when stdin and stdout are TTYs and `/dev/tty` opens for reading. Else `missing`.
- `editor`: `ok` with detail `<VISUAL or EDITOR name>` when either is non-empty. Else `missing`.
- `browser`: `ok` when `BROWSER` is non-empty or `webbrowser.get()` succeeds. Else `missing`. Never opens a browser.

A config that fails to load still lets every other step run, using default config values.

### I5. Checks are read-only and bounded

- Zero model requests, in checks and in fixers.
- A check pass makes at most 3 GitHub requests: viewer, search, notifications. None of them mutate. `doctor` runs at most 2 check passes.
- A check pass creates, changes, and deletes no files and no SQLite rows, and starts no subprocess other than `gh auth token`.
- Only an accepted fixer (I8) may write a file or start another subprocess.
- Runs the same with or without a config file.

### I6. No secrets in output

`doctor` never prints a token, an API key, or the value of any env var. It may print env var names, the GitHub login, the config path, and `model.name`.

### I7. Failures do not crash

A network error, timeout, bad JSON, missing `gh`, or invalid config gives the step a status and a fix line. `doctor` never prints a traceback and exits 0 or 1 only.

### I8. `doctor` offers fixes after the report

After the first check pass, `doctor` offers each fix below whose condition holds, in registry order, one at a time. Each offer prints one line `Fix <title>? [y/N] `. Only `y` or `yes` (any case) accepts. Anything else, empty input, or EOF declines.

| Step | Offered when | Fixer does |
|---|---|---|
| `github-auth` | status `fail` and `gh` is on `PATH` | runs `gh auth login`, attached to the terminal |
| `config` | status `fail` and `VISUAL` or `EDITOR` is set | runs the existing `config edit` flow |
| `model` | status `missing` | asks `Model base URL: `, `Model name: `, `Model API key env (optional): `; builds the full new config; validates it; shows the destination and full redacted TOML; asks `Write this change? [y/N] `; writes with the existing atomic writer after `y` only |
| `notifications` | status `missing` and `github-auth` detail is `via gh` | runs `gh auth refresh -s notifications`, attached to the terminal |

No other step has a fixer. Its `fix:` line is the only help.

When at least one fixer ran, `doctor` prints one blank line and runs a second check pass. It offers no fixes after the second pass.

Offers happen only when stdin and stdout are both TTYs. Otherwise `doctor` prints the report and exits, with no prompt and no fixer.

### I9. Fixers are safe

- A fixer never writes a secret value to any file. The model fixer stores only an env var name in `model.api_key_env`.
- The model fixer goes through the same validation as `config set`. Invalid input prints the loader's message and writes nothing.
- When no config file exists, the model fixer writes the default config plus the model section, after the same preview and `[y/N]`.
- A failed fixer (non-zero exit from `gh` or the editor, or invalid input) prints one line `fix failed: <title>` and `doctor` continues to the next offer.
- Ctrl-C during an offer or fixer stops `doctor` with exit 130 and no traceback. Writes already confirmed stay; nothing half-written remains (atomic writer).

### I10. `doctor` ends with a to-do list

After the last check pass, `doctor` prints one blank line, then:

- When no step is `fail`, `missing`, or `skip`: one line `All set.`
- Otherwise: a line `Still to do:`, then one line per such step, required steps first, each group in registry order:

  ```text
  <n>. <title> (required|optional) — <fix>
  ```

  `<n>` counts from 1. A `skip` step is listed with fix `fix "<title of the step it needs>" first`.

This list is the user's checklist of what is still to install or set up.

### I11. `init` points to `doctor`

After `init` writes the config, its last stdout line is exactly `Next: please-merge-my-pr doctor`. Prompts, their order, the preview, and the no-overwrite rule do not change.

### I12. README stays in step

`README.md` has a `## Setup` section. In it, in order: the line `uv tool install please-merge-my-pr`, then every registry step's `title`, in registry order. Each title appears verbatim.

### I13. Nothing else changes

All existing gates still pass. No existing command's output or exit code changes, other than I11's added line. Runtime dependencies stay at zero.

## Keeping it current

This plan's registry is the one record of user setup. Any later change that adds, changes, or removes something a user must do to run the tool:

1. adds, changes, or removes the registry step in `src/please_merge_my_pr/setup_steps.py`,
2. updates the README `## Setup` section,
3. states it in that feature's plan under `## Setup impact` (`none` is a valid answer).

The I12 gate fails when the registry and README drift apart. The rule itself is in `AGENTS.md` §9.

## Setup impact

Adds the `doctor` command and the registry. No new step the user must do.

## Decisions for the human

All four are answered. The human sets `Status: frozen` when ready.

- **D1. Install command in README.** Answered 2026-10-05: `uv tool install please-merge-my-pr`. The command works for users only after the human publishes the package to PyPI. On 2026-10-05 the name returned 404 on `https://pypi.org/pypi/please-merge-my-pr/json` (free). Publishing stays out of scope.
- **D2. Command name and job.** Answered 2026-10-05: the command is `doctor`. It reports, then offers fixes (I8).
- **D3. Network in `doctor`.** Answered 2026-10-05: no offline mode. `doctor` always runs every check, including GitHub requests.
- **D4. Auth errors.** Answered 2026-10-05: `doctor` describes each auth error by cause (I4 tables) and ends with a list of what is still to install or set up (I10). Existing command error messages stay as is (I13).

## File ownership

| File | Change |
|---|---|
| `src/please_merge_my_pr/setup_steps.py` | new: registry, step type, checks, fixers |
| `src/please_merge_my_pr/cli.py` | add `doctor` parser entry and dispatch |
| `src/please_merge_my_pr/onboarding.py` | I11 closing line only |
| `README.md` | `## Setup` section per I12 |
| `architecture/architecture.md` | Build updates the map |
| `tests/test_doctor.py` | new gates |

## Phases

### Phase 1 — Build the registry

Add `setup_steps.py` with the step type, the status type, the ordered registry (I1, I2), and the check functions with their cause tables (I4). Checks take config, env, an injectable GitHub transport, and an injectable `gh` runner, so gates can run them with no real network or `gh`.

### Phase 2 — Build `doctor`

Add the `doctor` command to `cli.py`. It loads config (falling back to defaults on error, I4), runs every check in order, prints per I3, prints the I10 to-do list, and exits per I3. Pass the existing injectable transport through, as other read commands do.

### Phase 3 — Build fixes

Add the four fixers and the offer loop (I8, I9). Fixers take an injectable subprocess runner and injectable input, so gates can run them with no real `gh`, editor, or terminal. Reuse the existing config validator, redacted TOML output, `config edit` flow, and atomic writer. Add the second check pass.

### Phase 4 — Point `init` to `doctor`

Add the I11 line after a successful write. Change nothing else in `init`.

### Phase 5 — README and map

Rewrite README `## Setup` per I12. Keep the clone + `uv sync` steps under a separate `## Development` heading. Update `architecture/architecture.md`.

## Planned gates

1. Registry ids include the nine I2 ids, in order, unique, with the stated `required` values.
2. With the fake GitHub, a valid token, model set, editor set: `doctor` exit 0, one line per step in registry order, shape per I3.
3. No token in env and `gh` absent: `github-auth` is `fail`, `github-access` and `notifications` are `skip`, exit 1, each non-`ok` line followed by a `fix:` line.
4. Token from env: detail is `via <ENV_NAME>`. Token from fake `gh`: detail is `via gh`.
5. Fake GitHub returns 401 on viewer: `github-access` is `fail`, exit 1, no traceback.
6. Network error on search: `github-access` is `fail`, exit 1, no traceback.
7. Notifications 403: `notifications` is `missing` and exit stays 0 when all required steps are `ok`.
8. No model section: `model` is `missing`, exit 0. `api_key_env` set but env empty: `model` is `fail`.
9. Invalid config file: `config` is `fail` with the loader's message, the other steps still print, exit 1.
10. Absent config file: `config` is `ok` with `using defaults`.
11. Unwritable state parent: `state-dir` is `fail`. After `doctor`, the state path does not exist.
12. Request count, no fix accepted: at most 3 GitHub requests, zero non-GET REST requests, zero GraphQL mutations, zero model requests.
13. Fake token and fake API key values do not appear in stdout or stderr.
14. Non-TTY run, and TTY run with every offer declined: `doctor` prints no `[y/N]` (non-TTY) or writes nothing (declined), creates no file under the isolated config and state roots, and starts no subprocess other than `gh auth token`.
15. `init` with `y`: last stdout line is `Next: please-merge-my-pr doctor`.
16. README `## Setup` contains `uv tool install please-merge-my-pr`, then every registry title in registry order.
17. Offers appear only for the I8 conditions, in registry order, one prompt each. A step with no fixer never prompts.
18. Answers `y`, `Y`, `yes` accept. `n`, empty, `sure`, and EOF decline and run no fixer.
19. `github-auth` accepted with fake `gh` on `PATH`: the runner receives exactly `gh auth login`. Without `gh` on `PATH`: no offer.
20. `notifications` accepted: the runner receives exactly `gh auth refresh -s notifications`. With token via env: no offer.
21. `model` accepted with valid input and `y` at the write prompt: config file has the model section, still loads, contains no secret value; a second check pass prints `model` as `ok`; exit code comes from the second pass.
22. `model` accepted with `y` then `n` at the write prompt: config file bytes unchanged (or still absent).
23. `model` accepted with an invalid base URL: loader message printed, nothing written, `fix failed: <title>` printed, next offer still shown.
24. A fixer that exits non-zero prints `fix failed: <title>` and `doctor` continues.
25. With one fixer run: exactly two check passes, at most 6 GitHub requests, zero model requests.
26. `github-auth` cause table: no env token and no `gh` on `PATH` → the first row's exact detail and fix; `gh` on `PATH` but `gh auth token` exits non-zero → the second row's exact detail and fix.
27. `github-access` cause table: fake GitHub returns 401, 403 with `X-RateLimit-Remaining: 0`, 403 without it, 404, a network error, a 500, and bad JSON → each row's exact detail and fix. The 401 fix differs for token via gh and via env.
28. To-do list: with every step `ok` the output ends with `All set.`; with one required `fail`, one optional `missing`, and one `skip`, the list has exactly 3 numbered lines, required first, each with `(required)` or `(optional)` and the step's fix.
29. The to-do list reflects the second check pass when a fixer ran: a step fixed by a fixer is not listed.

## Verification

After all phases are built, run every command. Do not stop after a failure.

```bash
uv run pytest -q
uv run mypy src
uv run ruff check .
uv run ruff format --check .
uv build
```

Known leftovers from chat (TRY004 at `src/please_merge_my_pr/onboarding.py:150`, `ruff format` on `src/please_merge_my_pr/tools.py`) will show in lint. Phase 3 edits `onboarding.py`; it does not fix TRY004 unless the human asks.
