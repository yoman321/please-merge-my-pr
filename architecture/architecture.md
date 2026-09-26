# Architecture
<!-- role: Build | model: gpt-5 | base: 251926649600f0750c78f760549e2c2a5e4f1e37 | date: 2026-09-25 -->

## Purpose
`please-merge-my-pr` is a terminal CLI for one developer. It ranks GitHub pull requests, supports direct and slash commands, and has an optional model-backed chat loop.
GitHub writes and saved scoring changes need the confirmation policy defined in code.

## Layout
```
AGENTS.md                  agent rules
README.md                  setup, entry commands, environment names, checks
handoff.md                 current session state
LICENSE
pyproject.toml             package metadata, console script, dev tools
uv.lock                    locked dev dependencies; no runtime dependencies
architecture/              this repository map
plans/                     chat.md, the frozen build contract
research/                  product research notes
src/please_merge_my_pr/    application package
  github/                  GitHub read, write, auth, and HTTP adapters
  ingest/                  notification polling
  signals/                 seven score signals and registry
  ui/                      terminal screen and color helpers
  demo/                    packaged offline data
tests/                     old gates and chat gates
  fixtures/                recorded GitHub payloads
dist/                      source and wheel build output
```

## Modules
- `src/please_merge_my_pr/__main__.py` — runs `cli.main` — entry: module execution — depends on `cli`
- `src/please_merge_my_pr/cli.py` — declares direct commands, lazily starts chat, loads candidates, renders reads, executes actions, and manages local state — entry: `main` — depends on `config`, `actions`, `github.*`, `queue`, `scoring`, `store`, `ui.screens`
- `src/please_merge_my_pr/chat.py` — owns `/dev/tty` bracketed-paste mode, slash dispatch, paired tool history after interrupts, bounded turns, queue-checked moves, delimited detail data, summaries, wrapped weight previews, egress memory, and session overlay — entry: `run` — depends on `actions`, `cli`, `config`, `diffprep`, `events`, `github.auth`, `github.http`, `github.read`, `model`, `overlay`, `scoring`, `summarize`, `text`, `tools`, and the standard library
- `src/please_merge_my_pr/config.py` — immutable canonical config, URL and schema validation, partial optional model settings, legacy aliases, quoted TOML output, and atomic writes — entries: `load_config`, `config_from_text`, `to_toml`, `atomic_write` — depends on the standard library
- `src/please_merge_my_pr/onboarding.py` — `init` and `config show|path|set|edit`, including staged model keys and quoted TOML key serialization — entries: `run_init`, `run_config` — depends on `config`, the configured editor, and the standard library
- `src/please_merge_my_pr/events.py` — GitHub value objects, including milestone, patch, and blocked-person data — depends on the standard library
- `src/please_merge_my_pr/queue.py` — deterministic queue eligibility — entry: `eligible` — depends on `events`
- `src/please_merge_my_pr/scoring.py` — normalized seven-signal score and deterministic rank — entries: `score`, `rank` — depends on `config`, `events`, `signals`
- `src/please_merge_my_pr/signals/` — urgency, blocking people, risk path, due date, fractional review-request age, non-lockfile diff, and CI formulas — entry: `registry` in `signals/__init__.py` — depends on `config`, `events`
- `src/please_merge_my_pr/actions.py` — action tiers, PR parsing, canonical GitHub requests, previews, confirmation, execution, and error-safe browser commands with the PR URL — depends on `config`, `github.http`, `github.write`, `store`
- `src/please_merge_my_pr/github/http.py` — injectable, redirect-blocking urllib transport with bounded response reads — entry: `UrllibTransport.send` — depends on the standard library
- `src/please_merge_my_pr/github/auth.py` — GitHub token lookup from an environment variable or `gh auth token` — entry: `token` — depends on `config`, `gh`, and the standard library
- `src/please_merge_my_pr/github/read.py` — candidate discovery plus PR, file, review, CI, dependency, and same-repository stack reads — entries: `read_candidates`, `read_candidate` — depends on `config`, `events`, `github.http`, and the standard library
- `src/please_merge_my_pr/github/write.py` — turns a transport response into write success or failure — entry: `send` — depends on `github.http` and the standard library
- `src/please_merge_my_pr/store.py` — SQLite polling, seen, rule, hide, snooze, model-call, and model-turn metadata — entry: `Store` — depends on SQLite and the standard library
- `src/please_merge_my_pr/rules.py` — exact label-rule add and list helpers — depends on `store`
- `src/please_merge_my_pr/model.py` — OpenAI-compatible client with secret, byte, timeout, and metric controls — entry: `Client.request` — depends on `config`, `github.http`, `store`, and the standard library
- `src/please_merge_my_pr/tools.py` — the ten model tool schemas and strict JSON argument validation — entries: `schemas`, `parse_arguments`, `valid` — depends on `config` and the standard library
- `src/please_merge_my_pr/overlay.py` — process-only top, bottom, before, and after moves — entry: `Overlay` — depends on the standard library
- `src/please_merge_my_pr/diffprep.py` — sorted, lockfile-free, binary-free, UTF-8-safe bounded diff text — entry: `build` — depends on `events` and the standard library
- `src/please_merge_my_pr/summarize.py` — summary prompts, repair prompts, and exact response validation — entries: `messages`, `repair_messages`, `parse` — depends on the standard library
- `src/please_merge_my_pr/summary.py` — unused legacy `NullSummarizer` and summarizer protocol — entries: `Summarizer`, `NullSummarizer` — depends on `events` and the standard library
- `src/please_merge_my_pr/text.py` — control removal and 80-column wrapping — entries: `clean`, `wrapped`, `ai_lines` — depends on the standard library
- `src/please_merge_my_pr/ingest/poll.py` — conditional GitHub notification polling and scored watch items — entry: `Poller.poll_once` — depends on `config`, `events`, `github.http`, `github.read`, `queue`, `scoring`, `store`, and the standard library
- `src/please_merge_my_pr/demo_data.py` — packaged offline candidates — entry: `load_demo` — depends on packaged JSON, `events`, `github.read`, and the standard library
- `src/please_merge_my_pr/ui/screens.py` — wrapped list, why, show, and watch text — depends on `scoring`, `text`
- `src/please_merge_my_pr/ui/theme.py` — unused optional ANSI color helper — entry: `color` — depends on the standard library

## Data flow
- Direct read → `cli.main` → validated config → GitHub or demo candidates → eligibility → seven-signal score → local hide/snooze filter → rank → screen or JSON.
- Direct action → `cli.main` → canonical action requests → preview → rule or user confirmation → injected GitHub transport → result.
- Chat input → `/dev/tty` bracketed-paste mode → `chat.Session` joins and cleans one turn → bounded model request → validated tool calls → shared read/action/state services → structured result or local error → final `AI:` output.
- Slash line → `chat.Session.slash` → local direct service path → terminal output, with no model request.
- Summary tool → PR file patches → `diffprep.build` → summary request → strict parse → one optional repair → structured tool result.
- Saved weights → code-ranked before/after preview → confirmation → quoted TOML serialization and validation → backup and atomic config write → config reload → score recompute → overlay reapply.
- Model call → final JSON secret scan → visible marker → HTTP request → metadata-only SQLite call row → metadata-only turn row.
- Hide, snooze, and rules → `Store` SQLite rows → filtering or exact tier-two prompt removal.

## External
- GitHub REST
- GitHub GraphQL
- OpenAI-compatible `/chat/completions`
- `gh` CLI
- configured editor from `VISUAL` or `EDITOR`
- configured browser from `BROWSER`
- controlling terminal `/dev/tty`
- SQLite
- env vars: `GITHUB_TOKEN`, configured `github.token_env`, configured `model.api_key_env`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `HOME`, `NO_COLOR`, `BROWSER`, `EDITOR`, `VISUAL`

## Features
- chat — `plans/chat.md` — `src/please_merge_my_pr/{chat,model,tools,actions,overlay,rules,summarize,diffprep,onboarding,config,cli,store,text}.py`, `src/please_merge_my_pr/github/{read,write}.py`, `src/please_merge_my_pr/signals/`, `src/please_merge_my_pr/ui/screens.py`
