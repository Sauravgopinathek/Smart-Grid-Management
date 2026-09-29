"""Smart Grid MAS - Data Export for Interactive Dashboard.

Generates JSON simulation data for the browser-based dashboard.
Runs both GREEDY and A_STAR modes, exports all hourly telemetry with agent-level detail.
"""

import json
import sys
from smart_grid_mas.scenarios.scenario_runner import ScenarioRunner
from smart_grid_mas.planning.cost_function import TOUTariff


def export_simulation_data(scenario_name: str = "baseline", horizon: int = 12) -> dict:
    """Run both GREEDY and A_STAR simulations and return combined data dict."""
    runner = ScenarioRunner()

    greedy_res = runner.run_24h_scenario(
        scenario_name=scenario_name,
        num_households=3,
        seed=42,
        planning_mode="GREEDY",
    )
    astar_res = runner.run_24h_scenario(
        scenario_name=scenario_name,
        num_households=3,
        seed=42,
        planning_mode="A_STAR",
        planning_horizon=horizon,
    )

    # Build TOU tariff schedule
    tou_schedule = []
    for h in range(24):
        tou_schedule.append({
            "hour": h,
            "import_rate": TOUTariff.get_import_rate(h),
            "export_rate": TOUTariff.get_export_rate(h),
            "band": "Off-Peak" if h < 6 else ("Peak" if 17 <= h < 21 else "Normal"),
        })

    return {
        "scenario": scenario_name,
        "horizon": horizon,
        "tou_schedule": tou_schedule,
        "greedy": {
            "hourly": greedy_res.hourly_records,
            "summary": {
                "total_demand": greedy_res.total_energy_demand_kwh,
                "total_solar": greedy_res.total_solar_generation_kwh,
                "total_p2p": greedy_res.total_p2p_energy_traded_kwh,
                "total_import": greedy_res.total_grid_import_kwh,
                "total_export": greedy_res.total_grid_export_kwh,
                "total_unmet": greedy_res.total_unmet_demand_kwh,
                "avg_soc": greedy_res.avg_battery_soc,
                "min_soc": greedy_res.min_battery_soc,
                "total_cost": greedy_res.total_energy_cost,
                "outage_hours": greedy_res.grid_outage_duration_hours,
            },
        },
        "astar": {
            "hourly": astar_res.hourly_records,
            "summary": {
                "total_demand": astar_res.total_energy_demand_kwh,
                "total_solar": astar_res.total_solar_generation_kwh,
                "total_p2p": astar_res.total_p2p_energy_traded_kwh,
                "total_import": astar_res.total_grid_import_kwh,
                "total_export": astar_res.total_grid_export_kwh,
                "total_unmet": astar_res.total_unmet_demand_kwh,
                "avg_soc": astar_res.avg_battery_soc,
                "min_soc": astar_res.min_battery_soc,
                "total_cost": astar_res.total_energy_cost,
                "outage_hours": astar_res.grid_outage_duration_hours,
            },
        },
    }


def main():
    scenarios = ["baseline", "real_world_dataset", "cloud_cover", "peak_demand", "grid_outage", "combined"]
    all_data = {}
    for sc in scenarios:
        print(f"Exporting {sc}...", file=sys.stderr)
        all_data[sc] = export_simulation_data(sc)

    output_path = "dashboard_data.json"
    with open(output_path, "w") as f:
        json.dump(all_data, f, indent=2)
    print(f"Exported to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
