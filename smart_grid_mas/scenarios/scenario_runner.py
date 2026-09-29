from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from smart_grid_mas.environment.smart_grid_model import SmartGridModel
from smart_grid_mas.scenarios.profiles import SolarGenerationProfile, HouseholdDemandProfile, MicrogridDatasetLoader
from smart_grid_mas.scenarios.shocks import BaseShock, CloudCoverShock, PeakDemandShock, GridOutageShock


@dataclass
class ScenarioResult:
    """Encapsulates the simulation outcome and resilience metrics of a 24-hour run."""
    scenario_name: str
    num_households: int
    hourly_records: List[Dict[str, Any]]
    
    # 11 Scenario-Level Resilience Metrics
    total_energy_demand_kwh: float
    total_solar_generation_kwh: float
    total_p2p_energy_traded_kwh: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float
    total_unmet_demand_kwh: float
    p2p_deficit_coverage_percent: float
    min_battery_soc: float
    avg_battery_soc: float
    grid_outage_duration_hours: int
    unmet_demand_timesteps_count: int
    total_energy_cost: float = 0.0
    planning_mode: str = "GREEDY"


class ScenarioRunner:
    """Manages execution of dynamic 24-hour scenario simulations and stress tests."""

    def __init__(
        self,
        solar_profile: Optional[SolarGenerationProfile] = None,
        demand_profile: Optional[HouseholdDemandProfile] = None,
    ) -> None:
        self.solar_profile = solar_profile if solar_profile is not None else SolarGenerationProfile(base_peak_kw=6.0)
        self.demand_profile = demand_profile if demand_profile is not None else HouseholdDemandProfile()

    def build_shocks_for_scenario(self, scenario_name: str) -> List[BaseShock]:
        """Factory method configuring shocks for standard named scenarios."""
        name = scenario_name.lower().strip()
        if name in ("baseline", "normal"):
            return []
        elif name in ("cloud_cover", "cloud"):
            return [CloudCoverShock(start_hour=12, duration_hours=2, reduction_factor=0.4)]
        elif name in ("peak_demand", "peak"):
            return [PeakDemandShock(start_hour=17, duration_hours=3, demand_multiplier=1.5)]
        elif name in ("grid_outage", "outage", "blackout"):
            return [GridOutageShock(start_hour=18, duration_hours=2)]
        elif name in ("combined", "combined_stress"):
            return [
                CloudCoverShock(start_hour=12, duration_hours=2, reduction_factor=0.4),
                PeakDemandShock(start_hour=17, duration_hours=3, demand_multiplier=1.5),
                GridOutageShock(start_hour=18, duration_hours=2),
            ]
        elif name in ("real_world_dataset", "dataset", "empirical"):
            return []
        else:
            raise ValueError(f"Unknown scenario name: '{scenario_name}'. Use 'baseline', 'cloud_cover', 'peak_demand', 'grid_outage', 'combined', or 'real_world_dataset'.")

    def run_24h_scenario(
        self,
        scenario_name: str,
        num_households: int = 3,
        seed: int = 42,
        custom_shocks: Optional[List[BaseShock]] = None,
        enable_p2p: bool = True,
        planning_mode: str = "GREEDY",
        planning_horizon: int = 12,
        negotiation_rounds: int = 3,
    ) -> ScenarioResult:
        """Execute a 24-hour simulation under specified environmental conditions."""
        shocks = custom_shocks if custom_shocks is not None else self.build_shocks_for_scenario(scenario_name)

        # Configurable heterogeneous household initial parameters
        configs = []
        for i in range(num_households):
            # Heterogeneous community profile:
            # i % 3 == 0: High Solar Prosumer (surplus exporter)
            # i % 3 == 1: Commercial/High Consumer (deficit buyer)
            # i % 3 == 2: Balanced Microgrid Node
            if i % 3 == 0:
                solar_factor = round(1.3 + (i // 3) * 0.1, 2)
                demand_multiplier = round(0.8 + (i // 3) * 0.05, 2)
                init_soc = 60.0
            elif i % 3 == 1:
                solar_factor = round(0.2 + (i // 3) * 0.05, 2)
                demand_multiplier = round(1.25 + (i // 3) * 0.1, 2)
                init_soc = 20.0
            else:
                solar_factor = round(0.9 + (i // 3) * 0.1, 2)
                demand_multiplier = round(1.0 + (i // 3) * 0.05, 2)
                init_soc = 50.0

            configs.append({
                "agent_id": f"Household {chr(65 + i) if i < 26 else f'H{i+1}'}",
                "solar_generation": 0.0,
                "household_demand": 1.5,
                "battery_capacity": 10.0,
                "battery_soc": init_soc,
                "max_charge_rate_kw": 5.0,
                "max_discharge_rate_kw": 5.0,
                "max_p2p_buy_price": 6.0,
                "preferred_p2p_sell_price": 5.0,
                "_solar_factor": solar_factor,
                "_demand_multiplier": demand_multiplier,
            })

        model = SmartGridModel(
            num_households=num_households,
            household_configs=configs,
            seed=seed,
            enable_p2p=enable_p2p,
            planning_mode=planning_mode,
            planning_horizon=planning_horizon,
            max_negotiation_rounds=negotiation_rounds,
        )

        hourly_records: List[Dict[str, Any]] = []

        # Run 24 discrete hourly timesteps (00:00 to 23:00)
        for hour in range(24):
            # Check which shocks are currently active
            active_shocks = [s for s in shocks if s.is_active(hour)]
            model.active_shocks = [s.name for s in active_shocks]

            # Update Grid availability: if any GridOutageShock is active, grid is offline
            grid_outage_active = any(isinstance(s, GridOutageShock) and s.is_active(hour) for s in active_shocks)
            model.utility_grid.set_availability(not grid_outage_active)

            # Determine if empirical dataset mode is active
            is_dataset_scenario = scenario_name.lower().strip() in ("real_world_dataset", "dataset", "empirical")
            if is_dataset_scenario and not hasattr(self, "_dataset_loader"):
                self._dataset_loader = MicrogridDatasetLoader()

            # Update external environment inputs for each agent
            for i, agent in enumerate(model.household_agents):
                s_factor = configs[i]["_solar_factor"]
                d_mult = configs[i]["_demand_multiplier"]

                if is_dataset_scenario:
                    # Ingest real-world smart meter traces
                    solar_kw = self._dataset_loader.get_agent_solar(hour, i)
                    demand_kw = self._dataset_loader.get_agent_demand(hour, i)
                else:
                    # Base profile readings from physical equations
                    solar_kw = self.solar_profile.get_solar(hour, household_factor=s_factor)
                    demand_kw = self.demand_profile.get_demand(hour, household_multiplier=d_mult)

                # Apply active shocks
                for s in active_shocks:
                    if isinstance(s, CloudCoverShock):
                        solar_kw = s.modify_solar(hour, solar_kw)
                    elif isinstance(s, PeakDemandShock):
                        demand_kw = s.modify_demand(hour, demand_kw)

                agent.update_environment(solar_kw=solar_kw, demand_kw=demand_kw)

                # Feed lookahead forecasts if agent planning is active
                if agent.planning_enabled:
                    if is_dataset_scenario:
                        s_fc = [self._dataset_loader.get_agent_solar((hour + k) % 24, i) for k in range(planning_horizon)]
                        d_fc = [self._dataset_loader.get_agent_demand((hour + k) % 24, i) for k in range(planning_horizon)]
                    else:
                        s_fc = [self.solar_profile.get_solar((hour + k) % 24, household_factor=s_factor) for k in range(planning_horizon)]
                        d_fc = [self.demand_profile.get_demand((hour + k) % 24, household_multiplier=d_mult) for k in range(planning_horizon)]
                    agent.set_forecasts(s_fc, d_fc)

            # Step simulation
            telemetry = model.step()
            hourly_records.append(telemetry)

        # Compute 11 Resilience Metrics across the 24 hours
        total_demand = round(sum(r["total_demand"] for r in hourly_records), 2)
        total_solar = round(sum(r["total_solar_generation"] for r in hourly_records), 2)
        total_p2p = round(sum(r["p2p_energy_traded"] for r in hourly_records), 2)
        total_import = round(sum(r["grid_import"] for r in hourly_records), 2)
        total_export = round(sum(r["grid_export"] for r in hourly_records), 2)
        total_unmet = round(sum(r["unmet_demand"] for r in hourly_records), 2)
        total_deficit = sum(r["total_deficit"] for r in hourly_records)

        coverage = round((total_p2p / total_deficit) * 100.0, 1) if total_deficit > 1e-6 else 100.0
        min_soc = min(r["minimum_battery_soc"] for r in hourly_records)
        avg_soc = round(sum(r["average_battery_soc"] for r in hourly_records) / 24.0, 1)
        outage_hours = sum(1 for r in hourly_records if not r["grid_available"])
        unmet_timesteps = sum(1 for r in hourly_records if r["unmet_demand"] > 1e-6)

        # Calculate total energy cost under TOU tariffs
        from smart_grid_mas.planning.cost_function import TOUTariff
        total_energy_cost = 0.0
        for r in hourly_records:
            h = r["hour"]
            total_energy_cost += (r["grid_import"] * TOUTariff.get_import_rate(h)) - (r["grid_export"] * TOUTariff.get_export_rate(h))
        total_energy_cost = round(total_energy_cost, 2)

        return ScenarioResult(
            scenario_name=scenario_name,
            num_households=num_households,
            hourly_records=hourly_records,
            total_energy_demand_kwh=total_demand,
            total_solar_generation_kwh=total_solar,
            total_p2p_energy_traded_kwh=total_p2p,
            total_grid_import_kwh=total_import,
            total_grid_export_kwh=total_export,
            total_unmet_demand_kwh=total_unmet,
            p2p_deficit_coverage_percent=coverage,
            min_battery_soc=min_soc,
            avg_battery_soc=avg_soc,
            grid_outage_duration_hours=outage_hours,
            unmet_demand_timesteps_count=unmet_timesteps,
            total_energy_cost=total_energy_cost,
            planning_mode=planning_mode,
        )

    @staticmethod
    def print_hourly_summary(result: ScenarioResult) -> None:
        """Print concise 24-hour tabular summary showing dynamic progression and events."""
        print("=" * 86)
        print(f"24-HOUR SIMULATION LOG: SCENARIO '{result.scenario_name.upper()}' ({result.num_households} Households)")
        print("=" * 86)
        print(f"{'Hour':<5} | {'Solar':<7} | {'Demand':<7} | {'P2P':<7} | {'Import':<7} | {'Export':<7} | {'Unmet':<7} | {'Avg SOC':<7} | {'Events / Shocks'}")
        print("-" * 86)

        for r in result.hourly_records:
            h = r["hour"]
            solar = f"{r['total_solar_generation']:.1f} kW"
            demand = f"{r['total_demand']:.1f} kW"
            p2p = f"{r['p2p_energy_traded']:.2f}"
            g_imp = f"{r['grid_import']:.2f}"
            g_exp = f"{r['grid_export']:.2f}"
            unmet = f"{r['unmet_demand']:.2f}"
            soc = f"{r['average_battery_soc']:.1f}%"

            events = []
            if not r["grid_available"]:
                events.append("GRID BLACKOUT")
            if "CloudCoverShock" in r["active_shocks"]:
                events.append("CLOUD COVER")
            if "PeakDemandShock" in r["active_shocks"]:
                events.append("PEAK DEMAND")
            event_str = ", ".join(events) if events else "Normal"

            print(f"{h:02d}:00 | {solar:<7} | {demand:<7} | {p2p:<7} | {g_imp:<7} | {g_exp:<7} | {unmet:<7} | {soc:<7} | {event_str}")

        print("-" * 86)
        print(f"24h Totals: Solar = {result.total_solar_generation_kwh:.1f} kWh | Demand = {result.total_energy_demand_kwh:.1f} kWh | P2P Traded = {result.total_p2p_energy_traded_kwh:.2f} kWh")
        print(f"            Grid Import = {result.total_grid_import_kwh:.2f} kWh | Grid Export = {result.total_grid_export_kwh:.2f} kWh | Unmet Demand = {result.total_unmet_demand_kwh:.2f} kWh")
        print(f"            Battery Avg SOC = {result.avg_battery_soc:.1f}% (Min = {result.min_battery_soc:.1f}%) | Outage = {result.grid_outage_duration_hours}h")
        print("=" * 86 + "\n")

    @staticmethod
    def print_comparison_table(results: List[ScenarioResult]) -> None:
        """Print comparative evaluation table across multiple scenarios."""
        print("=" * 96)
        print("SCENARIO RESILIENCE COMPARISON TABLE (24-Hour Horizon)")
        print("=" * 96)
        headers = [f"{r.scenario_name.title()[:12]:<12}" for r in results]
        header_str = " | ".join(headers)
        print(f"{'Metric':<30} | {header_str}")
        print("-" * 96)

        def print_row(label: str, getter_func):
            vals = [f"{getter_func(r):<12}" for r in results]
            print(f"{label:<30} | " + " | ".join(vals))

        print_row("Total Solar (kWh)", lambda r: f"{r.total_solar_generation_kwh:.1f}")
        print_row("Total Demand (kWh)", lambda r: f"{r.total_energy_demand_kwh:.1f}")
        print_row("P2P Energy Traded (kWh)", lambda r: f"{r.total_p2p_energy_traded_kwh:.2f}")
        print_row("Utility Grid Import (kWh)", lambda r: f"{r.total_grid_import_kwh:.2f}")
        print_row("Utility Grid Export (kWh)", lambda r: f"{r.total_grid_export_kwh:.2f}")
        print_row("Unmet Demand (kWh)", lambda r: f"{r.total_unmet_demand_kwh:.2f}")
        print_row("P2P Deficit Coverage (%)", lambda r: f"{r.p2p_deficit_coverage_percent:.1f}%")
        print_row("Min Battery SOC (%)", lambda r: f"{r.min_battery_soc:.1f}%")
        print_row("Avg Battery SOC (%)", lambda r: f"{r.avg_battery_soc:.1f}%")
        print_row("Outage Duration (hours)", lambda r: f"{r.grid_outage_duration_hours}h")
        print_row("Unmet Demand Hours", lambda r: f"{r.unmet_demand_timesteps_count}h")
        print("=" * 96 + "\n")

    @staticmethod
    def print_shock_detail(result: ScenarioResult, hour: int = 12) -> None:
        """Print in-depth telemetry for a specific shock hour (conforming to Part 18 demo specification)."""
        if hour >= len(result.hourly_records):
            return
        rec = result.hourly_records[hour]
        print("=" * 60)
        print(f"SCENARIO EVENT TRACE: {result.scenario_name.upper()}")
        print("=" * 60)
        print(f"TIME: {hour:02d}:00\n")

        shocks = rec["active_shocks"]
        if "CloudCoverShock" in shocks:
            print("Shock Event:\n  CLOUD COVER ATTENUATION (ACTIVE)")
            print(f"Actual Solar Generation:\n  {rec['total_solar_generation']:.1f} kW (Attenuated)\n")
        elif "PeakDemandShock" in shocks:
            print("Shock Event:\n  EVENING PEAK SURGE (ACTIVE)")
            print(f"Actual Demand:\n  {rec['total_demand']:.1f} kW\n")
        elif not rec["grid_available"]:
            print("Shock Event:\n  UTILITY GRID BLACKOUT (ISLANDED)")
            print("Grid Import:\n  0.00 kW (REJECTED by islanded grid)\n")
        else:
            print(f"Status:\n  NORMAL OPERATION ({rec['total_solar_generation']:.1f} kW solar, {rec['total_demand']:.1f} kW demand)\n")

        # Agents state overview
        for a in rec["agents"][:3]:
            print(f"{a['agent_id']}:")
            print(f"  State: {a['state']}")
            print(f"  Solar: {a['solar_generation']:.1f} kW | Demand: {a['household_demand']:.1f} kW | Battery SOC: {a['battery_soc']:.1f}%")
            if a["p2p_bought"] > 0:
                print(f"  P2P Trade (Bought): {a['p2p_bought']:.2f} kWh")
            if a["p2p_sold"] > 0:
                print(f"  P2P Trade (Sold): {a['p2p_sold']:.2f} kWh")
            if a["unmet_demand"] > 0:
                print(f"  Unmet Demand: {a['unmet_demand']:.2f} kWh (ISLANDED)")
            print()

        print(f"Neighborhood P2P Traded: {rec['p2p_energy_traded']:.2f} kWh")
        print(f"Neighborhood Grid Import: {rec['grid_import']:.2f} kWh")
        print(f"Neighborhood Unmet Demand: {rec['unmet_demand']:.2f} kWh")
        print("=" * 60 + "\n")
