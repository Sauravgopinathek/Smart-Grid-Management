import unittest
from smart_grid_mas.scenarios.profiles import SolarGenerationProfile, HouseholdDemandProfile
from smart_grid_mas.scenarios.shocks import CloudCoverShock, PeakDemandShock, GridOutageShock
from smart_grid_mas.scenarios.scenario_runner import ScenarioRunner, ScenarioResult
from smart_grid_mas.environment.smart_grid_model import SmartGridModel
from smart_grid_mas.energy.energy_state import EnergyState


class TestScenariosAndEnvironmentalShocks(unittest.TestCase):
    """Test suite verifying Module 3: Dynamic Environmental Shocks & Scenario Framework."""

    def setUp(self):
        self.runner = ScenarioRunner()
        self.solar_profile = SolarGenerationProfile(base_peak_kw=6.0)
        self.demand_profile = HouseholdDemandProfile()

    def test_01_solar_profile_changes_across_hours(self):
        """Test 1: Solar profile varies dynamically across the 24 hours."""
        solar_0 = self.solar_profile.get_solar(0)
        solar_6 = self.solar_profile.get_solar(6)
        solar_12 = self.solar_profile.get_solar(12)
        solar_18 = self.solar_profile.get_solar(18)
        solar_23 = self.solar_profile.get_solar(23)

        self.assertEqual(solar_0, 0.0)
        self.assertAlmostEqual(solar_6, 0.0)
        self.assertEqual(solar_12, 6.0)  # Peak at midday
        self.assertAlmostEqual(solar_18, 0.0)
        self.assertEqual(solar_23, 0.0)
        self.assertGreater(solar_12, solar_0)

    def test_02_demand_profile_changes_across_hours(self):
        """Test 2: Demand profile varies dynamically across the 24 hours."""
        demand_night = self.demand_profile.get_demand(3)
        demand_morning = self.demand_profile.get_demand(8)
        demand_evening = self.demand_profile.get_demand(19)

        self.assertLess(demand_night, demand_morning)
        self.assertLess(demand_morning, demand_evening)
        self.assertGreater(demand_evening, 4.0)

    def test_03_cloud_shock_reduces_solar_generation(self):
        """Test 3: CloudCoverShock attenuates solar generation during event."""
        shock = CloudCoverShock(start_hour=12, duration_hours=2, reduction_factor=0.4)
        normal_solar = self.solar_profile.get_solar(12)
        shocked_solar = shock.modify_solar(12, normal_solar)

        self.assertEqual(normal_solar, 6.0)
        self.assertEqual(shocked_solar, 2.4)  # 6.0 * 0.4 = 2.4 kW

    def test_04_solar_generation_returns_after_cloud_shock(self):
        """Test 4: Solar generation returns to normal curve once cloud event terminates."""
        shock = CloudCoverShock(start_hour=12, duration_hours=2, reduction_factor=0.4)
        # Hour 14 is after the 2-hour shock (12:00, 13:00)
        normal_solar_14 = self.solar_profile.get_solar(14)
        post_shock_solar_14 = shock.modify_solar(14, normal_solar_14)

        self.assertEqual(normal_solar_14, post_shock_solar_14)
        self.assertFalse(shock.is_active(14))

    def test_05_peak_demand_shock_increases_demand(self):
        """Test 5: PeakDemandShock amplifies household load during evening hours."""
        shock = PeakDemandShock(start_hour=17, duration_hours=3, demand_multiplier=1.5)
        normal_demand_18 = self.demand_profile.get_demand(18)
        shocked_demand_18 = shock.modify_demand(18, normal_demand_18)

        self.assertGreater(shocked_demand_18, normal_demand_18)
        self.assertAlmostEqual(shocked_demand_18, normal_demand_18 * 1.5, places=1)

    def test_06_demand_returns_after_peak_shock(self):
        """Test 6: Demand returns to baseline profile after peak shock expires."""
        shock = PeakDemandShock(start_hour=17, duration_hours=3, demand_multiplier=1.5)
        normal_demand_21 = self.demand_profile.get_demand(21)
        post_shock_demand = shock.modify_demand(21, normal_demand_21)

        self.assertEqual(normal_demand_21, post_shock_demand)
        self.assertFalse(shock.is_active(21))

    def test_07_grid_outage_disables_grid_import(self):
        """Test 7: During a GridOutageShock, UtilityGrid refuses energy imports."""
        shock = GridOutageShock(start_hour=18, duration_hours=2)
        self.assertFalse(shock.is_grid_available(18))

        configs = [{"agent_id": "H1", "solar_generation": 0.0, "household_demand": 5.0, "battery_soc": 0.0}]
        m = SmartGridModel(num_households=1, household_configs=configs, enable_p2p=False)
        m.utility_grid.set_availability(False)

        telemetry = m.step()
        self.assertEqual(telemetry["grid_import"], 0.0)
        self.assertEqual(m.utility_grid.current_step_import, 0.0)

    def test_08_grid_outage_disables_grid_export(self):
        """Test 8: During a GridOutageShock, UtilityGrid refuses surplus exports."""
        configs = [{"agent_id": "H1", "solar_generation": 8.0, "household_demand": 2.0, "battery_soc": 100.0}]
        m = SmartGridModel(num_households=1, household_configs=configs, enable_p2p=False)
        m.utility_grid.set_availability(False)

        telemetry = m.step()
        self.assertEqual(telemetry["grid_export"], 0.0)
        self.assertEqual(m.utility_grid.current_step_export, 0.0)

    def test_09_unmet_demand_recorded_during_insufficient_supply(self):
        """Test 9: When battery and grid cannot supply load, unmet demand is recorded."""
        configs = [{"agent_id": "H1", "solar_generation": 0.0, "household_demand": 4.0, "battery_soc": 0.0}]
        m = SmartGridModel(num_households=1, household_configs=configs, enable_p2p=False)
        m.utility_grid.set_availability(False)

        telemetry = m.step()
        self.assertEqual(telemetry["unmet_demand"], 4.0)
        agent = m.get_agent_by_id("H1")
        self.assertEqual(agent.unmet_demand, 4.0)

    def test_10_grid_availability_returns_after_outage(self):
        """Test 10: Grid availability is restored after outage shock window ends."""
        shock = GridOutageShock(start_hour=18, duration_hours=2)
        self.assertFalse(shock.is_grid_available(18))
        self.assertFalse(shock.is_grid_available(19))
        self.assertTrue(shock.is_grid_available(20))

    def test_11_battery_state_persists_between_timesteps(self):
        """Test 11: Battery SOC updates across sequential dynamic timesteps."""
        res = self.runner.run_24h_scenario("baseline", num_households=3, seed=42)
        self.assertEqual(len(res.hourly_records), 24)

        # Solar charges battery during midday, night discharges it
        socs = [r["average_battery_soc"] for r in res.hourly_records]
        midday_soc = socs[13]
        early_soc = socs[3]
        self.assertGreater(midday_soc, early_soc)

    def test_12_p2p_negotiation_operates_under_dynamic_conditions(self):
        """Test 12: Autonomous P2P trades occur under dynamic solar/demand fluctuations."""
        res = self.runner.run_24h_scenario("baseline", num_households=3, seed=42)
        self.assertGreater(res.total_p2p_energy_traded_kwh, 0.0)

    def test_13_deterministic_reproducibility_with_seed(self):
        """Test 13: Running with the same seed produces identical results."""
        run1 = self.runner.run_24h_scenario("combined", num_households=3, seed=123)
        run2 = self.runner.run_24h_scenario("combined", num_households=3, seed=123)

        self.assertEqual(run1.total_solar_generation_kwh, run2.total_solar_generation_kwh)
        self.assertEqual(run1.total_energy_demand_kwh, run2.total_energy_demand_kwh)
        self.assertEqual(run1.total_p2p_energy_traded_kwh, run2.total_p2p_energy_traded_kwh)
        self.assertEqual(run1.total_grid_import_kwh, run2.total_grid_import_kwh)

    def test_14_baseline_scenario_completes_24_timesteps(self):
        """Test 14: Baseline scenario runs all 24 hours without errors."""
        res = self.runner.run_24h_scenario("baseline", num_households=3)
        self.assertEqual(len(res.hourly_records), 24)
        self.assertEqual(res.grid_outage_duration_hours, 0)
        self.assertEqual(res.total_unmet_demand_kwh, 0.0)

    def test_15_cloud_scenario_completes_24_timesteps(self):
        """Test 15: Cloud Cover scenario runs all 24 hours with reduced solar."""
        res_base = self.runner.run_24h_scenario("baseline", num_households=3)
        res_cloud = self.runner.run_24h_scenario("cloud_cover", num_households=3)

        self.assertEqual(len(res_cloud.hourly_records), 24)
        self.assertLess(res_cloud.total_solar_generation_kwh, res_base.total_solar_generation_kwh)

    def test_16_peak_demand_scenario_completes_24_timesteps(self):
        """Test 16: Peak Demand scenario runs all 24 hours with increased demand."""
        res_base = self.runner.run_24h_scenario("baseline", num_households=3)
        res_peak = self.runner.run_24h_scenario("peak_demand", num_households=3)

        self.assertEqual(len(res_peak.hourly_records), 24)
        self.assertGreater(res_peak.total_energy_demand_kwh, res_base.total_energy_demand_kwh)

    def test_17_grid_outage_scenario_completes_24_timesteps(self):
        """Test 17: Grid Outage scenario runs all 24 hours and records outage duration."""
        res_outage = self.runner.run_24h_scenario("grid_outage", num_households=3)
        self.assertEqual(len(res_outage.hourly_records), 24)
        self.assertEqual(res_outage.grid_outage_duration_hours, 2)

    def test_18_combined_stress_scenario_completes_successfully(self):
        """Test 18: Combined Stress scenario executes all shocks concurrently."""
        res_combined = self.runner.run_24h_scenario("combined", num_households=3)
        self.assertEqual(len(res_combined.hourly_records), 24)
        self.assertEqual(res_combined.grid_outage_duration_hours, 2)

    def test_19_no_negative_battery_soc(self):
        """Test 19: Battery SOC never falls below 0.0% across all 24 hours."""
        res = self.runner.run_24h_scenario("combined", num_households=3)
        self.assertGreaterEqual(res.min_battery_soc, 0.0)

    def test_20_battery_soc_never_exceeds_100_percent(self):
        """Test 20: Battery SOC never exceeds 100.0% across all 24 hours."""
        res = self.runner.run_24h_scenario("combined", num_households=3)
        for r in res.hourly_records:
            self.assertLessEqual(r["average_battery_soc"], 100.0)

    def test_21_no_negative_solar_generation(self):
        """Test 21: Solar generation is strictly non-negative at every hour."""
        for h in range(24):
            self.assertGreaterEqual(self.solar_profile.get_solar(h), 0.0)

    def test_22_no_negative_demand(self):
        """Test 22: Household demand is strictly positive at every hour."""
        for h in range(24):
            self.assertGreater(self.demand_profile.get_demand(h), 0.0)

    def test_23_existing_module_1_tests_intact(self):
        """Test 23: Verification of Module 1 compatibility."""
        m = SmartGridModel(num_households=3)
        self.assertEqual(m.num_households, 3)

    def test_24_existing_module_2_negotiation_intact(self):
        """Test 24: Verification of Module 2 P2P trading compatibility."""
        m = SmartGridModel(num_households=3, enable_p2p=True)
        tel = m.step()
        self.assertIn("p2p_energy_traded", tel)


if __name__ == "__main__":
    unittest.main()
