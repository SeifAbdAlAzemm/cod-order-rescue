"""Slice 3 REPLAY evaluation: every scenario in data/scenarios/scenarios.json through the full agent
loop with scripted model turns. These are REPLAY results (no API, no model understanding claimed)."""

import pytest

from cod_rescue.agent.evaluation import load_scenarios, run_scenario

SCENARIOS = load_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[f"{s['id']}-{'_'.join(s['test_cases']) or 'robustness'}" for s in SCENARIOS])
def test_replay_scenario(scenario, settings, tmp_path):
    result = run_scenario(scenario, settings, "REPLAY", tmp_path)
    assert result["passed"], result["failures"]
    for e in result["events"]:
        assert e["result"].get("cost_usd", 0) == 0
        if "run_id" in e["result"]:
            assert e["result"]["cost_basis"] == "NOT_APPLICABLE_REPLAY" and e["result"]["mode"] == "REPLAY"


def test_scenarios_cover_all_test_cases_and_requested_conditions():
    tcs = {tc for s in SCENARIOS for tc in s["test_cases"]}
    assert tcs == {f"TC-{i:02d}" for i in range(1, 17)}
    titles = " ".join(s["title"].lower() for s in SCENARIOS)
    for needle in ["injection", "runaway", "budget", "malformed", "api failure", "duplicate", "only one", "shipped"]:
        assert needle in titles, needle
