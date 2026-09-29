"""Smart Grid Multi-Agent System - Module 2 Simulation Runner.

Demonstrates Decentralized Peer-to-Peer (P2P) Energy Negotiation,
Direct Energy Trading, Contract-Net message flows, and Before/After Grid Relief Comparison.
"""

import sys
import argparse
from typing import List, Dict, Any
from smart_grid_mas.environment.smart_grid_model import SmartGridModel
from smart_grid_mas.energy.energy_state import EnergyState


# Deterministic Demo Configurations
DEMO_HOUSEHOLD_CONFIGS = [
    {
        "agent_id": "Household A",
        "solar_generation": 6.0,
        "household_demand": 3.0,
        "battery_capacity": 10.0,
        "battery_soc": 100.0,  # Battery sufficiently charged: 3.0 kWh surplus available for P2P
        "max_p2p_buy_price": 6.0,
        "preferred_p2p_sell_price": 5.0,
    },
    {
        "agent_id": "Household B",
        "solar_generation": 2.0,
        "household_demand": 5.0,
        "battery_capacity": 10.0,
        "battery_soc": 0.0,    # Battery empty: 3.0 kWh deficit needs external energy
        "max_p2p_buy_price": 6.0,
        "preferred_p2p_sell_price": 5.0,
    },
    {
        "agent_id": "Household C",
        "solar_generation": 4.0,
        "household_demand": 4.0,
        "battery_capacity": 10.0,
        "battery_soc": 70.0,   # Generation matches demand: BALANCED
        "max_p2p_buy_price": 6.0,
        "preferred_p2p_sell_price": 5.0,
    },
]


def print_negotiation_trace(model: SmartGridModel, step_num: int) -> None:
    """Print readable terminal output detailing the P2P negotiation lifecycle."""
    print("=" * 60)
    print(f"P2P NEGOTIATION -- TIME STEP {step_num}")
    print("=" * 60)

    # Initial Household Observation
    for agent in model.household_agents:
        if agent.state == EnergyState.SURPLUS:
            print(f"{agent.agent_id}")
            print(f"  State: {agent.state.value}")
            print(f"  Available Surplus: {agent.available_surplus + agent.p2p_energy_sold:.2f} kWh")
            print()
        elif agent.state == EnergyState.DEFICIT:
            print(f"{agent.agent_id}")
            print(f"  State: {agent.state.value}")
            print(f"  Remaining Deficit: {agent.remaining_deficit + agent.p2p_energy_bought:.2f} kWh")
            print()

    # Step Trades & Negotiation Lifecycle
    trades = model.step_trades
    if trades:
        for t in trades:
            print("-" * 60)
            print("REQUEST")
            print("-" * 60)
            buyer = model.get_agent_by_id(t.buyer_id)
            max_price = buyer.max_p2p_buy_price if buyer else 6.0
            print(f"{t.buyer_id}")
            print(f"  -> {t.seller_id}")
            print(f"  REQUEST: {t.energy_amount:.2f} kWh")
            print(f"  Maximum Price: Rs. {max_price:.2f}/kWh")
            print()

            print("-" * 60)
            print("OFFER")
            print("-" * 60)
            print(f"{t.seller_id}")
            print(f"  -> {t.buyer_id}")
            print(f"  OFFER: {t.energy_amount:.2f} kWh")
            print(f"  Price: Rs. {t.price_per_kwh:.2f}/kWh")
            print(f"  Total: Rs. {t.total_price:.2f}")
            print()

            print("-" * 60)
            print("NEGOTIATION DECISION")
            print("-" * 60)
            print(f"{t.buyer_id}:")
            print("  OFFER ACCEPTED")
            print("Reason:")
            print(f"  Price Rs. {t.price_per_kwh:.2f}/kWh <= maximum Rs. {max_price:.2f}/kWh")
            print()

            print("-" * 60)
            print("P2P TRADE")
            print("-" * 60)
            print(f"Seller: {t.seller_id}")
            print(f"Buyer : {t.buyer_id}")
            print()
            print(f"Energy: {t.energy_amount:.2f} kWh")
            print(f"Price : Rs. {t.price_per_kwh:.2f}/kWh")
            print(f"Value : Rs. {t.total_price:.2f}")
            print()
            print(f"Status: {t.status.value}")
            print()
    else:
        print("-" * 60)
        print("P2P TRADING")
        print("-" * 60)
        print("No P2P trades concluded in this timestep (supply/demand balanced locally or no surplus available).")
        print()

    # Energy Impact
    print("-" * 60)
    print("ENERGY IMPACT")
    print("-" * 60)
    for agent in model.household_agents:
        if agent.state == EnergyState.SURPLUS:
            print(f"{agent.agent_id} remaining surplus: {agent.available_surplus:.2f} kWh")
        elif agent.state == EnergyState.DEFICIT:
            print(f"{agent.agent_id} remaining deficit: {agent.remaining_deficit:.2f} kWh")

    print(f"Utility Grid Import: {model.utility_grid.current_step_import:.2f} kWh")
    print(f"Utility Grid Export: {model.utility_grid.current_step_export:.2f} kWh")
    print()

    # Neighborhood Summary
    telemetry = model.latest_telemetry or {}
    print("-" * 60)
    print("NEIGHBORHOOD SUMMARY")
    print("-" * 60)
    print(f"Total Solar Generation : {telemetry.get('total_solar_generation', 0.0):.1f} kW")
    print(f"Total Demand           : {telemetry.get('total_demand', 0.0):.1f} kW")
    print(f"Total Surplus          : {telemetry.get('total_surplus', 0.0):.1f} kW")
    print(f"Total Deficit          : {telemetry.get('total_deficit', 0.0):.1f} kW")
    print(f"P2P Energy Traded      : {telemetry.get('p2p_energy_traded', 0.0):.2f} kWh")
    print(f"P2P Trade Count        : {telemetry.get('p2p_trade_count', 0)}")
    print(f"P2P Trade Value        : Rs. {telemetry.get('p2p_trade_value', 0.0):.2f}")
    print(f"P2P Deficit Coverage   : {telemetry.get('p2p_deficit_coverage_percent', 0.0):.1f}%")
    print(f"Grid Import            : {telemetry.get('grid_import', 0.0):.2f} kWh")
    print(f"Grid Export            : {telemetry.get('grid_export', 0.0):.2f} kWh")
    print("=" * 60)
    print()


def run_comparison() -> None:
    """Execute Before/After comparison demonstrating the impact of P2P energy trading."""
    print("\n" + "#" * 60)
    print("BEFORE / AFTER COMPARISON: P2P TRADING IMPACT")
    print("#" * 60)
    print("Running identical deterministic scenario under two conditions:\n")

    # Scenario A: P2P Disabled (Baseline)
    model_baseline = SmartGridModel(num_households=3, household_configs=DEMO_HOUSEHOLD_CONFIGS, enable_p2p=False)
    tel_base = model_baseline.step()

    # Scenario B: P2P Enabled (Module 2)
    model_p2p = SmartGridModel(num_households=3, household_configs=DEMO_HOUSEHOLD_CONFIGS, enable_p2p=True)
    tel_p2p = model_p2p.step()

    print(f"{'Metric':<32} | {'Scenario A (P2P Disabled)':<25} | {'Scenario B (P2P Enabled)':<25}")
    print("-" * 88)
    print(f"{'P2P Energy Traded':<32} | {tel_base['p2p_energy_traded']:>18.2f} kWh | {tel_p2p['p2p_energy_traded']:>18.2f} kWh")
    print(f"{'P2P Trade Count':<32} | {tel_base['p2p_trade_count']:>22} | {tel_p2p['p2p_trade_count']:>22}")
    print(f"{'P2P Trade Value':<32} | {'Rs. ' + str(tel_base['p2p_trade_value']):>22} | {'Rs. ' + str(tel_p2p['p2p_trade_value']):>22}")
    print(f"{'Utility Grid Import':<32} | {tel_base['grid_import']:>18.2f} kWh | {tel_p2p['grid_import']:>18.2f} kWh")
    print(f"{'Utility Grid Export':<32} | {tel_base['grid_export']:>18.2f} kWh | {tel_p2p['grid_export']:>18.2f} kWh")
    print(f"{'Deficit Coverage by P2P':<32} | {tel_base['p2p_deficit_coverage_percent']:>21.1f}% | {tel_p2p['p2p_deficit_coverage_percent']:>21.1f}%")
    print("-" * 88)

    import_reduction = tel_base['grid_import'] - tel_p2p['grid_import']
    pct_reduction = (import_reduction / tel_base['grid_import'] * 100.0) if tel_base['grid_import'] > 0 else 0.0
    print(f"[CONCLUSION] P2P trading reduced external grid import by {import_reduction:.2f} kWh ({pct_reduction:.1f}% reduction).")
    print("#" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Grid MAS Simulation (Modules 1, 2, and 3)")
    parser.add_argument("--steps", type=int, default=1, help="Number of discrete timesteps to simulate (default: 1)")
    parser.add_argument("--households", type=int, default=3, help="Number of household agents (default: 3)")
    parser.add_argument("--no-p2p", action="store_true", help="Disable P2P negotiation (run baseline)")
    parser.add_argument("--compare", action="store_true", help="Run Before/After P2P trading comparison")
    parser.add_argument("--scenario", type=str, choices=["baseline", "cloud_cover", "peak_demand", "grid_outage", "combined"], help="Run 24-hour dynamic scenario (Module 3)")
    parser.add_argument("--compare-scenarios", action="store_true", help="Run and compare all 5 Module 3 dynamic scenarios")
    args = parser.parse_args()

    if args.compare_scenarios:
        from run_scenario import run_all_scenarios_comparison
        run_all_scenarios_comparison(num_households=args.households, seed=42)
        return

    if args.scenario:
        from run_scenario import run_single_scenario
        run_single_scenario(scenario_name=args.scenario, num_households=args.households, seed=42)
        return

    if args.compare:
        run_comparison()
        return

    enable_p2p = not args.no_p2p
    mode_str = "ENABLED" if enable_p2p else "DISABLED (Baseline)"
    print(f"\n[INFO] Initializing Smart Grid Multi-Agent System [P2P Negotiation: {mode_str}]...")
    print(f"[INFO] Configuration: {args.households} Autonomous Household Agents, simulating {args.steps} discrete timesteps.\n")

    # Use demo configs for 3 households, or dynamic configs for scalable tests
    configs = DEMO_HOUSEHOLD_CONFIGS if args.households == 3 else None
    model = SmartGridModel(num_households=args.households, household_configs=configs, enable_p2p=enable_p2p)

    for step_idx in range(1, args.steps + 1):
        model.step()
        print_negotiation_trace(model, step_idx)

    print("[SUCCESS] Simulation completed successfully.")
    print(f"Cumulative P2P Volume : {sum(t.energy_amount for t in model.trade_history):.2f} kWh")
    print(f"Cumulative P2P Value  : Rs. {sum(t.total_price for t in model.trade_history):.2f}")
    print(f"Cumulative Grid Import: {model.utility_grid.total_imported:.2f} kWh")
    print(f"Cumulative Grid Export: {model.utility_grid.total_exported:.2f} kWh\n")


if __name__ == "__main__":
    main()
