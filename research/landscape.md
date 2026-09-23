# Landscape and constraints

Research from 2026-09-22. Checked from public pages only. Re-check before
relying on it.

## Similar tools

| Tool | What it does | Ranks a queue? | Open source? | Price |
|---|---|---|---|---|
| CodeRabbit Triage | Ranks open PRs P0–P3 with "deterministic" scores and shown evidence. Signals: blocking, dependencies, security, risk, effort, ownership. Web UI, Now/Next columns. Launched 2026-09-15, beta. | Yes | No (closed service) | Free on public repos (OSS offer includes triage). Private repos: Team plan and up, ~$48/dev/month annual. |
| PR Flow | Desktop app (macOS/Windows/Linux). One queue across GitHub, GitLab, Gerrit, Azure DevOps. Orders by whose turn it is, then state, open threads, age. AI optional, local-first. | Yes | No | Paid, one-time license after 14-day trial |
| Unblocked | AI code review comments on PRs, PR chat, risk-based auto-approve. Context engine over code, docs, Slack, issues. Funded ($20M Series A, 2025). | No | No | From $19/user/month |
| GitHub notifications | Newest first. | No | — | Free |

What we add over all of them: open code, runs locally, any model, PR text
can never move rank (tested), trust-weighted urgency with a learned track
record, replay proof against history, injection test results, egress log.

Sources:
- https://www.coderabbit.ai/blog/coderabbit-triage
- https://www.coderabbit.ai/oss
- https://www.coderabbit.ai/pricing
- https://prflow.app/pull-request-review-queue
- https://getunblocked.com/code-review/
- https://docs.getunblocked.com/code-review
- https://finance.yahoo.com/news/unblocked-raises-20m-ai-help-150000386.html

## Hackathon rules that shape the design

From https://nebiusglobalaihackathon.devpost.com/rules (read via a summarizing
fetch; read the original before relying on it).

- Must "make a runtime call to the Token Factory inference API", or run on
  Nebius AI Cloud (Serverless Jobs, Serverless Endpoints, DevPods).
- Must use at least one NVIDIA open source model (Nemotron counts).
- Other third-party APIs are allowed if used under their terms.
- Repo must be public with an open source license file (MIT, Apache 2.0, MPL 2.0).
- Entrants keep all IP. Sponsors get a non-exclusive license for judging.
- Judging, equal weight: Technological Implementation (effective use of
  Nebius/NVIDIA models), Design, Potential Impact, Quality of Idea (creative
  use of the specified technologies).
- Deadline: Thu Oct 30, 2026, 10:00 PDT. Video under 3 minutes.

Consequence: default model is Nemotron on Token Factory; bring-your-own model
is an extra, not a replacement.

## Name checks

| Name | PyPI | npm | Notes |
|---|---|---|---|
| `please-merge-my-pr` | free | free | Chosen. Command is the full name. |
| `queue` | free | — | Clashes with Python's built-in `queue` module |
| `cairn` | taken (2019 version tool) | taken | Many AI dev-tool repos named cairn, e.g. cairn-dev/cairn |
| `unblock` / `unblocked` | taken | taken | Unblocked is a funded company in the same space |

PyPI treats `-`, `_`, `.` as the same; `pleasemergemypr` is a different name.
Trademarks were not checked.
