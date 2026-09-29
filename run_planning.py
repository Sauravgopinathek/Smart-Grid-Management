"""Smart Grid Multi-Agent System - Module 4 Planning CLI.

Demonstrates Decentralized A* Local Trajectory Planning & Predictive Energy Optimization:
- Time-of-Use (TOU) electricity pricing optimization (Off-Peak Rs. 3, Normal Rs. 5, Peak Rs. 8)
- A* search f(n) = g(n) + h(n) with an admissible (relaxation-based) heuristic
- Receding-horizon local replanning without central coordinator
- Side-by-side comparative benchmark: GREEDY baseline vs A* PREDICTIVE planning
"""

import sys
import argparse
from typing import List, Dict, Any
from smart_grid_mas.planning.astar_planner import AStarPlanner, PlanningResult
from smart_grid_mas.planning.cost_function import TOUTariff, CostFunction
from smart_grid_mas.planning.planning_state import PlanningAction
from smart_grid_mas.scenarios.scenario_runner import ScenarioRunner, ScenarioResult


def print_tou_schedule() -> None:
    """Display the Time-of-Use electricity tariff schedule."""
    print("=" * 76)
    print("TIME-OF-USE (TOU) ELECTRICITY PRICING SCHEDULE")
    print("=" * 76)
    print(f"{'Time Band':<22} | {'Hours':<14} | {'Import Tariff':<16} | {'Export Tariff'}")
    print("-" * 76)
    print(f"{'Off-Peak (Night)':<22} | {'00:00 - 06:00':<14} | {'Rs. 3.00 / kWh':<16} | {'Rs. 2.00 / kWh'}")
    print(f"{'Normal / Mid-Peak':<22} | {'06:00 - 17:00':<14} | {'Rs. 5.00 / kWh':<16} | {'Rs. 2.00 / kWh'}")
    print(f"{'Peak (Evening)':<22} | {'17:00 - 21:00':<14} | {'Rs. 8.00 / kWh':<16} | {'Rs. 2.00 / kWh'}")
    print(f"{'Normal (Late Night)':<22} | {'21:00 - 24:00':<14} | {'Rs. 5.00 / kWh':<16} | {'Rs. 2.00 / kWh'}")
    print("=" * 76)
    print()


def print_single_agent_plan_trace(horizon: int = 6) -> None:
    """Demonstrate A* trajectory optimization for an individual household agent."""
    print("=" * 76)
    print(f"DECENTRALIZED A* SEARCH TRACE (Horizon H = {horizon} Hours)")
    print("=" * 76)

    planner = AStarPlanner(horizon=horizon)
    start_hour = 14  # 14:00 (midday heading into evening peak)
    initial_soc = 40.0
    battery_cap = 10.0

    # Solar drops from afternoon to 0 in evening; demand surges at 17:00-19:00
    solar_fc = [4.5, 2.0, 0.0, 0.0, 0.0, 0.0]
    demand_fc = [2.5, 3.0, 5.0, 6.0, 5.5, 4.0]

    # Adjust lists to match requested horizon
    solar_fc = (solar_fc * ((horizon // len(solar_fc)) + 1))[:horizon]
    demand_fc = (demand_fc * ((horizon // len(demand_fc)) + 1))[:horizon]

    print(f"Agent Initial State: SOC = {initial_soc:.1f}%, Capacity = {battery_cap} kWh")
    print(f"Planning Window:     {start_hour:02d}:00 to {(start_hour + horizon) % 24:02d}:00")
    print("-" * 76)
    print(f"{'Step':<5} | {'Hour':<6} | {'Solar':<7} | {'Demand':<7} | {'Tariff':<8} | {'Status'}")
    print("-" * 76)
    for k in range(horizon):
        h = (start_hour + k) % 24
        rate = TOUTariff.get_import_rate(h)
        print(f"{k+1:<5} | {h:02d}:00  | {solar_fc[k]:<7.2f} | {demand_fc[k]:<7.2f} | Rs. {rate:<3.1f} | {'Peak' if rate == 8.0 else 'Normal'}")
    print("-" * 76)

    res = planner.plan(
        start_hour=start_hour,
        initial_soc=initial_soc,
        battery_capacity=battery_cap,
        solar_forecast=solar_fc,
        demand_forecast=demand_fc,
    )

    print("\nA* SEARCH EXECUTION METRICS:")
    print(f"  Nodes Expanded:    {res.nodes_expanded}")
    print(f"  Computation Time:  {res.computation_time_ms:.2f} ms")
    print(f"  Search Optimality: {'OPTIMAL (w.r.t. discrete action set, cost function & horizon)' if res.is_optimal else 'Suboptimal'}")
    print(f"  Total Cost g(N):   Rs. {res.total_cost:.2f}")

    print("\nOPTIMAL TRAJECTORY PLAN:")
    print(f"{'Step':<5} | {'Action':<14} | {'Flow (kWh)':<11} | {'SOC (%)':<8} | {'Import':<8} | {'Export':<8} | {'Cost'}")
    print("-" * 76)
    for idx, (act, state) in enumerate(zip(res.actions, res.states[1:])):
        step_h = (start_hour + idx) % 24
        print(
            f"{idx+1:<5} | {act.value:<14} | {state.battery_flow:<+11.2f} | "
            f"{state.battery_soc:<8.1f} | {state.grid_import:<8.2f} | {state.grid_export:<8.2f} | Rs. {state.step_cost:.2f}"
        )
    print("-" * 76)
    print(f"-> RECEDING-HORIZON ACTION COMMITTED: {res.first_action.value} ({res.first_battery_flow:+.2f} kWh)\n")


def compare_greedy_vs_astar(scenario_name: str = "baseline", horizon: int = 12) -> None:
    """Execute side-by-side 24-hour simulation comparing Greedy baseline vs A* Planning."""
    runner = ScenarioRunner()

    print("=" * 86)
    print(f"24-HOUR BENCHMARK: GREEDY BASELINE vs A* LOCAL PLANNING")
    print(f"Scenario: {scenario_name.upper()} | Lookahead Horizon: {horizon} Hours")
    print("=" * 86)

    # 1. Greedy Run
    print("-> Running GREEDY baseline (Immediate reactive battery allocation)...")
    greedy_res = runner.run_24h_scenario(
        scenario_name=scenario_name,
        num_households=3,
        seed=42,
        planning_mode="GREEDY",
    )

    # 2. A* Run
    print("-> Running A* PREDICTIVE planning (Decentralized receding-horizon optimization)...")
    astar_res = runner.run_24h_scenario(
        scenario_name=scenario_name,
        num_households=3,
        seed=42,
        planning_mode="A_STAR",
        planning_horizon=horizon,
    )

    # Compute Peak Hour Grid Imports (17:00 to 20:00)
    greedy_peak_import = round(sum(r["grid_import"] for r in greedy_res.hourly_records if 17 <= r["hour"] < 21), 2)
    astar_peak_import = round(sum(r["grid_import"] for r in astar_res.hourly_records if 17 <= r["hour"] < 21), 2)

    cost_saving = greedy_res.total_energy_cost - astar_res.total_energy_cost
    pct_saving = (cost_saving / greedy_res.total_energy_cost * 100.0) if greedy_res.total_energy_cost > 0 else 0.0

    def verdict(delta: float, lower_is_better: bool, unit: str, tol: float = 0.005) -> str:
        """Describe a change honestly: the label is derived from the sign of the delta."""
        if abs(delta) <= tol:
            return "no change"
        improved = (delta < 0) if lower_is_better else (delta > 0)
        return f"{delta:+.2f} {unit} ({'better' if improved else 'WORSE'})"

    g, a = greedy_res, astar_res
    rows = [
        ("Total Electricity Demand (kWh)", g.total_energy_demand_kwh, a.total_energy_demand_kwh, "no change (input)"),
        ("Total Solar Generated (kWh)", g.total_solar_generation_kwh, a.total_solar_generation_kwh, "no change (input)"),
        ("P2P Energy Traded (kWh)", g.total_p2p_energy_traded_kwh, a.total_p2p_energy_traded_kwh,
         verdict(a.total_p2p_energy_traded_kwh - g.total_p2p_energy_traded_kwh, False, "kWh")),
        ("Total Grid Import (kWh)", g.total_grid_import_kwh, a.total_grid_import_kwh,
         verdict(a.total_grid_import_kwh - g.total_grid_import_kwh, True, "kWh")),
        ("Peak-Hour Import (17-21h) (kWh)", greedy_peak_import, astar_peak_import,
         verdict(astar_peak_import - greedy_peak_import, True, "kWh")),
        ("Unmet Demand (kWh)", g.total_unmet_demand_kwh, a.total_unmet_demand_kwh,
         verdict(a.total_unmet_demand_kwh - g.total_unmet_demand_kwh, True, "kWh")),
        ("Average Battery SOC (%)", g.avg_battery_soc, a.avg_battery_soc,
         f"{a.avg_battery_soc - g.avg_battery_soc:+.1f} %"),
        ("Total TOU Electricity Cost (Rs.)", g.total_energy_cost, a.total_energy_cost,
         verdict(a.total_energy_cost - g.total_energy_cost, True, "Rs")),
    ]

    print("\n" + "=" * 86)
    print(f"{'Performance Metric':<34} | {'GREEDY Baseline':<15} | {'A* Predictive':<15} | {'Change (A* - Greedy)'}")
    print("-" * 86)
    for label, gv, av, change in rows:
        print(f"{label:<34} | {gv:<15.2f} | {av:<15.2f} | {change}")
    print("=" * 86)

    if abs(cost_saving) <= 0.005:
        cost_line = "A* and Greedy have the same total electricity cost"
    elif cost_saving > 0:
        cost_line = f"A* reduced total electricity cost by Rs. {cost_saving:.2f} ({pct_saving:.1f}%)"
    else:
        cost_line = f"A* INCREASED total electricity cost by Rs. {-cost_saving:.2f} ({-pct_saving:.1f}%)"
    unmet_delta = a.total_unmet_demand_kwh - g.total_unmet_demand_kwh
    if abs(unmet_delta) > 0.005:
        cost_line += f"; unmet demand {'fell' if unmet_delta < 0 else 'ROSE'} by {abs(unmet_delta):.2f} kWh"
    print(f"CONCLUSION: {cost_line}.")
    if g.grid_outage_duration_hours > 0:
        print("NOTE: energy that could not be served during the outage is not billed, so compare")
        print("      'Unmet Demand' alongside cost in outage scenarios.")
    print("=" * 86 + "\n")


def horizon_study(scenario_name: str = "baseline") -> None:
    """Compare Greedy against A* at several lookahead horizons (justifies H = 12)."""
    runner = ScenarioRunner()
    greedy = runner.run_24h_scenario(scenario_name=scenario_name, planning_mode="GREEDY")
    print("=" * 86)
    print(f"HORIZON STUDY: scenario {scenario_name.upper()} (3 households, 24 h)")
    print("=" * 86)
    print(f"{'Policy':<16} | {'Cost (Rs.)':<11} | {'Saving':<10} | {'Unmet (kWh)':<11} | {'Nodes / day':<11} | {'Planner time'}")
    print("-" * 86)
    print(f"{'Greedy':<16} | {greedy.total_energy_cost:<11.2f} | {'-':<10} | {greedy.total_unmet_demand_kwh:<11.2f} | {'-':<11} | -")
    import time
    for h in (3, 6, 12, 24):
        t0 = time.perf_counter()
        res = runner.run_24h_scenario(scenario_name=scenario_name, planning_mode="A_STAR", planning_horizon=h)
        elapsed = time.perf_counter() - t0
        nodes = sum(r["total_nodes_expanded"] for r in res.hourly_records)
        pct = (greedy.total_energy_cost - res.total_energy_cost) / greedy.total_energy_cost * 100.0
        print(f"{f'A* (H = {h:>2} h)':<16} | {res.total_energy_cost:<11.2f} | {f'{pct:+.1f}%':<10} | "
              f"{res.total_unmet_demand_kwh:<11.2f} | {nodes:<11} | {elapsed:.2f} s")
    print("=" * 86 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Grid MAS - Module 4 A* Local Planning")
    parser.add_argument(
        "--scenario",
        type=str,
        default="baseline",
        choices=["baseline", "real_world_dataset", "cloud_cover", "peak_demand", "grid_outage", "combined"],
        help="Scenario to evaluate (default: baseline)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=12,
        choices=[3, 6, 12, 24],
        help="Planning lookahead horizon in hours (default: 12)",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Display A* search node expansion and optimal trajectory trace",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        default=True,
        help="Run side-by-side benchmark comparing Greedy baseline vs A* Planning (default: True)",
    )

    parser.add_argument(
        "--horizon-study",
        action="store_true",
        help="Compare Greedy vs A* at horizons 3, 6, 12 and 24 hours for the chosen scenario",
    )

    args = parser.parse_args()

    if args.horizon_study:
        horizon_study(args.scenario)
        return

    print_tou_schedule()

    if args.trace:
        print_single_agent_plan_trace(horizon=args.horizon)

    if args.compare:
        compare_greedy_vs_astar(scenario_name=args.scenario, horizon=args.horizon)


if __name__ == "__main__":
    main()
