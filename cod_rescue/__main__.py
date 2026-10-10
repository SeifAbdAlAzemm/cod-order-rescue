"""CLI: python -m cod_rescue {init-db,seed,status,eval,check-model,handle} [--db PATH]"""

from __future__ import annotations

import argparse
import os
import sys

from cod_rescue.config import ConfigError, load_dotenv, load_settings, model_pricing
from cod_rescue.db import SchemaVersionError, connect, init_db, schema_version
from cod_rescue.seed import SeedError, seed


def _require_live(settings) -> None:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ConfigError("LIVE mode needs ANTHROPIC_API_KEY in the environment or a local .env file (never commit it)")
    model_pricing(settings)  # cost budget requires known prices


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
                    print(f"        -> customer [{m['kind']}]: {m['text'][:140]}")
                print(f"        = outcome {r.get('outcome')} | lifecycle {r.get('lifecycle_state')} | "
                      f"error {r.get('error_class')} | llm_calls {r.get('llm_calls')} tool_calls {r.get('tool_calls')}"
                      + ("  (saved result replayed)" if r.get("replayed_from_saved_result") else ""))
    t = report["totals"]
    print(f"\n{report['mode']}: {report['passed']}/{report['total']} scenarios passed"
          + (f" | skipped (not live-capable): {', '.join(report['skipped_not_live_capable'])}"
             if report["skipped_not_live_capable"] else ""))
    if report["mode"] == "LIVE":
        print(f"LIVE usage: {t['llm_calls']} model calls, {t['input_tokens']} in / {t['output_tokens']} out tokens, "
              f"estimated cost ${t['cost_usd']:.4f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cod_rescue", description="COD Order Rescue (local MVP, synthetic data)")
    parser.add_argument("--db", help="SQLite path (default from config/settings.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create the schema if missing")
    seed_p = sub.add_parser("seed", help="load synthetic fixtures into an empty database")
    seed_p.add_argument("--reset", action="store_true",
                        help="replace an existing SYNTHETIC demo database (refused for any other database)")
    sub.add_parser("status", help="show schema version and orders")
    ev = sub.add_parser("eval", help="run agent scenarios (REPLAY by default; LIVE only when explicitly requested)")
    ev.add_argument("--mode", choices=["replay", "live"], default="replay")
    ev.add_argument("--scenario", action="append", help="scenario id (repeatable), e.g. S01")
    ev.add_argument("--verbose", "-v", action="store_true", help="print tool trace and customer messages")
    sub.add_parser("check-model", help="verify the configured model ID via the Models API (needs API key; not billed)")
    h = sub.add_parser("handle", help="LIVE: process one customer message for one order (billable)")
    h.add_argument("--order", required=True)
    h.add_argument("--event", required=True, help="unique event id")
    h.add_argument("--text", required=True)
    args = parser.parse_args(argv)

    settings = load_settings()
    db_path = args.db or settings.db_path

    try:
        if args.command == "eval":
            factory = None
            if args.mode == "live":
                _require_live(settings)
                from cod_rescue.agent.llm import AnthropicLLM
                factory = AnthropicLLM
                print(f"LIVE evaluation with {settings.llm.model}: billable API calls; per-event cap "
                      f"${settings.agent_budget.max_cost_usd} and {settings.agent_budget.max_llm_calls} calls.")
            from cod_rescue.agent.evaluation import run_suite
            report = run_suite(settings, args.mode.upper(), args.scenario, live_llm_factory=factory)
            _print_eval(report, args.verbose)
            return 0 if report["passed"] == report["total"] else 1
        if args.command == "check-model":
            _require_live(settings)
            import anthropic
            m = anthropic.Anthropic().models.retrieve(settings.llm.model)
            print(f"OK: {m.id} ({getattr(m, 'display_name', '')}) is available to this API key")
            return 0
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
                print(f"DB: {db_path} | schema v{schema_version(conn)} | model: {settings.llm.model} | messaging: SIMULATED")
                for r in conn.execute("SELECT order_id, lifecycle_state, version, agent_outcome FROM orders ORDER BY order_id"):
                    print(f"  {r['order_id']}  {r['lifecycle_state']:<19} v{r['version']}  outcome={r['agent_outcome'] or '-'}")
            elif args.command == "handle":
                _require_live(settings)
                from cod_rescue.agent.llm import AnthropicLLM
                from cod_rescue.agent.runtime import handle_event
                from cod_rescue.context import ToolContext
                result = handle_event(ToolContext(conn, settings), AnthropicLLM(settings), args.order, args.event, args.text)
                for m in result.get("messages_sent", []):
                    print(f"-> customer [{m['kind']}]: {m['text']}")
                print({k: result.get(k) for k in ("outcome", "lifecycle_state", "error_class", "llm_calls",
                                                  "tool_calls", "input_tokens", "output_tokens", "cost_usd", "cost_basis")})
        finally:
            conn.close()
    except (SeedError, SchemaVersionError, ConfigError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
