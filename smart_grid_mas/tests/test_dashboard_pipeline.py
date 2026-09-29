"""Test Suite for Dashboard Data Pipeline & Integration.

Validates:
1. Generation and integrity of dashboard_data.json and dashboard_data.js.
2. Presence of all 6 required simulation scenarios.
3. 24 hourly discrete records per scenario and mode.
4. Outage islanding behavior and grid disconnect.
5. Exact arithmetic reconciliation between hourly records and summary metrics.
6. Real empirical microgrid dataset P2P transactions and A* savings.
7. Authentic FIPA ACL message packets in telemetry.
8. Multi-agent scalability (3, 10, 25, 50 households).
"""

import json
import os
from pathlib import Path
import pytest
from smart_grid_mas.scenarios.scenario_runner import ScenarioRunner


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JSON_PATH = PROJECT_ROOT / "dashboard_data.json"
JS_PATH = PROJECT_ROOT / "dashboard_data.js"


@pytest.fixture(scope="module")
def dashboard_json_data():
    """Load dashboard_data.json once for the test module."""
    assert JSON_PATH.exists(), f"{JSON_PATH} does not exist. Run export_dashboard_data.py first."
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_data_files_exist_and_non_empty():
    """Verify that export files exist and are adequately sized."""
    assert JSON_PATH.exists(), "dashboard_data.json must exist"
    assert JS_PATH.exists(), "dashboard_data.js must exist"

    assert os.path.getsize(JSON_PATH) > 10000, "dashboard_data.json is suspiciously small"
    assert os.path.getsize(JS_PATH) > 10000, "dashboard_data.js is suspiciously small"

    # Verify JS file format
    with open(JS_PATH, "r", encoding="utf-8") as f:
        js_content = f.read()
    assert "window.GRID_DATA = {" in js_content, "dashboard_data.js must bind window.GRID_DATA"
    assert js_content.strip().endswith("};"), "dashboard_data.js must be a valid JS assignment ending with ;"


def test_all_scenarios_present(dashboard_json_data):
    """Verify all 6 scenarios are present in dashboard data."""
    expected_scenarios = [
        "baseline",
        "real_world_dataset",
        "cloud_cover",
        "peak_demand",
        "grid_outage",
        "combined",
    ]
    for sc in expected_scenarios:
        assert sc in dashboard_json_data, f"Scenario '{sc}' missing from dashboard_data.json"
        assert "greedy" in dashboard_json_data[sc], f"Mode 'greedy' missing from scenario {sc}"
        assert "astar" in dashboard_json_data[sc], f"Mode 'astar' missing from scenario {sc}"


def test_24_hourly_records_per_scenario_and_mode(dashboard_json_data):
    """Ensure exactly 24 sequential hourly records exist for every scenario and mode."""
    for sc_name, sc_data in dashboard_json_data.items():
        for mode in ["greedy", "astar"]:
            hourly = sc_data[mode]["hourly"]
            assert len(hourly) == 24, f"{sc_name} {mode} has {len(hourly)} records, expected 24"
            for expected_hour, rec in enumerate(hourly):
                assert rec["hour"] == expected_hour, (
                    f"{sc_name} {mode} hour index mismatch: got {rec['hour']}, expected {expected_hour}"
                )


def test_grid_outage_scenario_behavior(dashboard_json_data):
    """Ensure grid outage scenario enforces microgrid islanding during blackout hours."""
    outage_data = dashboard_json_data["grid_outage"]
    for mode in ["greedy", "astar"]:
        hourly = outage_data[mode]["hourly"]
        summary = outage_data[mode]["summary"]
        assert summary["outage_hours"] >= 2, "Summary outage hours must be at least 2"

        # Hours 18 and 19 are the designated blackout interval
        for h in range(18, 20):
            rec = hourly[h]
            assert rec["grid_available"] is False, f"Grid should be unavailable at hour {h}"
            assert rec["grid_import"] == 0.0, f"Grid import must be 0.0 during outage hour {h}"


def test_summary_metrics_match_hourly_aggregation(dashboard_json_data):
    """Reconcile summary metrics against the sum of hourly records within numerical tolerance."""
    for sc_name, sc_data in dashboard_json_data.items():
        for mode in ["greedy", "astar"]:
            hourly = sc_data[mode]["hourly"]
            summary = sc_data[mode]["summary"]

            sum_demand = sum(r["total_demand"] for r in hourly)
            sum_solar = sum(r["total_solar_generation"] for r in hourly)
            sum_import = sum(r["grid_import"] for r in hourly)
            sum_p2p = sum(r["p2p_energy_traded"] for r in hourly)
            sum_unmet = sum(r["unmet_demand"] for r in hourly)

            assert abs(sum_demand - summary["total_demand"]) < 0.2, (
                f"{sc_name} {mode} demand mismatch: sum {sum_demand} vs summary {summary['total_demand']}"
            )
            assert abs(sum_solar - summary["total_solar"]) < 0.2, (
                f"{sc_name} {mode} solar mismatch: sum {sum_solar} vs summary {summary['total_solar']}"
            )
            assert abs(sum_import - summary["total_import"]) < 0.2, (
                f"{sc_name} {mode} import mismatch: sum {sum_import} vs summary {summary['total_import']}"
            )
            assert abs(sum_p2p - summary["total_p2p"]) < 0.2, (
                f"{sc_name} {mode} p2p mismatch: sum {sum_p2p} vs summary {summary['total_p2p']}"
            )
            assert abs(sum_unmet - summary["total_unmet"]) < 0.2, (
                f"{sc_name} {mode} unmet mismatch: sum {sum_unmet} vs summary {summary['total_unmet']}"
            )


def test_empirical_dataset_p2p_and_savings(dashboard_json_data):
    """Ensure real-world empirical dataset produces active P2P trades and positive A* savings."""
    rw = dashboard_json_data["real_world_dataset"]
    g_summary = rw["greedy"]["summary"]
    a_summary = rw["astar"]["summary"]

    assert g_summary["total_p2p"] > 0, "Real-world dataset must have non-zero P2P trading in greedy"
    assert a_summary["total_p2p"] > 0, "Real-world dataset must have non-zero P2P trading in astar"

    savings = (g_summary["total_cost"] - a_summary["total_cost"]) / g_summary["total_cost"] * 100.0
    assert savings > 0.0, f"A* planning should achieve positive cost savings; got {savings:.2f}%"


def test_telemetry_messages_and_trades_present(dashboard_json_data):
    """Ensure hourly records capture authentic FIPA ACL message packets."""
    rw = dashboard_json_data["real_world_dataset"]["greedy"]
    all_messages = []
    for h in rw["hourly"]:
        all_messages.extend(h.get("messages", []))

    assert len(all_messages) > 0, "Simulation telemetry must capture FIPA messages"

    # Check required FIPA ACL message types
    msg_types = {m["type"] for m in all_messages}
    expected_types = {"SURPLUS", "DEFICIT", "REQUEST", "OFFER", "ACCEPT"}
    assert expected_types.issubset(msg_types), (
        f"Missing FIPA types: expected {expected_types}, found {msg_types}"
    )

    # Verify message payload schema
    sample_msg = all_messages[0]
    assert "sender" in sample_msg
    assert "receiver" in sample_msg
    assert "type" in sample_msg
    assert "amount" in sample_msg
    assert "timestamp" in sample_msg


@pytest.mark.parametrize("n_agents", [3, 10, 25, 50])
def test_multi_agent_scalability(n_agents):
    """Verify backend and scenario runner scale dynamically across variable agent populations."""
    runner = ScenarioRunner()
    res = runner.run_24h_scenario(
        scenario_name="baseline",
        num_households=n_agents,
        planning_mode="GREEDY",
    )
    assert len(res.hourly_records) == 24
    assert res.total_energy_demand_kwh > 0
    # Verify each hourly record contains exactly n_agents
    for hr in res.hourly_records:
        assert len(hr["agents"]) == n_agents
