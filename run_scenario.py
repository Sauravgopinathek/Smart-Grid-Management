"""Smart Grid Multi-Agent System - Module 3 Scenario Runner CLI.

Executes dynamic 24-hour scenarios with deterministic environmental shocks:
- Baseline: Normal solar & demand profiles
- Cloud Cover: 60% drop in solar generation at 12:00-14:00
- Peak Demand: 50% evening surge in household load at 17:00-20:00
- Grid Outage: Utility grid blackout & microgrid islanding at 18:00-20:00
- Combined Stress: All three shocks applied concurrently
"""

import sys
import argparse
from typing import List
from smart_grid_mas.scenarios.scenario_runner import ScenarioRunner, ScenarioResult


def run_single_scenario(
    scenario_name: str,
    num_households: int,
    seed: int,
    mode: str = "GREEDY",
    horizon: int = 12,
    rounds: int = 3,
) -> ScenarioResult:
    """Run a single 24-hour scenario and print hourly logs and metrics."""
    runner = ScenarioRunner()
    result = runner.run_24h_scenario(
        scenario_name=scenario_name,
        num_households=num_households,
        seed=seed,
        planning_mode=mode,
        planning_horizon=horizon,
        negotiation_rounds=rounds,
    )
    runner.print_hourly_summary(result)

    # Print in-depth shock event trace for representative hour
    shock_hour_map = {
        "cloud_cover": 12,
        "peak_demand": 17,
        "grid_outage": 18,
        "combined": 18,
        "baseline": 12,
    }
    trace_hour = shock_hour_map.get(scenario_name.lower(), 12)
    runner.print_shock_detail(result, hour=trace_hour)
    return result


def run_all_scenarios_comparison(num_households: int, seed: int) -> None:
    """Execute all 5 scenarios and display side-by-side comparative resilience metrics."""
    runner = ScenarioRunner()
    scenarios = ["baseline", "cloud_cover", "peak_demand", "grid_outage", "combined"]
    results: List[ScenarioResult] = []

    print("\n" + "#" * 96)
    print(f"RUNNING COMPREHENSIVE 24-HOUR SCENARIO SUITE ({num_households} Households, Seed={seed})")
    print("#" * 96)

    for sc in scenarios:
        print(f"-> Executing '{sc.upper()}' scenario...")
        res = runner.run_24h_scenario(scenario_name=sc, num_households=num_households, seed=seed)
        results.append(res)

    print("\n")
    runner.print_comparison_table(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Grid MAS - Module 3 Dynamic Scenario Framework")
    parser.add_argument(
        "--scenario",
        type=str,
        default="combined",
        choices=["baseline", "real_world_dataset", "cloud_cover", "peak_demand", "grid_outage", "combined"],
        help="Specific scenario to execute (default: combined)",
    )
    parser.add_argument(
        "--households",
        type=int,
        default=3,
        help="Number of household agents in microgrid (default: 3)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic reproducibility (default: 42)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="greedy",
        choices=["greedy", "astar"],
        help="Decision mode: 'greedy' (baseline) or 'astar' (predictive planning) (default: greedy)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=12,
        choices=[3, 6, 12, 24],
        help="Planning lookahead horizon in hours (default: 12)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="Maximum P2P negotiation rounds per hour (default: 3; 1 = no renegotiation)",
    )
    parser.add_argument(
        "--compare-all",
        action="store_true",
        help="Run all 5 scenarios and print comprehensive comparison table",
    )

    args = parser.parse_args()

    if args.compare_all:
        run_all_scenarios_comparison(num_households=args.households, seed=args.seed)
    else:
        run_single_scenario(
            scenario_name=args.scenario,
            num_households=args.households,
            seed=args.seed,
            mode=args.mode.upper(),
            horizon=args.horizon,
            rounds=args.rounds,
        )


if __name__ == "__main__":
    main()
