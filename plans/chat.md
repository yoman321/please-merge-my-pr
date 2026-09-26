<!-- role: state change (human instruction) | model: claude-opus-5-5 | base: 251926649600f0750c78f760549e2c2a5e4f1e37 | date: 2026-09-25 -->
Status: frozen
Phases: 16

# Chat

## Goal

Make chat the default terminal interface for the PR queue.

The user can ask questions, change the view, and propose GitHub actions in plain words. Slash commands keep a direct, model-free path. The model may change saved scoring weights only after the user sees the exact effect and confirms it.

This file is the full build contract. Every build input and product choice is stated below.

## Current baseline

The repository already contains the Python package, SQLite store, GitHub read client, deterministic scorer, list and detail screens, and these commands:

```text
list  why  show  watch  init  config  label  merge  comment
approve  hide  snooze  open  rules  egress
```

Some commands are stubs. Three score signals are placeholders. There is no model client, write client, rule store, or chat loop yet. Every missing part needed by this plan is built in the phases below.

The package keeps zero runtime dependencies. Use the Python standard library and the installed project code.

## Out of scope

- A web UI, voice UI, or multi-user chat.
- Background model calls.
- Autonomous GitHub writes.
- AI-triggered `hide` or `snooze`.
- A replay service, hosted eval service, or remote trace service.
- Trust or credibility scores for people.
- Saving prompts, responses, diffs, titles, bodies, comments, or generated summaries.

## Terms

- **Direct command:** a normal CLI command, such as `please-merge-my-pr list`.
- **Slash command:** a chat line beginning with `/`.
- **Plain turn:** a chat line that does not begin with `/`.
- **Model request:** one outbound HTTP request to the configured OpenAI-compatible endpoint.
- **Tool call:** one structured request from the model to local code.
- **Move:** a session-only change to visible PR order.
- **Action:** a local or GitHub side effect.
- **Rule:** stored metadata that can remove a repeated tier-2 confirmation.
- **Content:** PR text, diffs, comments, user prompts, model responses, and summaries.

## Invariants

### C1. Slash commands do not enter the model loop

A slash line is parsed locally. The line, its arguments, and its result never enter the conversational model request. `/show` is code-only and does not call the summary model. Only the `show` tool, selected during a plain turn, may request a generated summary.

### C2. Direct and slash reads agree

`/list`, `/why`, and `/show` call the same code paths as `list`, `why`, and `show`. Given the same database and session overlay, their stdout is byte-for-byte equal.

### C3. Existing direct reads stay model-free

`list`, `why`, `show`, and `watch` make zero model requests.

### C4. Model tools are closed and bounded

The model receives only the tools in this table. A turn may execute at most eight tool calls and make at most eight model requests. Unknown tools fail with `tool rejected: unknown tool`. Malformed arguments fail with `tool rejected: invalid arguments`. A ninth tool call fails with `turn limit reached: tools`. Every tool result is recorded and sent to the next model request as structured tool output.

| Tool | Effect | Tier |
|---|---|---:|
| `list_queue(limit)` | Read ranked queue | read |
| `why(pr)` | Read score parts | read |
| `show(pr, summary)` | Read PR detail and optionally generate one summary | read |
| `move(pr, before, after, position, reason)` | Change session view order | view |
| `open(pr)` | Open the PR in a browser | 1 |
| `label(pr, add, remove)` | Edit labels | 2 |
| `merge(pr, method)` | Merge a PR | 3 |
| `comment(pr, body)` | Post a comment | 3 |
| `approve(pr, body)` | Submit approval | 3 |
| `set_weights(weights)` | Replace all saved score weights | 3 |

Every `pr`, `before`, and `after` reference is `owner/repository#<positive integer>`. `summary` is a boolean. `move` accepts exactly one placement: `position=top`, `position=bottom`, `before=<pr>`, or `after=<pr>`. Its `reason` is 1 through 200 Unicode characters. `limit` is an integer from 1 through 50. `method` is `merge`, `squash`, or `rebase`. `add` and `remove` contain at most 20 unique labels each, at least one list is non-empty, and the lists do not overlap. A label is 1 through 50 Unicode characters. A comment body is 1 through 10,000 Unicode characters. An approval body is optional and at most 10,000 Unicode characters.

Each conversational request uses `model.name`, `messages`, the ten tool schemas, `tool_choice: "auto"`, and `max_tokens: 1024`. Summary and repair requests use `model.name`, `messages`, and `max_tokens: 1024`, but advertise no tools and omit `tool_choice`. A valid conversational assistant message has either non-empty text or one or more OpenAI-style function tool calls. Tool-call IDs are preserved. Function arguments must be one JSON object. Each result returns as a `tool` role message with the matching ID and a JSON object body. A conversational response with neither text nor valid tool calls is invalid. A summary or repair response containing a tool call is invalid. All conversational, summary, and repair requests count toward the same eight-request turn limit.

### C5. Permission tiers are fixed

- Read and view work needs no prompt.
- Tier 1 includes `open`, `hide`, `unhide`, and `snooze`. It needs no prompt.
- Tier 2 includes label edits. It needs `[y/N]` unless an exact stored rule matches.
- Tier 3 includes merge, comment, approve, and saved weight changes. It always needs `[y/N]`.

### C6. Tier 3 is never delegated

No rule, flag, earlier answer, or model text can remove a tier-3 prompt. One confirmation permits one concrete action only.

### C7. Confirmation previews are complete

Each prompt names the repository, PR number, exact operation, and complete payload. Label previews show every added and removed label. Merge previews show the method. Comment and approval previews show the full body. Only `y` or `yes`, after trimming and case-folding, approves. Any other input, Ctrl-C, or EOF declines. Declining changes nothing and sends no write request.

### C8. Rules are explicit and narrow

Only the user can create or remove rules through direct or slash commands. A rule can approve one tier-2 label operation for an exact repository and exact label set. Rules never match tier 3. Model output cannot create, edit, or delete a rule.

### C9. Model destinations are strict

`model.base_url` must be HTTPS. Plain HTTP is allowed only when the parsed host is a literal address in `127.0.0.0/8` or is exactly `::1`. Hostnames such as `localhost`, redirects, URLs with user info, query strings, fragments, and other schemes are rejected before a request is sent. The client posts JSON to `<base_url>/chat/completions`. It sends `Authorization: Bearer <key>` only when `model.api_key_env` is set.

### C10. Code owns rank scores

The model never supplies, changes, or recomputes a PR score. Code computes the seven signals and the source-of-truth formula in C24. A score can change only when stored weights change, source PR data changes, or time changes a time-based signal. A move changes view order only.

### C11. Moves are small, visible, and temporary

At most three successful moves may occur in one user turn. A fourth fails with `turn limit reached: moves`. Moves never hide a PR. A moved primary row displays `[moved by AI]`. Its next line starts with `AI:` and contains the model reason. The reason is plain text, not a score. The complete overlay disappears when the process exits.

### C12. Undo is local

`/reset-view` clears all moves and model reasons without changing scores, saved weights, rules, hidden state, snoozes, or remote data.

### C13. Model words are marked

Every model-written explanation or summary starts with `AI:`. Code-computed scores, score parts, and action previews are never labeled as model output.

### C14. Every model request is visible

Before each request, stderr prints `calling model...`. The marker is written and flushed before opening the socket.

### C15. Only needed PR data leaves the machine

Tool output includes only fields needed for that tool. Queue rows may contain repository, number, title, author, state, labels, updated time, code-computed score parts, and code-computed score. Detail may also contain body, review state, CI state, changed-file names, additions, deletions, and a bounded diff. Untrusted fields are wrapped in fixed delimiters and described as data, never instructions.

### C16. Secrets never enter a model request

The model client scans the final serialized JSON bytes before opening a socket. It rejects the request if those bytes contain the exact non-empty GitHub token or any exact non-empty value read from an environment variable named by the config. The fixed error is `model request blocked: secret detected`. Logs and errors never print secret values.

### C17. Content is not stored

Content may live in process memory only. SQLite and files may store PR identifiers, timestamps, numeric scores, numeric weights, boolean state, rule metadata, model name, request counts, request byte counts, response byte counts, provider token counts, token-usage completeness, latency, and error classes. They may not store content. The config and its `.bak` file may contain non-secret settings and weights. API keys and GitHub tokens stay in environment variables.

### C18. Cost and loop limits are deterministic

- A user line is at most 16,384 UTF-8 bytes.
- `max_tokens` is 1,024 on every model request.
- The final serialized request body is at most 262,144 bytes.
- The response body is at most 1,048,576 bytes.
- One request has a 30-second socket timeout.
- Chat history receives at most 196,608 serialized bytes. Keep the system message and current user turn, then add the newest complete earlier turns that fit. Never split a tool call from its result.
- Each turn obeys the eight-request, eight-tool, and three-move limits.
- No model call occurs without a current user turn.
- Each request record contains request bytes, response bytes, latency, outcome, model name, and nullable provider input and output token counts. Missing provider `usage` is stored as null, never guessed.
- Each completed turn records request count and exact request-byte and response-byte totals. It records provider input-token and output-token totals only when every request in that turn supplied `usage`; otherwise both token totals are null and `token_usage_complete` is false.

Crossing a byte, request, or response limit stops that operation before another model request. The fixed errors are `user input too large`, `model request too large`, `model response too large`, and `turn limit reached: requests`.

### C19. Terminal output stays readable

All normal output fits within 80 visible columns. ANSI is off when stdout is not a TTY or `NO_COLOR` is present. Color is never the only meaning. Each PR has one primary row. AI text may use indented continuation lines.

### C20. Terminal input is safe

Ctrl-C cancels the current prompt or request without a traceback and returns to the prompt. Ctrl-D on an empty prompt exits cleanly. Pasted multi-line text is one user turn. Chat turns on bracketed paste by writing `\x1b[?2004h` to `/dev/tty` on entry and turns it off by writing `\x1b[?2004l` to `/dev/tty` on every exit. Neither sequence is written to stdout or stderr. If `/dev/tty` cannot be opened, chat runs without it. Escape sequences and control characters are removed before text is printed or inserted into a confirmation preview.

### C21. Model failure does not break direct use

A timeout, invalid JSON, bad tool call, HTTP error, missing key, or unavailable endpoint produces a short local error and leaves the chat usable. If `model.api_key_env` is configured but missing or empty, the client prints `model key not set: <NAME>` and makes zero network requests. Direct and slash commands still work.

### C22. Saved weight changes are exact and confirmed

`set_weights` must contain all seven keys exactly once: `urgency`, `blocks`, `risk`, `due_soon`, `age`, `diff`, and `ci`. Duplicate JSON keys are rejected while parsing. Each value is finite and from 0 through 100. At least one value is greater than zero. The preview shows the config path, every old and new raw value, every old and new normalized share, and the exact code-ranked top three rows before and after, ignoring the move overlay. If fewer than three rows exist, it shows all rows. Rank order uses displayed score descending, review-request time ascending, repository ascending, then PR number ascending. After `[y/N]`, an approval writes a sibling temporary file, flushes and fsyncs it, preserves the old file as `<config>.bak`, and atomically replaces the config. The parent directory is fsynced. A failure leaves the old config usable. The next queue read reloads weights, recomputes code scores, and reapplies the session move overlay.

### C23. Setup and config are complete

The config is TOML. It has these sections and values:

```toml
[github]
api_url = "https://api.github.com"
web_url = "https://github.com"
token_env = "GITHUB_TOKEN"
repos = ["owner/repo"]

[model]
base_url = "https://example.invalid/v1"
api_key_env = "MODEL_API_KEY"
name = "configured-model-id"

[weights]
urgency = 30.0
blocks = 25.0
risk = 15.0
due_soon = 10.0
age = 10.0
diff = 5.0
ci = 5.0

[scoring]
age_cap_days = 14.0
diff_cap_lines = 500.0
due_horizon_days = 14.0
blocked_people_cap = 3.0

[urgency_labels]
urgent = 1.0
high = 0.75
medium = 0.5
low = 0.25

[risk_paths]
auth = ["auth/**"]
billing = ["billing/**"]
migrations = ["migrations/**"]

[files]
lockfiles = ["**/uv.lock", "**/package-lock.json"]

[display]
limit = 3
```

`risk_paths` values and `files.lockfiles` are arrays of repository-relative glob strings. `display.limit` is an integer from 1 through 50. The model section is optional. Without it, a plain turn prints `model is not configured` and sends no request. `model.api_key_env` is also optional for a local endpoint. The default path is `$XDG_CONFIG_HOME/please-merge-my-pr/config.toml`, or `~/.config/please-merge-my-pr/config.toml` when `XDG_CONFIG_HOME` is unset.

The loader accepts the existing weight aliases `risk_paths`, `diff_size`, and `ci_state` as `risk`, `diff`, and `ci`. Canonical and alias names may not appear together. It also accepts existing top-level `repos` and `lockfiles`. Every write emits only the canonical schema above.

`init` asks for repositories, GitHub settings, and optional model settings. It writes a new file only after showing its destination and full redacted content and receiving `[y/N]`; it refuses to overwrite. `config show` prints redacted canonical TOML. `config path` prints the path. `config set <dotted-key> <TOML-literal>` parses the literal with `tomllib`, validates the full result, and atomically writes it. `config edit` opens `$EDITOR`, validates the edited temporary file, then uses the same atomic writer. Supported dotted keys are those shown in the schema, plus entries below `risk_paths`. Invalid config names the exact key and exits before network or database work. Config files never contain secret values.

Repository values must be unique `owner/repository` strings. GitHub URLs must be HTTPS base URLs with no user info, query, or fragment. Model URL rules follow C9. Environment-variable names must match `[A-Za-z_][A-Za-z0-9_]*`. Model name, when present, is non-empty. Weights follow C22. Scoring caps are finite and greater than zero. Urgency values are finite and in `[0, 1]`. Glob lists contain unique non-empty relative patterns. Unknown keys are errors.

### C24. All seven signals are real and normalized

- `urgency` is the highest case-folded exact label match in `urgency_labels`, or 0 when none match.
- `blocks` examines two structural sources. First, find same-repository issues whose GitHub `blocked_by` relationship includes this PR and count their assignees. Second, when this PR's head repository equals its base repository, find open PRs whose base branch equals this PR's head branch and count their authors and assignees. When the head is in another repository, this source makes no request and counts no one. Count distinct logins, exclude this PR's author, divide by `blocked_people_cap`, and clamp to 1.
- `risk` is 1 when any changed path matches `risk_paths`, otherwise 0.
- `due_soon` is 1 when the milestone due time has passed. Otherwise it is `1 - min(1, days_left / due_horizon_days)`. No milestone or no due time is 0.
- `age` is elapsed time since the current review request divided by `age_cap_days`, clamped to 1. PR creation time does not affect it.
- `diff` is additions plus deletions minus changed lines in files matching `files.lockfiles`, divided by `diff_cap_lines` and clamped to 1. The value cannot be negative.
- `ci` is 0 when CI is failing or the PR is not mergeable. It is 1 for passing, pending, or no CI when the PR is mergeable.

Every signal `s_i` is finite and clamped to `[0, 1]`. Every raw weight `w_i` is finite and non-negative. At least one weight is positive. The total weight is:

```text
T = urgency_weight + blocks_weight + risk_weight + due_soon_weight
    + age_weight + diff_weight + ci_weight
```

Each signal contributes:

```text
contribution_i = 100 * (w_i / T) * s_i
```

The source-of-truth exact score is the sum of all seven contributions:

```text
exact_score = 100 * sum(w_i * s_i) / T
```

With the default weights, this is:

```text
exact_score = 30*urgency + 25*blocks + 15*risk + 10*due_soon
              + 10*age + 5*diff + 5*ci
```

The displayed score is `floor(exact_score + 0.5)`. If a required read fails, that signal is `unavailable`, has value 0, and keeps its weight in `T`. If only one `blocks` source fails, `blocks` is unavailable rather than partially counted. Rank order uses the rule in C22. Every queue reason uses these code values. This formula is authoritative; research notes and model output cannot override it.

### C25. Direct actions are complete and support dry-run

`label`, `merge`, `comment`, `approve`, and `open` use the same action registry and payload builders as model tools. `hide`, `unhide`, and `snooze` are direct or slash only. `--dry-run` on a write action prints the complete sanitized HTTP method, URL path, and JSON body, then sends zero write requests and changes no local action state. GitHub writes use `github.api_url` only, disable redirects, send `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`, and treat non-2xx responses as failure. A failed write never reports success. `open` builds the browser URL from `github.web_url` and makes no GitHub API write.

GitHub payloads are fixed:

- Adds use `POST /repos/{owner}/{repo}/issues/{number}/labels` with `{"labels": [...]}`.
- Removes use one URL-encoded `DELETE /repos/{owner}/{repo}/issues/{number}/labels/{label}` per label.
- Merge uses `PUT /repos/{owner}/{repo}/pulls/{number}/merge` with `{"merge_method": method}`.
- Comment uses `POST /repos/{owner}/{repo}/issues/{number}/comments` with `{"body": body}`.
- Approval uses `POST /repos/{owner}/{repo}/pulls/{number}/reviews` with `{"event": "APPROVE"}` and includes `body` only when non-empty.

Label removals run in sorted order, followed by one sorted add request. The preview and dry-run show every request in that order. Execution stops at the first failure and reports which earlier requests succeeded. A prompt on non-TTY stdin declines. There is no `--yes` or other prompt bypass.

### C26. Generated summaries are bounded and strict

Only `show(summary=true)` may generate a summary. At most one summary sequence may start in one user turn. A later summary request returns `summary limit reached` without a model call. The diff builder sorts file names, excludes configured lockfiles, skips binary patches, and takes at most 65,536 UTF-8 bytes without cutting a character. The summary request asks for one JSON object with exactly `what_changed`, `files`, `risk_notes`, and `tests_changed`. Each value is a string of at most 1,000 characters. Invalid output gets one repair request if the turn budget allows; a second failure returns a local error. Summary content remains in memory and every displayed line begins with `AI:`.

### C27. Local state contains metadata only

SQLite stores hide state, snooze-until timestamps, and exact tier-2 rules by repository and label sets. Rule IDs are stable integer primary keys. It also stores the request metadata allowed by C17. It stores no reason text or other content. The default database path is `$XDG_STATE_HOME/please-merge-my-pr/state.sqlite3`, or `~/.local/state/please-merge-my-pr/state.sqlite3` when `XDG_STATE_HOME` is unset. `rules add`, `rules list`, and `rules rm` exist as direct and slash commands. Snooze times are RFC 3339 timestamps with an explicit offset and must be in the future. Snoozed items return after their timestamp. Hidden items return only after `unhide`. Filtering is applied before the move overlay.

### C28. Egress inspection is local and session-only

`/egress` shows the current session's model request metadata and redacted request fields from memory. It never makes a model request. The direct `egress` command prints that egress data is available only inside chat and exits with status 2. No remote tracing or local content log is added.

## Chat behavior

Running `please-merge-my-pr` with no subcommand starts chat only when stdin and stdout are TTYs. Otherwise it prints help and exits with status 2. Existing subcommands keep their current entry points.

The prompt is `queue> `. A plain turn sends one model request with the closed tool schema. The loop executes valid tool calls in response order, appends structured results, and asks the model again until it returns final text or reaches a limit. Final text is sanitized and printed with `AI:`.

Slash commands are:

```text
/list [limit]
/why <repo#number>
/show <repo#number>
/watch
/hide <repo#number>
/unhide <repo#number>
/snooze <repo#number> <RFC-3339 time>
/open <repo#number>
/label <repo#number> --add <label>... --remove <label>...
/merge <repo#number> --method <merge|squash|rebase>
/comment <repo#number> <body>
/approve <repo#number> [body]
/rules add <repo> --add <label>... --remove <label>...
/rules list
/rules rm <rule-id>
/reset-view
/egress
/help
/quit
```

Unknown slash commands print `unknown command: /<name>` and make zero model requests.

Direct action and rule commands use the same arguments without the leading slash. `unhide` is added as a direct command. `/watch` polls until Ctrl-C, then returns to `queue> `.

## File ownership

New modules:

- `src/please_merge_my_pr/chat.py` — prompt loop and slash dispatch.
- `src/please_merge_my_pr/model.py` — OpenAI-compatible HTTP client and budgets.
- `src/please_merge_my_pr/tools.py` — closed tool registry and schemas.
- `src/please_merge_my_pr/overlay.py` — session move state.
- `src/please_merge_my_pr/actions.py` — action tiers, previews, and payloads.
- `src/please_merge_my_pr/rules.py` — exact tier-2 rule and local-state metadata.
- `src/please_merge_my_pr/summarize.py` — strict summary parsing.
- `src/please_merge_my_pr/diffprep.py` — bounded diff construction.
- `src/please_merge_my_pr/github/write.py` — GitHub write requests.
- `src/please_merge_my_pr/onboarding.py` — init and config flows.

Existing modules changed:

- `src/please_merge_my_pr/cli.py` — default chat entry and complete commands.
- `src/please_merge_my_pr/config.py` — full schema, validation, and atomic writer.
- `src/please_merge_my_pr/events.py` — fields needed by signals, actions, and tools.
- `src/please_merge_my_pr/github/read.py` — dependencies, stacks, milestones, checks, and diffs.
- `src/please_merge_my_pr/github/http.py` — bounded reads and strict destinations.
- `src/please_merge_my_pr/scoring.py` — all seven signal formulas.
- `src/please_merge_my_pr/store.py` — metadata-only tables and queries.
- `src/please_merge_my_pr/ui.py` — move markers and AI continuation lines.

Tests mirror those modules. No module imports `chat.py` from the scorer, store, GitHub readers, or direct read commands.

## Follow-up decisions

Decided by the human on 2026-09-25 after the build review:

- Use the recommended fix in the last field of each `## Build review` finding. Phases 12 through 16 carry them out.
- The bracketed-paste switch goes to `/dev/tty`. C20 states this.
- The `blocks` stack source counts only same-repository heads. C24 states this.
- The plan stays `frozen` for this follow-up. It was not re-graded.

Finding to phase:

| Finding | Phase |
|---|---|
| `src/please_merge_my_pr/chat.py:103` | 12 (fix built; gates 34, 63) |
| `src/please_merge_my_pr/chat.py:329` | built (gate 35) |
| `src/please_merge_my_pr/config.py:353` | built (gates 40, 42) |
| `src/please_merge_my_pr/chat.py:301` | 13 |
| `src/please_merge_my_pr/tools.py:60` | 13 |
| `src/please_merge_my_pr/overlay.py:50` | 13 |
| `src/please_merge_my_pr/chat.py:407` | 13 |
| `src/please_merge_my_pr/chat.py:413` | 13 |
| `src/please_merge_my_pr/chat.py:169` | 13 |
| `src/please_merge_my_pr/model.py:62` | 14 |
| `src/please_merge_my_pr/github/http.py:64` | 14 |
| `src/please_merge_my_pr/cli.py:271` | 15 |
| `src/please_merge_my_pr/chat.py:467` | 15 |
| `src/please_merge_my_pr/onboarding.py:114` | 15 |
| `src/please_merge_my_pr/onboarding.py:77` | 15 |
| `src/please_merge_my_pr/actions.py:189` | 15 |
| `src/please_merge_my_pr/github/read.py:318` | 16 |
| `src/please_merge_my_pr/signals/age.py:19` | 16 |
| `architecture/architecture.md:30`, `:33`, `:47`, `:56` | 16 |

## Phases

### Phase 1 — Complete config and scoring

Extend the immutable config schema and validation. Add the atomic TOML writer. Preserve the existing weighted scorer and the built `risk`, `age`, `diff`, and `ci` formulas. Fetch and store the structured fields needed by `urgency`, `blocks`, and `due_soon`, then replace only those three placeholders with the C24 formulas. Keep rank and reason rendering code-owned.

### Phase 2 — Complete setup and config commands

Build `init`, `config show`, `config path`, `config set`, and `config edit`. Enforce preview, confirmation, no overwrite, redaction, validation, and no-secret rules.

### Phase 3 — Build action and local-state policy

Add the tier registry, canonical action objects, previews, exact rule matching, hide state, snooze state, and metadata-only SQLite migrations. Add direct and slash rule management.

### Phase 4 — Build GitHub writes and direct actions

Add write transport and exact label, merge, comment, and approval payloads. Complete direct `label`, `merge`, `comment`, `approve`, `open`, `hide`, and `snooze`. Add `--dry-run`. Do not add model code in this phase.

### Phase 5 — Build the model client and summarizer

Add destination validation, redirect blocking, secret scan, byte limits, timeouts, response limits, usage metadata, diff preparation, strict summary schema, and one bounded repair attempt.

### Phase 6 — Build the session overlay

Add stable top, bottom, before, and after moves. Enforce three successful moves per turn. Render move attribution and clear it with `/reset-view`. Apply saved score changes before reapplying the overlay.

### Phase 7 — Build the tool registry

Define the ten exact tools in C4. Validate every argument before dispatch. Return structured success and error results. Route reads, actions, summaries, and moves through their existing service code.

### Phase 8 — Build confirmations and saved weight edits

Apply the tier policy to direct, slash, and model actions. Build the full `set_weights` validator, before-and-after computation, preview, confirmation, backup, and atomic write. Rules may remove only exact tier-2 prompts.

### Phase 9 — Build the bounded turn loop and egress view

Add history pruning, request and tool limits, visible request markers, usage metadata, current-session egress memory, and failure recovery. Preserve complete tool call/result pairs.

### Phase 10 — Build slash dispatch

Map every slash command locally. Prove slash input never reaches the model loop. Keep `/show` code-only. Add safe control handling, multi-line paste handling, help, and quit.

### Phase 11 — Make chat the default interface

Wire no-subcommand TTY entry into `cli.py`. Keep non-TTY help behavior. Finish 80-column rendering, ANSI rules, AI labels, and end-to-end command parity.

### Phase 12 — Finish the paste switch

Keep the built paste joining. Write the C20 on and off sequences to `/dev/tty` inside a `with` block, so `ruff check` passes. Turn the switch off on every exit path: `/quit`, Ctrl-D, and an error. Run chat without the switch when `/dev/tty` cannot be opened.

### Phase 13 — Harden turn history and tools

After Ctrl-C during a tool dispatch, never leave a tool call in history without its result: add an error result for each unanswered call. Emit JSON-schema types, required keys, enums, and bounds for every tool from the C4 table. Reject a `move` whose `before` or `after` equals `pr`. Return an error result when the target is hidden, snoozed, or not in the queue, and do not count it as a move. Send the `review_state` read from GitHub, or omit the field. Wrap changed-file paths in the same fixed delimiters as title and body. Delete the dead branch in slash handling.

### Phase 14 — Tighten egress bounds

Scan every request for the exact token that `auth.token(config)` returns, including a token from `gh auth token` or a stripped env value, plus the raw env values from C16. Read at most 1,048,577 response bytes before applying the C18 response limit.

### Phase 15 — Fix direct commands and config

Apply the move overlay to all ranked entries before cutting `/list` to its limit. Print each weight-preview row as `#<n> <reason>   [score <s>]` and wrap every preview line to 80 columns. Check `config set` keys against the fixed C23 schema plus `risk_paths.*`, not against keys already in the file. In `init`, catch `ValueError`, print it, and exit 2. For `open`, append the URL when `BROWSER` has no `%s`, and turn a missing browser command into a short error.

### Phase 16 — Fix signals, reads, and the map

Apply the C24 same-repository rule to the stack source. Restore fractional seconds in the `age` formula. Update `architecture/architecture.md`: add `summary.py`; move URL checks to the `config.py` block and redirect blocking to the `github/http.py` block; list each module's dependencies; mark `ui/theme.py` as unused if nothing imports it.

## Planned gates

1. A slash command executes with zero conversational and summary model requests.
2. `/show` executes with zero model requests.
3. Direct and slash `list`, `why`, and `show` outputs are byte-equal.
4. Direct `list`, `why`, `show`, and `watch` make zero model requests.
5. Conversational requests advertise exactly the ten C4 tools; summary and repair requests advertise none.
6. Unknown tools, malformed arguments, and the ninth tool call fail without dispatch.
7. Tool-call IDs and every structured result are present in the next request.
8. Tool bounds reject out-of-range limits, labels, bodies, methods, and move shapes.
9. The action registry assigns the exact tiers in C5.
10. Every tier-3 attempt prompts once, including after a prior approval.
11. Decline and EOF send no write and make no local action change.
12. Confirmation previews contain the exact target and complete payload.
13. Rules match only exact repository and label sets, and never tier 3.
14. Model output cannot add, edit, or remove a rule.
15. Destination checks accept HTTPS and literal loopback HTTP only.
16. Redirects and forbidden hosts are rejected before payload resend.
17. Rank scores come only from the seven code signals and saved weights.
18. One turn permits three successful moves and rejects the fourth.
19. A move changes view order without changing score or hiding a PR.
20. `/reset-view` restores code order and leaves saved state unchanged.
21. Every model-written line begins with `AI:` and code values do not.
22. `calling model...` is flushed before every socket open.
23. Tool payloads omit fields that are not needed by that tool.
24. Untrusted content is delimited and cannot add a tool or instruction.
25. A seeded GitHub token or configured environment value blocks the request.
26. Logs and errors never contain seeded secret values.
27. Content never appears in SQLite, config, backup, or metric records.
28. User, request, response, history, tool, request-count, and move limits hold at exact boundaries.
29. History pruning keeps the system and current turn and never splits a tool pair.
30. No idle or post-turn background model request occurs.
31. Request and turn records contain exact byte totals; provider token totals are exact only when `token_usage_complete` is true and are null otherwise.
32. TTY, piped, and `NO_COLOR` output stays within 80 visible columns.
33. Meaning remains clear with ANSI removed.
34. Ctrl-C, Ctrl-D, pasted lines, escape sequences, and control characters follow C20.
35. Missing keys and each model failure class leave direct and slash reads usable.
36. A missing configured key prints the exact error and opens no socket.
37. Weight input requires exactly seven unique finite values in range and a positive sum.
38. The weight preview shows every raw value, share, top-three result, and config path.
39. Weight decline and failed write preserve bytes of the live config.
40. Weight approval creates a backup, atomically replaces config, recomputes scores, and preserves moves.
41. `init` previews once, requires `[y/N]`, and refuses overwrite.
42. Each config command validates, redacts, and writes atomically as required.
43. Invalid config fails before database or network access and names its key.
44. Legacy config aliases load, mixed aliases fail, and the next write emits canonical keys.
45. The built `risk`, `age`, `diff`, and `ci` formulas remain unchanged, and the three new signals match C24 at zero, boundary, cap, and over-cap cases.
46. Signal outputs are finite and in `[0, 1]`; every contribution, unavailable read, exact score, displayed score, and rescaled weight set follows the source-of-truth C24 formula.
47. Direct and tool actions build the exact C25 methods, paths, headers, and bodies.
48. `--dry-run` prints every sanitized request in execution order and sends zero writes.
49. A partial label failure reports completed requests and never prints full success.
50. Other non-2xx GitHub writes fail and never print success.
51. Summary diff order and the 65,536-byte boundary are deterministic.
52. Summary schema rejects tool calls, missing fields, extra fields, wrong types, and overlong fields.
53. One bad summary gets at most one repair request, within the turn cap.
54. A second summary request in one turn makes no model call.
55. Hide, unhide, snooze expiry, and filtering-before-overlay behave exactly as C27.
56. Rule, local-state, and model-metric rows contain only fields allowed by C17.
57. `/egress` makes zero requests and shows only current-session redacted data.
58. Direct `egress` exits 2 with the fixed chat-only message.
59. No-subcommand starts chat only with TTY stdin and stdout.
60. Non-TTY no-subcommand prints help and exits 2.
61. Import direction keeps chat out of scorer, store, readers, and direct read commands.
62. A package-tree test fails if an undeclared subcommand, tool, or runtime dependency appears.
63. Chat writes `\x1b[?2004h` to `/dev/tty` on entry and `\x1b[?2004l` on `/quit`, Ctrl-D, and error exit; stdout and stderr contain neither; chat starts and joins pastes when `/dev/tty` cannot be opened.
64. After Ctrl-C during a tool dispatch, every assistant tool-call ID in the next model request has exactly one matching `tool` result.
65. Every tool schema declares the C4 types, required keys, and enums, and bounds equal to C4: `limit` 1–50, `reason` 1–200 characters, labels 1–50 characters with at most 20 per list, bodies at most 10,000 characters, and `weights` with exactly the seven keys from 0 through 100.
66. A `move` targeting itself fails with `tool rejected: invalid arguments`; a move targeting a hidden, snoozed, or unknown PR returns an error result; neither changes order or uses one of the three moves.
67. `show` detail omits `review_state` or sends the value GitHub returned, and every changed-file path is inside the untrusted-data delimiters.
68. A request containing the token from `gh auth token`, or the stripped token env value, fails with `model request blocked: secret detected` and opens no socket.
69. A response body over 1,048,576 bytes fails with `model response too large` after reading at most 1,048,577 bytes.
70. After a PR ranked below `display.limit` is moved to `top`, `/list` shows it first with `[moved by AI]`, matching the `list_queue` tool order.
71. The weight preview prints each before and after row as `#<n> <reason>   [score <s>]` with the code score, and every line fits 80 columns with a 200-character config path.
72. `config set model.base_url`, `model.name`, and `model.api_key_env` succeed when the model section is absent; unknown keys still fail and name the key.
73. `init` with repository `acme` or a blank model name prints `invalid config: <key>`, exits 2, prints no traceback, and writes no file.
74. `open` with `BROWSER` set to a command without `%s` runs it with the PR URL as the last argument; a missing browser command prints a short error, no traceback, and no success message.
75. For a PR whose head repository differs from its base repository, the stack source sends no request and counts zero people, and `blocks` is not `unavailable` for that reason.
76. A review request 0.5 seconds old gives `age = 0.5 / (age_cap_days * 86400)`, not 0.

## Verification

After all phases are built, run every command. Do not stop after a failure.

```bash
uv run pytest -q
uv run mypy src
uv run ruff check .
uv run ruff format --check .
uv build
```

## Deployment input

The model endpoint is operator config, not a build choice. The build does not hardcode a provider or model. All required gates use a local fake OpenAI-compatible endpoint. A live paid-provider check is optional and is not required to complete this plan.

## Plan review

The findings below keep their human-controlled states. References to deleted files are historical evidence only. They are not build inputs. The body above is the complete contract.

- [rejected] high — PLAN.md:79 — the frozen CLI plan says the product must remain deterministic and make no model calls, while this plan makes chat and outbound model calls the default interface — the human must explicitly replace or narrow the frozen CLI decision before this plan can freeze
- [rejected] high — plans/queue-skeleton.md:98 — invariant I12 forbids the model from changing scores or ordering, while `move` changes queue order — define a session-only view-order overlay owned by UI code, preserve code scores, cap moves, and show explicit model attribution
- [rejected] high — plans/queue-actions.md:112 — invariant A5 says rules never auto-confirm tier 3, while this plan says a policy may remove any write confirmation — restrict policy-based confirmation removal to the tiers the action plan permits
- [rejected] high — plans/summaries.md:88 — the summary plan limits the model to summaries, but this plan adds conversation, planning, and tool choice — the human must supersede that model-use boundary or narrow chat to deterministic intent parsing
- [rejected] med — plans/cli-design.md:51 — the CLI plan requires one line per PR, while AI reasons add extra queue lines — define a compatible continuation-line format or move reasons into `/why`
- [accepted] med — plans/chat.md:55 — `move` has no per-turn or per-session limit, so repeated tool calls can arbitrarily rewrite the visible queue — cap successful moves per turn and provide `/reset-view`
- [accepted] med — plans/chat.md:126 — the plan does not forbid calls after the user turn, so the client can make invisible background requests despite the stated no-background intent — require zero model calls without an active user turn and test after idle time
- [accepted] med — plans/chat.md:114 — "session state" is not defined, so prompts and model output may be written to SQLite or traces — list permitted persisted fields and state that raw user text, model text, and tool payloads stay in memory only
- [accepted] med — plans/chat.md:75 — Tier 2 confirmation removal depends on "a specific rule" but no exact match keys or precedence exist — define the minimum rule fields and require exact matching before implementation
- [accepted] med — plans/chat.md:120 — the build order uses modules from absent work (`actions.py`, `model.py`, `summarize.py`) without making those frozen prerequisites — freeze and build the dependency plans first, or absorb the required contracts and phases into this plan
- [rejected] med — PLAN.md:36 — Week 3 makes chat depend on stable queue metrics and replay results, but the plan has no entry gate for those results — name the required metric report and passing thresholds before Phase 1
- [rejected] med — plans/chat.md:45 — "Nemotron Nano 9B v2 or any OpenAI-compatible endpoint" does not name an exact model identifier or a tested tool-calling contract — set the exact model ID and add one compatibility gate for multi-step tool calls
- [accepted] med — plans/chat.md:61 — AI-triggered `hide` and `snooze` are Tier 1 side effects with no confirmation, and `hide` can silently remove work from the queue — remove them from model tools for v1, or require a visible preview plus confirmation
- [accepted] med — plans/chat.md:33 — tool bounds are incomplete for labels, arrays, and comment bodies, so a model can create oversized requests or ambiguous empty actions — set exact item, character, and enum limits for every tool field
- [accepted] med — plans/chat.md:48 — allowing plain HTTP for an arbitrary configured local endpoint can send PR content or credentials over the network — require HTTPS except for loopback hosts and reject non-loopback HTTP before sending
- [rejected] high — plans/chat.md:16 — the requirement that slash commands never enter an LLM loop conflicts with `/show` sharing the CLI path because `show` uses `NullSummarizer` today but the summaries plan makes that path model-backed — split deterministic `/show` from AI summary generation or narrow C1 to the conversational loop and state the model call explicitly
- [accepted] med — plans/chat.md:67 — the plan caps tool calls but not user input, retained history, model output, or total tokens, so a long chat can exceed the local model context or create unbounded cost — define byte/token limits, deterministic history pruning, and an output-token cap
- [accepted] med — plans/chat.md:103 — C8 requires users to create confirmation rules through slash commands, but the slash registry has only `/rules` read output and no add/remove grammar — define explicit rule add/remove commands or remove chat rule management from C8
- [accepted] high — plans/chat.md:83 — `localhost` is accepted as a safe HTTP destination without resolving and pinning its addresses, so DNS or host mapping can route PR content off-box — allow plain HTTP only for literal loopback IPs or validate every resolved address and connect to that pinned result
- [accepted] med — plans/chat.md:181 — a configured but missing `api_key_env` has no specified behavior, so the client may send an unauthenticated request or fail unclearly — require a fixed local error and zero network calls when the named variable is absent or empty
- [accepted] high — plans/chat.md:153 — the egress gate checks only a GitHub token fixture and does not require inspection of the final serialized request, so other environment secrets can leak through prompts, tool results, or headers — scan the exact outbound bytes for every configured secret and keep the no-egress assertion at the HTTP boundary
- [accepted] med — plans/chat.md:126 — observability records request count and latency but omits input and output token usage, so cost regressions cannot be measured — record exact per-request input and output token counts and totals per user turn
- [rejected] high — plans/chat.md:111 — `set_weights` lets the model change ranking scores, which conflicts with queue-skeleton I4 unless the human explicitly approves this new path — state that confirmed user-approved weights are the only model-proposed score change and remove the older blanket ban before freeze
- [rejected] high — plans/onboarding.md:67 — onboarding invariant O5 allows only setup fields to be changed, while `set_weights` writes seven scoring fields — extend the allowed config writer and its atomic-write gates to the weight keys before freeze

## Build review

- [accepted] high — src/please_merge_my_pr/chat.py:103 — a real TTY `readline` returns one line per call, bracketed paste is never turned on (`\x1b[?2004h` is written nowhere), and `clean()` strips ESC before the paste check at :104, so a pasted multi-line block becomes one model turn per line; gate 34 passes only because the harness `FakeIn.readline` returns the whole paste at once — breaks C20 — write `\x1b[?2004h` on chat entry and `\x1b[?2004l` on exit, read until `\x1b[201~` before calling `clean()`
- [accepted] high — src/please_merge_my_pr/chat.py:329 — `dispatch` does not catch `GitHubError` or `AuthError` from `candidates`/`token` (:329, :352, :380, :450) or `OSError` from `open_pr` (:377), and `turn` (:273) and `loop` (:117) catch only `KeyboardInterrupt`, so one GitHub outage during a tool call ends chat with a traceback; probe with a transport raising `ConnectionError` printed `turn raised: GitHubError could not discover GitHub review requests` — breaks C21 — catch these in `dispatch` and return `{"error": <short message>}` as the tool result
- [accepted] high — src/please_merge_my_pr/config.py:353 — `to_toml` writes `urgency_labels` and `risk_paths` keys unquoted (also onboarding.py:167 `_raw_toml`), so a valid label such as `"priority: high"` serializes to `priority: high = 1.0`; probe reload gave `invalid TOML: Expected '=' after a key`; an approved `set_weights` then replaces the live config with unreadable text and `load_config` at chat.py:478 raises — breaks C22 "a failure leaves the old config usable" and C23 canonical writes — emit keys with `json.dumps`, and parse the text with `config_from_text` before `atomic_write`
- [accepted] med — src/please_merge_my_pr/model.py:62 — the secret scan reads only the env var named by `github.token_env`, but the GitHub token in use may come from `gh auth token` (github/auth.py:20) or be a stripped env value (github/auth.py:16), and those exact bytes are never scanned — breaks C16 when the user signs in with `gh` or the env value has whitespace — scan the stripped value that `auth.token(config)` returns, plus the raw env values
- [accepted] med — src/please_merge_my_pr/chat.py:301 — Ctrl-C during a tool dispatch returns from `turn` (:274) and the `finally` still appends `current`, leaving an assistant `tool_calls` message with no matching `tool` results in history; every later request carries that unpaired call, which OpenAI-compatible servers reject — breaks C18 "never split a tool call from its result" — before appending, drop a trailing assistant message whose calls lack results, or add an error result for each
- [accepted] med — src/please_merge_my_pr/cli.py:271 — `/list` applies the overlay only to rows already inside the top `limit` rank groups, while the `list_queue` tool applies it before slicing (chat.py:331); moving a PR ranked below the limit to `top` shows in the tool result but never on `/list` — breaks C11 "moves are visible" for any PR below the display limit — apply the overlay to all ranked entries, then cut to the limit
- [accepted] med — src/please_merge_my_pr/chat.py:467 — the weight preview prints only `repo#number` for the before and after top three, not the code rows with score and reason, and the `Save weights to`, `before:`, and `after:` lines are not wrapped — breaks C22 "exact code-ranked top three rows" and C19 80 columns with long paths or repo names — print each row as `#<n> <reason>   [score <s>]` through `wrapped`
- [accepted] med — src/please_merge_my_pr/onboarding.py:114 — `config set` rejects any key not already in the current canonical text, so `model.base_url`, `model.name`, and `model.api_key_env` cannot be set when the model section or key is absent — breaks C23 "supported dotted keys are those shown in the schema" — check keys against the fixed schema key list plus `risk_paths.*`
- [accepted] med — src/please_merge_my_pr/onboarding.py:77 — `run_init` validates through `config_from_text`, whose `ValueError` neither `run_init` nor `cli.main` (cli.py:126) catches, so input like repo `acme` or a blank model name ends in a traceback — breaks C23 "invalid config names the exact key and exits" — catch `ValueError`, print it, return 2
- [accepted] med — src/please_merge_my_pr/actions.py:189 — when `BROWSER` is a plain command without `%s` (the usual form, e.g. `firefox`), the URL is never passed, so `open` starts the browser without the PR; a missing command raises `FileNotFoundError` uncaught — breaks C25 `open` under that condition — append the URL when `%s` is absent and catch `OSError`
- [accepted] med — src/please_merge_my_pr/github/read.py:318 — the stack query matches open PRs whose base equals this PR's `head_ref` in the base repo even when the head branch lives in a fork, so a fork PR from branch `main` counts every author and assignee of PRs into `main` — follows C24 wording literally; plan gap — also require the head repository to equal the base repository before running the stack query
- [accepted] low — src/please_merge_my_pr/github/http.py:64 — `response.read()` reads the whole body before model.py:83 checks the 1,048,576-byte limit, so a hostile endpoint can stream an unbounded body into memory; the plan's file ownership lists http.py for "bounded reads" but http.py is unchanged — read at most `RESPONSE_LIMIT + 1` bytes
- [accepted] low — src/please_merge_my_pr/tools.py:60 — every tool property schema is `{}`, with no type, enum, bound, or description, so the model is never told the `owner/repository#n` format, the `method` values, or the `weights` shape — raises invalid-argument rates and wasted requests — emit JSON-schema types, enums, and limits from the C4 table
- [accepted] low — src/please_merge_my_pr/overlay.py:50 — a `before`/`after` target that equals `pr` or is not in the list (hidden, snoozed, unknown) sends the PR to the bottom, and chat.py:375 still counts it as a successful move — surprising order change and a spent move — reject self-reference in `tools.valid` and return an error when the target is absent
- [accepted] low — src/please_merge_my_pr/chat.py:407 — `review_state` is the constant `"requested"`, not read from GitHub — the detail payload states a fact code never checked (C15) — use the read review state or omit the field
- [accepted] low — src/please_merge_my_pr/chat.py:413 — changed-file `path` values go to the model unwrapped while title and body are wrapped — file names are author-controlled text (C15 "untrusted fields are wrapped") — wrap paths with `_data`
- [accepted] low — src/please_merge_my_pr/signals/age.py:19 — the build changed the built `age` formula to truncate elapsed time to whole seconds; Phase 1 says preserve the built `age` formula — restore float seconds
- [accepted] low — src/please_merge_my_pr/chat.py:169 — `if code and command not in {...}: return False` is followed by `return False`, a dead branch — cost, clarity — delete it
- [accepted] low — architecture/architecture.md:30 — `src/please_merge_my_pr/summary.py` (`NullSummarizer`, imported by nothing) is on disk but missing from Modules — map drift — add a line for it
- [accepted] low — architecture/architecture.md:47 — the `model.py` block claims destination and redirect controls, but C9 checks live in `config._base_url` (config.py:130) and redirect blocking in `github/http.py:38`; the `config.py` block does not mention URL checks — map drift — move each claim to the module that does it
- [accepted] low — architecture/architecture.md:33 — many Modules blocks omit "what it depends on" (`model`, `tools`, `overlay`, `diffprep`, `summarize`, `text`, `github/*`, `store`, `ingest/poll`, `ui/*`), and the `chat.py` list omits `config`, `scoring`, `text`, `events`, `github.auth`, `github.http`, `github.read` — §4 shape requires dependencies per block — list them
- [accepted] low — architecture/architecture.md:56 — `ui/theme.py` is described as a live color helper, but no module imports it, so no output is ever colored — map drift — say it is unused
