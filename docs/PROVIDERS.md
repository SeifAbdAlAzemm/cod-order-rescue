# LLM Providers

The agent is provider-agnostic. **Execution mode** and **provider** are independent choices:

| | REPLAY (default) | LIVE |
|---|---|---|
| Calls an LLM provider | Never | Yes (the active profile) |
| Credentials | None | Key in the env var named by the profile |
| Cost | Not applicable | Local estimate + provider-reported (if any) |
| Results | `results/replay/` | `results/live/<provider>/<model>/` |

Business rules, the policy engine, guarded tools and database safety are identical for every provider: the model only chooses among the same 11 allowlisted tools, and code enforces every rule.

## Architecture
```
runtime (provider-neutral conversation: UserTurn / AssistantTurn / ToolResultsTurn, neutral JSON-Schema tools)
   └─ providers/
       ├─ anthropic_provider.py   Anthropic Messages API (official anthropic SDK)
       ├─ openai_compatible.py    OpenAI Chat Completions format (official openai SDK, configurable base_url)
       ├─ replay.py               scripted turns, no network
       ├─ capabilities.py         non-billable checks: key present, model listed, declared tools, pricing
       └─ __init__.py             REGISTRY = {"anthropic": ..., "openai_compatible": ...}
```
Adding a provider: if it speaks the OpenAI Chat Completions format, it is **configuration only** (new profile). Otherwise write one adapter class implementing `create(system, tools, conversation, remaining_s) -> LLMResponse` and add it to `REGISTRY`. The runtime does not change.

## Profiles (`config/settings.toml`)
```toml
[llm]
active_profile = "anthropic-haiku"          # or COD_RESCUE_LLM_PROFILE=<name>, or --profile <name>

[llm.profiles.openrouter-gemma-free]
provider = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
model = "google/gemma-4-31b-it:free"
api_key_env = "OPENROUTER_API_KEY"          # the NAME of the env var, never the key
pricing = "verified_free"
price_input_per_mtok = 0.0
price_output_per_mtok = 0.0
pricing_source = "OpenRouter GET /api/v1/models ... (2026-10-10)"
options = { openrouter_usage = true }       # ask OpenRouter to report actual cost per request
```
Shared across profiles: `max_tokens`, per-attempt timeout (capped by the remaining per-event wall budget), SDK retries, and all `[agent_budget]` limits.

| Profile | Provider | Model | Pricing | Tested |
|---|---|---|---|---|
| `anthropic-haiku` | anthropic | `claude-haiku-5-5` | known ($0.10 / $0.50 per 1M) | adapter offline-tested; LIVE not run |
| `openrouter-gemma-free` | openai_compatible (OpenRouter) | `google/gemma-4-31b-it:free` | verified_free (listing, 2026-10-10) | adapter offline-tested; listing checked; LIVE not run |
| Hugging Face router / OpenAI | openai_compatible | your choice | your choice | **template only, not tested** |

Templates (commented in `settings.toml`): Hugging Face `https://router.huggingface.co/v1` with `api_key_env="HF_TOKEN"`; OpenAI `https://api.openai.com/v1` with `api_key_env="OPENAI_API_KEY"`.

## Pricing status (cost budgets depend on it)
- **known** — nonzero prices configured; cost estimated locally from token usage.
- **verified_free** — both prices 0 *and* a `pricing_source`; for OpenRouter the zero price is re-checked against the live listing before every LIVE run (refused if the listing is not free). Cost basis recorded as `VERIFIED_FREE_MODEL`.
- **unknown** — LIVE refuses to run. **Missing pricing is never treated as free.** Overriding the model with `COD_RESCUE_MODEL` makes pricing unknown until configured.

Per run we record `cost_usd` (local estimate = tokens × configured prices) and, separately, `provider_cost_usd` (what the provider reported, e.g. OpenRouter usage accounting; `null` if not reported). Budgets are enforced on the higher of the two.

## Tool-calling capability
- **Declared** — model metadata says it supports tools (`check-provider`; OpenRouter `supported_parameters` contains `tools`).
- **Verified** — a LIVE evaluation in which the real model produced a schema-valid tool call that the harness executed (`tool_support_verified_live` in the LIVE report). Never assumed.
- A provider error saying tools are unsupported maps to `UNSUPPORTED_CAPABILITY` → the run fails closed and escalates.

Free models can be rate-limited, slower, or change availability; OpenRouter's free endpoints may have their own data policies. This project sends only synthetic data.

## Setup (LIVE)
1. Create a key with the provider (e.g. openrouter.ai → Keys). Do not paste it into code, config, prompts, chats or git.
2. Put it in `.env` (git-ignored), e.g. `OPENROUTER_API_KEY=...`. Only variable names referenced by profiles are loaded.
3. Non-billable check: `python -m cod_rescue --profile openrouter-gemma-free check-provider`
4. Small run first: `python -m cod_rescue --profile openrouter-gemma-free eval --mode live --scenario S01 -v`

## Future option: Sign in with ChatGPT (not implemented)
OpenAI documents "Sign in with ChatGPT" for eligible open-source applications: https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt . Supporting it here would mean implementing the **official OAuth flow** and a new adapter for the **Responses API** it supports (our OpenAI-compatible adapter uses Chat Completions). It needs an interactive user login, so it does not suit unattended judge evaluation; API-key profiles remain the default. We never reuse browser cookies, Codex credentials or any unofficial authentication method.
