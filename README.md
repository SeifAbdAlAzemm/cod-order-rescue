# COD Order Rescue — Hackathon Context Pack

This folder contains a **business-approved proposed MVP specification** and a delivery/evaluation handoff for Claude Code. **It is not an implemented agent**.

## Suggested reading order
1. `PROJECT-BRIEF.md` — problem, SME, scope and intended outcomes.
2. `REQUIREMENTS.md` — user-approved BR-01...BR-06 plus proposed decisions and ACs.
3. `HACKATHON-SUBMISSION.md` — the **official program details supplied by the participant** and deliverables.
4. `QUALITY-CHECKLIST.md` — **webinar-derived** engineering checks; not all are official scoring criteria.
5. `TEST-SCENARIOS.md` — 16 **not-yet-executed** scenarios.
6. `AGENT-ARCHITECTURE.md` — logical components and open technology decisions.
7. `AGENTS.md` — how Claude Code should behave, starting with a proposed plan before coding.

## Provenance
Business decisions BR-01 to BR-06 were explicitly approved as **proposed MVP rules**, not validated policies of an actual merchant. Source webinar notes were supplied in `sessions_notes.md` (not reproduced verbatim here). Official deadline and judging/submission details were supplied in chat. Avoid confusing **known instructions**, **agreed hypothetical rules** and **remaining assumptions**.

## Start prompt for Claude Code
```
Read all Markdown files in this repository, starting with README.md and AGENTS.md.
Do not edit files or implement anything yet.
Summarize (1) approved business scope and BR-01..BR-06, (2) open assumptions,
(3) official hackathon deliverables, (4) the smallest safe proposed technical architecture,
(5) a prioritized implementation and test plan to deliver a working demo.
Clearly distinguish simulation from real merchant integration.
Wait for my approval before writing code.
```
