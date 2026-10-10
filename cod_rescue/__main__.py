"""CLI: python -m cod_rescue [--profile NAME] {init-db,seed,status,eval,check-provider,handle} [--db PATH]

Execution mode (REPLAY default / LIVE) is chosen per command; the LLM provider profile is chosen
independently with --profile or COD_RESCUE_LLM_PROFILE. REPLAY never calls any provider.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys

from cod_rescue.config import ConfigError, allowed_env_keys, load_dotenv, load_settings, model_pricing
from cod_rescue.db import SchemaVersionError, connect, init_db, schema_version
from cod_rescue.seed import SeedError, seed


def _require_live(settings) -> None:
    """Preflight for billable LIVE calls on the active profile. Never prints the key."""
    from cod_rescue.agent.providers.capabilities import check_profile, is_openrouter

    profile = settings.llm.profile
    load_dotenv(allowed=allowed_env_keys(settings))
    if not os.environ.get(profile.api_key_env):
        raise ConfigError(f"LIVE mode with profile {profile.name!r} needs {profile.api_key_env} in the environment "
                          "or a local .env file (never commit it)")
    model_pricing(settings, profile)  # refuses unknown pricing
    if profile.pricing.status == "verified_free" or is_openrouter(profile):
        report = check_profile(settings, profile)  # non-billable metadata check
        if not report["live_ready"]:
            raise ConfigError(f"profile {profile.name!r} failed preflight: {'; '.join(report['problems'])}")


def _print_eval(report: dict, verbose: bool) -> None:
    print(f"\n{report['label']}")
    for s in report["scenarios"]:
        print(f"  [{'PASS' if s['passed'] else 'FAIL'}] {s['id']} {s['title']}  {','.join(s['test_cases'])}")
        for f in s["failures"]:
            print(f"         - {f}")
        if verbose:
            for e in s["events"]:
                r = e["result"]
                print(f"      customer ({e['order_id']}): {e['customer_text']}")
                for st in e["trace"]:
                    if st["kind"] == "TOOL_CALL":
                        out = (st["output_json"] or "")[:110]
                        print(f"        tool {st['name']}({(st['input_json'] or '')[:70]}) -> {out}")
                for m in r.get("messages_sent", []):
                    tag = " (template)" if m.get("template") else ""
                    print(f"        -> customer [{m['kind']}]{tag}: {m['text'][:140]}")
                print(f"        = outcome {r.get('outcome')} | lifecycle {r.get('lifecycle_state')} | "
                      f"error {r.get('error_class')} | llm_calls {r.get('llm_calls')} tool_calls {r.get('tool_calls')}"
                      + ("  (saved result replayed)" if r.get("replayed_from_saved_result") else ""))
                if report["mode"] == "LIVE" and not r.get("replayed_from_saved_result"):
                    pc = r.get("provider_cost_usd")
                    print(f"        = tokens {r.get('input_tokens')} in / {r.get('output_tokens')} out | "
                          f"latency {r.get('latency_ms')} ms | local est. ${r.get('cost_usd', 0):.5f} ({r.get('cost_basis')})"
                          f" | provider-reported {'$%.5f' % pc if pc is not None else 'n/a'}"
                          + (" | FALLBACK reply used" if r.get("fallback_reply_used") else ""))
                if r.get("agent_summary"):
                    print(f"        model summary: {r['agent_summary'][:160]}")
    t = report["totals"]
    print(f"\n{report['mode']}: {report['passed']}/{report['total']} scenarios passed"
          + (f" | skipped (not live-capable): {', '.join(report['skipped_not_live_capable'])}"
             if report["skipped_not_live_capable"] else ""))
    if report["mode"] == "LIVE":
        pc = t.get("provider_cost_usd")
        print(f"LIVE {report['provider']}/{report['model']}: {t['llm_calls']} model calls, {t['input_tokens']} in / "
              f"{t['output_tokens']} out tokens | local estimate ${t['cost_usd']:.4f} | provider-reported "
              f"{'$%.4f' % pc if pc is not None else 'n/a'} | tool calling verified live: {report['tool_support_verified_live']}")
        print(f"Results: {report['results_path']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cod_rescue", description="COD Order Rescue (local MVP, synthetic data)")
    parser.add_argument("--db", help="SQLite path (default from config/settings.toml)")
    parser.add_argument("--profile", help="LLM provider profile from config/settings.toml (LIVE only)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create the schema if missing")
    seed_p = sub.add_parser("seed", help="load synthetic fixtures into an empty database")
    seed_p.add_argument("--reset", action="store_true",
                        help="replace an existing SYNTHETIC demo database (refused for any other database)")
    sub.add_parser("status", help="show schema version, active profile and orders")
    ev = sub.add_parser("eval", help="run agent scenarios (REPLAY by default; LIVE only when explicitly requested)")
    ev.add_argument("--mode", choices=["replay", "live"], default="replay")
    ev.add_argument("--scenario", action="append", help="scenario id (repeatable), e.g. S01")
    ev.add_argument("--verbose", "-v", action="store_true", help="print tool trace and customer messages")
    sub.add_parser("check-provider", help="non-billable checks: key present, model listed, declared tool support, pricing")
    sub.add_parser("check-model", help="alias of check-provider")
    h = sub.add_parser("handle", help="LIVE: process one customer message for one order (may be billable)")
    h.add_argument("--order", required=True)
    h.add_argument("--event", required=True, help="unique event id")
    h.add_argument("--text", required=True)
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        if args.profile:
            if args.profile not in settings.llm.profiles:
                raise ConfigError(f"unknown profile {args.profile!r}; choose from {sorted(settings.llm.profiles)}")
            settings = dataclasses.replace(settings, llm=dataclasses.replace(settings.llm, active_profile=args.profile))
        db_path = args.db or settings.db_path

        if args.command == "eval":
            factory = None
            if args.mode == "live":
                _require_live(settings)
                from cod_rescue.agent.providers import build_provider
                factory = build_provider
                p = settings.llm.profile
                print(f"LIVE evaluation | profile {p.name} | {p.provider} | {p.model} | pricing {p.pricing.status} | "
                      f"per-event caps ${settings.agent_budget.max_cost_usd}, {settings.agent_budget.max_llm_calls} calls")
            from cod_rescue.agent.evaluation import run_suite
            report = run_suite(settings, args.mode.upper(), args.scenario, live_llm_factory=factory)
            _print_eval(report, args.verbose)
            return 0 if report["passed"] == report["total"] else 1
        if args.command in ("check-provider", "check-model"):
            from cod_rescue.agent.providers.capabilities import check_profile
            load_dotenv(allowed=allowed_env_keys(settings))
            r = check_profile(settings, settings.llm.profile)
            for k in ("profile", "provider", "model", "base_url", "api_key_env", "key_present", "model_listed",
                      "tool_support", "pricing_status", "pricing_check", "listed_prices_per_mtok", "live_ready"):
                if k in r:
                    print(f"  {k:<23} {r[k]}")
            for problem in r["problems"]:
                print(f"  problem: {problem}")
            print("  (declared support only; tool calling is verified by a LIVE run)")
            return 0 if r["live_ready"] else 1
        conn = connect(db_path)
        try:
            if args.command == "init-db":
                created = init_db(conn)
                print(f"{'Created' if created else 'Already initialized'}: {db_path} (schema v{schema_version(conn)})")
            elif args.command == "seed":
                counts = seed(conn, settings, replace_existing=args.reset)
                print(f"Seeded SYNTHETIC data into {db_path}")
                for table, n in counts.items():
                    if n:
                        print(f"  {table:<22} {n}")
            elif args.command == "status":
                init_db(conn)
                p = settings.llm.profile
                print(f"DB: {db_path} | schema v{schema_version(conn)} | LLM profile: {p.name} ({p.provider}/{p.model}) "
                      f"| messaging: SIMULATED")
                for r in conn.execute("SELECT order_id, lifecycle_state, version, agent_outcome FROM orders ORDER BY order_id"):
                    print(f"  {r['order_id']}  {r['lifecycle_state']:<19} v{r['version']}  outcome={r['agent_outcome'] or '-'}")
            elif args.command == "handle":
                _require_live(settings)
                from cod_rescue.agent.providers import build_provider
                from cod_rescue.agent.runtime import handle_event
                from cod_rescue.context import ToolContext
                result = handle_event(ToolContext(conn, settings), build_provider(settings), args.order, args.event, args.text)
                for m in result.get("messages_sent", []):
                    print(f"-> customer [{m['kind']}]: {m['text']}")
                print({k: result.get(k) for k in ("outcome", "lifecycle_state", "error_class", "provider", "model",
                                                  "llm_calls", "tool_calls", "input_tokens", "output_tokens",
                                                  "cost_usd", "provider_cost_usd", "cost_basis")})
        finally:
            conn.close()
    except (SeedError, SchemaVersionError, ConfigError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
