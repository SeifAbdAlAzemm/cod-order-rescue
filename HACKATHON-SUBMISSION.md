# Agents at Work — Submission Checklist

## Official program details (as supplied by participant)
- Format: online hackathon; two tracks (students, working professionals).
- Goal: working AI agent tailored to a real SME use case, judged on **measurable business impact**, not toy demos.
- **Deadline:** Saturday **10 October 2026**, **11:59 PM Cairo time** (extended).

## Official judging dimensions
1. **Does it work?** — live functioning agent.
2. **Time saved** — hours returned to the SME.
3. **Cost saved** — money the SME no longer spends.
4. **Revenue generated** — income the agent helps create.

**Note:** Quality topics (self-improvement, observability, privacy, tokens, reliability) are heavily emphasized in webinar notes but not listed as independent official scoring dimensions in the program text supplied.

## Official required deliverables
- [ ] **GitHub repository** — working agent + source + README allowing a judge to run it in **under five minutes**.
- [ ] **Impact slides** — short deck naming the SME, workflow replaced and measured business impact.
- [ ] **Demo video** — **2–3 minutes** showing agent doing the job.

## Recommended submission plan (team-owned)
- [ ] Run 1–2 strong end-to-end flows live in the demo (plus one safe failure scenario).
- [ ] Provide scripted demo fixtures and `.env.example` (never commit secrets).
- [ ] Record precise run steps and prerequisites, smoke-test from a clean clone.
- [ ] Show baseline and agent processing time using the **same task definition**.
- [ ] Report explicit costs and realistic savings estimates; disclose assumptions.
- [ ] Do not label simulated order-rescue results as verified increases in merchant revenue.
- [ ] Verify all links, repo access, media visibility and deadline submission fields before sending.

## Compact impact formula (illustrative, not measured)
`monthly_saved_staff_hours = monthly_cases × (manual_minutes_per_case − agent_human_minutes_per_case) / 60`

`monthly_staff_value_EGP = monthly_saved_staff_hours × loaded_staff_hour_cost_EGP`

`net_monthly_savings_EGP = monthly_staff_value_EGP − model_costs − hosting_costs − messaging_costs − other incremental operational costs`

Revenue uplift needs real attributable data; **do not set an assumed increase to a factual claim**.

## Missing official submission details
Actual form URL, deck constraints, video hosting rules and rubric weights have **not** been supplied and must be checked before final submission.
