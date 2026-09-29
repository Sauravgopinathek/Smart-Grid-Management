"""Convert dashboard_data.json (from export_dashboard_data.py) to dashboard_data.js.

Transforms the simulation telemetry into the exact format the dashboard.html expects:
  window.GRID_DATA = {
    scenario_name: {
      greedy: { metrics: {...}, hourly: [{...}, ...] },
      astar:  { metrics: {...}, hourly: [{...}, ...] }
    }, ...
  }
"""
import json
import sys

with open("dashboard_data.json", "r") as f:
    raw = json.load(f)


def map_shock(active_shocks):
    """Map the active_shocks list to a shock label string."""
    if not active_shocks:
        return "none"
    for s in active_shocks:
        sl = s.lower()
        if "cloud" in sl:
            return "cloud"
        if "peak" in sl:
            return "peak"
        if "outage" in sl or "blackout" in sl:
            return "outage"
    return "none"


def get_tou_rate(hour):
    """Return TOU import rate matching the dashboard thresholds."""
    if hour < 6:
        return 3.0   # Off-Peak
    elif 17 <= hour < 21:
        return 8.0   # Peak
    else:
        return 5.0   # Normal


def transform_scenario(scenario_data):
    """Transform one scenario's raw data into dashboard format."""
    result = {}
    for mode_key in ["greedy", "astar"]:
        raw_mode = scenario_data[mode_key]
        summary = raw_mode["summary"]

        # Compute savings (only for astar relative to greedy)
        greedy_cost = scenario_data["greedy"]["summary"]["total_cost"]
        this_cost = summary["total_cost"]
        if mode_key == "astar" and greedy_cost > 0:
            savings = round((greedy_cost - this_cost) / greedy_cost * 100, 1)
        else:
            savings = 0

        # Calculate peak-hour import (hours 17, 18, 19, 20)
        peak_import = sum(
            hr_rec.get("grid_import", 0.0)
            for hr_rec in raw_mode["hourly"]
            if 17 <= hr_rec.get("hour", 0) < 21
        )

        metrics = {
            "cost": round(summary["total_cost"], 2),
            "gridImport": round(summary["total_import"], 1),
            "gridExport": round(summary.get("total_export", 0.0), 1),
            "p2pTraded": round(summary["total_p2p"], 1),
            "unmet": round(summary["total_unmet"], 1),
            "savings": max(0, savings),
            "avgSoc": round(summary.get("avg_soc", 0.0), 1),
            "minSoc": round(summary.get("min_soc", 0.0), 1),
            "peakImport": round(peak_import, 2),
        }

        hourly = []
        for hr_rec in raw_mode["hourly"]:
            hour = hr_rec["hour"]
            agents_raw = hr_rec.get("agents", [])

            nodes = []
            for ag in agents_raw:
                nodes.append({
                    "name": ag["agent_id"].replace("Household ", "H"),
                    "fullName": ag["agent_id"],
                    "solar": round(ag.get("solar_generation", 0.0), 2),
                    "demand": round(ag.get("household_demand", 0.0), 2),
                    "soc": round(ag.get("battery_soc", 0.0), 1),
                    "state": ag.get("state", "BALANCED"),
                    "action": ag.get("action", "CONSUME"),
                    "unmet": round(ag.get("unmet_demand", 0.0), 2),
                    "batteryFlow": round(ag.get("planned_battery_flow", 0.0), 2),
                    "p2pBought": round(ag.get("p2p_bought", 0.0), 2),
                    "p2pSold": round(ag.get("p2p_sold", 0.0), 2),
                })

            hourly.append({
                "hour": hour,
                "solar": round(hr_rec.get("total_solar_generation", 0), 2),
                "demand": round(hr_rec.get("total_demand", 0), 2),
                "p2p": round(hr_rec.get("p2p_energy_traded", 0), 2),
                "gridImport": round(hr_rec.get("grid_import", 0), 2),
                "gridExport": round(hr_rec.get("grid_export", 0), 2),
                "unmet": round(hr_rec.get("unmet_demand", 0), 2),
                "avgSoc": round(hr_rec.get("average_battery_soc", 0), 1),
                "touRate": get_tou_rate(hour),
                "shock": map_shock(hr_rec.get("active_shocks", [])),
                "gridAvailable": hr_rec.get("grid_available", True),
                "nodes": nodes,
                "messages": hr_rec.get("messages", []),
                "trades": hr_rec.get("trades", []),
            })

        result[mode_key] = {
            "metrics": metrics,
            "hourly": hourly,
        }

    return result


output = {}
for scenario_name, scenario_data in raw.items():
    output[scenario_name] = transform_scenario(scenario_data)

with open("dashboard_data.js", "w") as f:
    f.write("// Auto-generated from real simulation data\n")
    f.write("// Run: python export_dashboard_data.py && python generate_dashboard_js.py\n")
    f.write("window.GRID_DATA = ")
    json.dump(output, f, indent=2)
    f.write(";\n")

# Summary
for sc, sd in output.items():
    g = sd["greedy"]["metrics"]
    a = sd["astar"]["metrics"]
    print(f"  {sc}: Greedy Rs.{g['cost']:.1f} | A* Rs.{a['cost']:.1f} | "
          f"Savings {a['savings']}% | Hours: {len(sd['greedy']['hourly'])}",
          file=sys.stderr)

print("Generated dashboard_data.js with REAL simulation data", file=sys.stderr)
