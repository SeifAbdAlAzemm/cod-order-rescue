"""Typed, validated loader for config/settings.toml.

Unknown keys raise (via dataclass constructors), every simulation section must be
explicitly labelled as a simulation assumption, and secrets are never read from file.
"""

from __future__ import annotations

import os
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


@dataclass(frozen=True)
class ModelPricing:
    input: float
    output: float


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    max_tokens: int
    effort: str
    request_timeout_s: float
    max_retries: int
    pricing_usd_per_mtok: dict[str, ModelPricing] = field(default_factory=dict)


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
    if env.get("COD_RESCUE_MODEL"):
        llm["model"] = env["COD_RESCUE_MODEL"]
    llm["pricing_usd_per_mtok"] = {
        model: _build(ModelPricing, p, f"llm.pricing_usd_per_mtok.{model}")
        for model, p in llm.get("pricing_usd_per_mtok", {}).items()
    }
    if any("key" in k.lower() or "secret" in k.lower() for k in llm):
        raise ConfigError("[llm] secrets must come from environment variables, not settings.toml")

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
    if s.llm.effort not in ("low", "medium", "high"):
        raise ConfigError("[llm] effort must be low, medium or high")
    if b.max_invalid_actions < 1 or b.history_messages < 1:
        raise ConfigError("[agent_budget] max_invalid_actions and history_messages must be >= 1")
    if s.llm.max_retries < 0 or s.llm.max_retries > 5:
        raise ConfigError("[llm] max_retries must be between 0 and 5")


def model_pricing(settings: Settings) -> ModelPricing:
    """Prices for the configured model; LIVE mode refuses to run without them (cost budget needs them)."""
    try:
        return settings.llm.pricing_usd_per_mtok[settings.llm.model]
    except KeyError:
        raise ConfigError(f"no pricing configured for model {settings.llm.model!r}; "
                          "add [llm.pricing_usd_per_mtok.\"<model>\"] to settings.toml") from None


def load_dotenv(path: Path | None = None, env: dict | None = None) -> None:
    """Minimal .env loader (KEY=VALUE lines) for ANTHROPIC_API_KEY / COD_RESCUE_*; never overrides real env."""
    path = path or PROJECT_ROOT / ".env"
    env = os.environ if env is None else env
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        if (key == "ANTHROPIC_API_KEY" or key.startswith("COD_RESCUE_")) and value and key not in env:
            env[key] = value.strip('"').strip("'")
