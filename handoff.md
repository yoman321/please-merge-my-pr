# Handoff
<!-- role: Plan | model: claude-opus-5-5 | base: 7565d0375cb1a70ce771aea854bf06d4e16a74d4 | date: 2026-09-23 -->

Feature:  weights-research        Plan: plans/weights-research.md    Status: draft
Phase:    0 of 5 — closed by the human; phases 1–5 were not run as written

State:    Research ran in chat. The human decided the signal directions and closed the plan
          (see its § Closed). No default weights, curves, caps, or rounding rule were set, and
          `research/weights.md` was not written. PLAN.md now describes the new ranking.
Next:     Human answers open questions 5–9 in plans/weights-research.md and sets its final Status.
Blocked:  `queue-skeleton` phase 3 needs default weight numbers and curves; none exist yet.
          `queue-skeleton`, `onboarding`, and `queue-signals` still conflict with this plan (its
          § Plan review and open questions 2–4). Each needs its own Plan session.
          `research/landscape.md` still claims "trust-weighted urgency with a learned track record";
          B7 dropped that. PLAN.md 4.1 (Tavily) adds a signal from web text; W11 forbids that.
Gates:    0/0. Failing: none. A research plan has no gates.
Verified: git diff --check → pass. grep of the plan for bot / four groups / drift → only closed or
          unrun text remains. grep of PLAN.md for credibility / trust / smaller → none stale left.
