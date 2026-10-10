"""Typed, validated loader for config/settings.toml.

Unknown keys raise (via dataclass constructors), every simulation section must be
explicitly labelled as a simulation assumption, and secrets are never read from file.
"""

from __future__ import annotations

import dataclasses
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from cod_rescue import PROJECT_ROOT

SIMULATION_STATUS = "SIMULATION_ASSUMPTION"
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.toml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AppConfig:
    db_path: str
    fixtures_dir: str
    currency: str


PROVIDERS = ("anthropic", "openai_compatible")
PRICING_STATUSES = ("known", "verified_free", "unknown")


@dataclass(frozen=True)
class ModelPricing:
    status: str                 # known | verified_free | unknown  (missing pricing is NEVER treated as free)
    input: float | None         # USD per 1M tokens
    output: float | None
    source: str = ""


@dataclass(frozen=True)
class LLMProfile:
    name: str
    provider: str
    model: str
    api_key_env: str            # NAME of the environment variable holding the key, never the key itself
    pricing: ModelPricing
    base_url: str = ""
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LLMConfig:
    active_profile: str
    max_tokens: int
    request_timeout_s: float
    max_retries: int
    profiles: dict[str, LLMProfile] = field(default_factory=dict)

    @property
    def profile(self) -> LLMProfile:
        return self.profiles[self.active_profile]

    @property
    def model(self) -> str:
        return self.profile.model

    @property
    def provider(self) -> str:
        return self.profile.provider


@dataclass(frozen=True)
class AgentBudget:
    max_llm_calls: int
    max_tool_calls: int
    max_wall_time_s: float
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: float
    max_invalid_actions: int
    history_messages: int


@dataclass(frozen=True)
class DuplicateRules:
    status: str
    window_hours: float
    identity: str
    item_match: str
    ignore_lifecycle_states: list[str]
    both_intended_words: list[str]
    both_markers: list[str]


@dataclass(frozen=True)
class AddressRules:
    status: str
    required_fields: list[str]
    optional_fields: list[str]


@dataclass(frozen=True)
class PhoneRules:
    status: str
    pattern: str


@dataclass(frozen=True)
class ClarificationRules:
    status: str
    max_attempts: int
    on_exceeded: str


@dataclass(frozen=True)
class PricingRules:
    status: str
    amounts_whole_egp: bool
    recheck_prices_at_commit: bool
    on_price_change: str


@dataclass(frozen=True)
class InventoryRules:
    status: str
    reservation_point: str


@dataclass(frozen=True)
class ConfirmationRules:
    status: str
    short_affirmatives: list[str]
    filler_words: list[str]
    require_first_reply_after_request: bool


@dataclass(frozen=True)
class MessagingRules:
    status: str
    mode: str


@dataclass(frozen=True)
class FaultInjection:
    status: str
    inventory_unavailable: bool
    shipping_rates_unavailable: bool
    price_source_unavailable: bool
    commit_timeout_after_success: bool
    ledger_unavailable: bool


@dataclass(frozen=True)
class SimulationConfig:
    duplicates: DuplicateRules
    address: AddressRules
    phone: PhoneRules
    clarification: ClarificationRules
    pricing: PricingRules
    inventory: InventoryRules
    confirmation: ConfirmationRules
    messaging: MessagingRules
    fault_injection: FaultInjection


@dataclass(frozen=True)
class Settings:
    app: AppConfig
    llm: LLMConfig
    agent_budget: AgentBudget
    simulation: SimulationConfig
    source_path: Path

    @property
    def db_path(self) -> Path:
        return _resolve(self.app.db_path)

    @property
    def fixtures_dir(self) -> Path:
        return _resolve(self.app.fixtures_dir)


_SIMULATION_SECTIONS = {
    "duplicates": DuplicateRules,
    "address": AddressRules,
    "phone": PhoneRules,
    "clarification": ClarificationRules,
    "pricing": PricingRules,
    "inventory": InventoryRules,
    "confirmation": ConfirmationRules,
    "messaging": MessagingRules,
    "fault_injection": FaultInjection,
}


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _build(cls, data: dict, section: str):
    try:
        return cls(**data)
    except TypeError as exc:
        raise ConfigError(f"[{section}] {exc}") from None


def load_settings(path: Path | str | None = None, env: dict[str, str] | None = None) -> Settings:
    path = Path(path) if path else DEFAULT_SETTINGS_PATH
    env = os.environ if env is None else env
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    expected_top = {"app", "llm", "agent_budget", "simulation"}
    if set(raw) != expected_top:
        raise ConfigError(f"top-level sections must be exactly {sorted(expected_top)}, got {sorted(raw)}")

    app = dict(raw["app"])
    if env.get("COD_RESCUE_DB_PATH"):
        app["db_path"] = env["COD_RESCUE_DB_PATH"]

    llm = dict(raw["llm"])
    if any("key" in k.lower() or "secret" in k.lower() for k in llm if k != "profiles"):
        raise ConfigError("[llm] secrets must come from environment variables, not settings.toml")
    llm["profiles"] = {name: _build_profile(name, dict(p)) for name, p in llm.get("profiles", {}).items()}
    if env.get("COD_RESCUE_LLM_PROFILE"):
        llm["active_profile"] = env["COD_RESCUE_LLM_PROFILE"]
    if llm.get("active_profile") not in llm["profiles"]:
        raise ConfigError(f"[llm] active_profile {llm.get('active_profile')!r} is not one of {sorted(llm['profiles'])}")
    if env.get("COD_RESCUE_MODEL"):  # a different model has unverified pricing until configured explicitly
        active = llm["profiles"][llm["active_profile"]]
        if env["COD_RESCUE_MODEL"] != active.model:
            llm["profiles"][active.name] = dataclasses.replace(
                active, model=env["COD_RESCUE_MODEL"],
                pricing=ModelPricing("unknown", None, None, "model overridden via COD_RESCUE_MODEL"))

    sim_raw = raw["simulation"]
    if set(sim_raw) != set(_SIMULATION_SECTIONS):
        raise ConfigError(f"[simulation] sections must be exactly {sorted(_SIMULATION_SECTIONS)}, got {sorted(sim_raw)}")
    sim = {}
    for name, cls in _SIMULATION_SECTIONS.items():
        section = sim_raw[name]
        if section.get("status") != SIMULATION_STATUS:
            raise ConfigError(f"[simulation.{name}] must declare status = \"{SIMULATION_STATUS}\"")
        sim[name] = _build(cls, section, f"simulation.{name}")

    settings = Settings(
        app=_build(AppConfig, app, "app"),
        llm=_build(LLMConfig, llm, "llm"),
        agent_budget=_build(AgentBudget, raw["agent_budget"], "agent_budget"),
        simulation=SimulationConfig(**sim),
        source_path=path,
    )
    _validate(settings)
    return settings


def _validate(s: Settings) -> None:
    if s.simulation.messaging.mode != "SIMULATED_OUTBOX":
        raise ConfigError("[simulation.messaging] only SIMULATED_OUTBOX is permitted in this MVP")
    if s.simulation.duplicates.window_hours <= 0:
        raise ConfigError("[simulation.duplicates] window_hours must be > 0")
    if s.simulation.duplicates.item_match != "exact_signature":
        raise ConfigError("[simulation.duplicates] item_match must be 'exact_signature'")
    if not s.simulation.confirmation.require_first_reply_after_request:
        raise ConfigError("[simulation.confirmation] require_first_reply_after_request must stay true (BR-04)")
    if s.simulation.clarification.max_attempts < 1:
        raise ConfigError("[simulation.clarification] max_attempts must be >= 1")
    if s.simulation.clarification.on_exceeded != "ESCALATE_TO_HUMAN":
        raise ConfigError("[simulation.clarification] on_exceeded must be ESCALATE_TO_HUMAN")
    b = s.agent_budget
    if min(b.max_llm_calls, b.max_tool_calls, b.max_input_tokens, b.max_output_tokens) < 1 or b.max_wall_time_s <= 0 or b.max_cost_usd <= 0:
        raise ConfigError("[agent_budget] all limits must be positive (no unbounded execution)")
    if b.max_invalid_actions < 1 or b.history_messages < 1:
        raise ConfigError("[agent_budget] max_invalid_actions and history_messages must be >= 1")
    if s.llm.max_retries < 0 or s.llm.max_retries > 5:
        raise ConfigError("[llm] max_retries must be between 0 and 5")


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_LOCAL_HTTP = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?(/|$)")
_PROFILE_KEYS = {"provider", "model", "api_key_env", "base_url", "pricing", "price_input_per_mtok",
                 "price_output_per_mtok", "pricing_source", "options"}
_OPTION_KEYS = {"effort", "openrouter_usage", "app_title", "app_url"}


def _build_profile(name: str, p: dict) -> LLMProfile:
    where = f"llm.profiles.{name}"
    unknown = set(p) - _PROFILE_KEYS
    if unknown:
        raise ConfigError(f"[{where}] unknown keys {sorted(unknown)}")
    if p.get("provider") not in PROVIDERS:
        raise ConfigError(f"[{where}] provider must be one of {PROVIDERS}")
    if not p.get("model"):
        raise ConfigError(f"[{where}] model is required")
    key_env = p.get("api_key_env", "")
    if not _ENV_NAME.match(key_env):
        raise ConfigError(f"[{where}] api_key_env must be an environment variable NAME (e.g. OPENROUTER_API_KEY), "
                          "never the key itself")
    base_url = p.get("base_url", "")
    if p["provider"] == "openai_compatible" and not (base_url.startswith("https://") or _LOCAL_HTTP.match(base_url)):
        raise ConfigError(f"[{where}] base_url must be https:// (http only for localhost)")
    options = dict(p.get("options", {}))
    if set(options) - _OPTION_KEYS:
        raise ConfigError(f"[{where}] unknown options {sorted(set(options) - _OPTION_KEYS)}")
    if "effort" in options and options["effort"] not in ("low", "medium", "high"):
        raise ConfigError(f"[{where}] options.effort must be low, medium or high")
    status = p.get("pricing", "unknown")
    pin, pout = p.get("price_input_per_mtok"), p.get("price_output_per_mtok")
    if status not in PRICING_STATUSES:
        raise ConfigError(f"[{where}] pricing must be one of {PRICING_STATUSES}")
    if status == "known" and not (isinstance(pin, (int, float)) and isinstance(pout, (int, float))
                                  and pin >= 0 and pout >= 0 and (pin > 0 or pout > 0)):
        raise ConfigError(f"[{where}] pricing='known' needs non-negative prices, not both zero "
                          "(use pricing='verified_free' for a verified zero-cost model)")
    if status == "verified_free" and not (pin == 0 and pout == 0 and p.get("pricing_source")):
        raise ConfigError(f"[{where}] pricing='verified_free' needs both prices = 0 and a pricing_source")
    if status == "unknown" and (pin is not None or pout is not None):
        raise ConfigError(f"[{where}] pricing='unknown' must not set prices")
    return LLMProfile(name, p["provider"], p["model"], key_env,
                      ModelPricing(status, pin, pout, p.get("pricing_source", "")), base_url, options)


def model_pricing(settings: Settings, profile: LLMProfile | None = None) -> ModelPricing:
    """Pricing for LIVE runs. Unknown pricing refuses to run: the cost budget could not be enforced."""
    profile = profile or settings.llm.profile
    if profile.pricing.status == "unknown":
        raise ConfigError(f"profile {profile.name!r}: no pricing configured for model {profile.model!r} "
                          "(unknown pricing is never treated as free); set pricing in settings.toml")
    return profile.pricing


def allowed_env_keys(settings: Settings) -> set[str]:
    return {p.api_key_env for p in settings.llm.profiles.values()}


def load_dotenv(path: Path | None = None, env: dict | None = None, allowed: set[str] | None = None) -> None:
    """Minimal .env loader (KEY=VALUE lines). Loads only the key names profiles reference (default:
    ANTHROPIC_API_KEY, OPENROUTER_API_KEY) and COD_RESCUE_*; never overrides the real environment."""
    path = path or PROJECT_ROOT / ".env"
    env = os.environ if env is None else env
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        names = allowed if allowed is not None else {"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"}
        if (key in names or key.startswith("COD_RESCUE_")) and value and key not in env:
            env[key] = value.strip('"').strip("'")
