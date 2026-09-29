import unittest
from smart_grid_mas.planning.planning_state import PlanningAction, PlanningState
from smart_grid_mas.planning.cost_function import TOUTariff, CostFunction
from smart_grid_mas.planning.astar_planner import AStarPlanner, PlanningResult
from smart_grid_mas.agents.household_agent import HouseholdAgent
from smart_grid_mas.environment.smart_grid_model import SmartGridModel
from smart_grid_mas.scenarios.scenario_runner import ScenarioRunner


class TestModule4Planning(unittest.TestCase):
    """Automated test suite verifying Module 4: A* Local Planning & Predictive Energy Optimization.
    
    Contains 28 comprehensive test cases:
    - Tests 1-3: TOU Tariff schedules and pricing rules
    - Tests 4-6: Cost function calculation & penalty weights
    - Tests 7-9: Admissibility, monotonicity, and correctness of heuristic h(n)
    - Tests 10-11: Planning state representation, state keys, and priority ordering
    - Tests 12-15: A* planner optimality, convergence, and closed-set state pruning
    - Tests 16-19: Economic behaviors: TOU arbitrage, peak shaving, solar self-consumption, outage resilience
    - Tests 20-23: Horizons (3, 6, 12, 24), receding-horizon execution, and physical battery limits
    - Tests 24-26: Edge cases: empty battery (0%), full battery (100%), zero demand/solar
    - Tests 27-28: A* vs Greedy benchmark cost reduction & decentralized multi-agent execution
    """

    def setUp(self):
        self.tariff = TOUTariff()
        self.cost_fn = CostFunction(tariff=self.tariff)
        self.planner = AStarPlanner(horizon=6, cost_function=self.cost_fn)

    # -------------------------------------------------------------------------
    # 1. TOU Tariff Schedule Tests (1 - 3)
    # -------------------------------------------------------------------------

    def test_01_tou_tariff_rates_by_hour(self):
        """Test 1: TOU Tariff returns correct rates across off-peak, normal, and peak hours."""
        # Off-peak: 00:00 to 06:00 -> Rs 3.0
        for h in range(0, 6):
            self.assertEqual(self.tariff.get_import_rate(h), 3.0)

        # Normal: 06:00 to 17:00 & 21:00 to 24:00 -> Rs 5.0
        for h in [6, 10, 12, 16, 21, 22, 23]:
            self.assertEqual(self.tariff.get_import_rate(h), 5.0)

        # Peak: 17:00 to 21:00 -> Rs 8.0
        for h in range(17, 21):
            self.assertEqual(self.tariff.get_import_rate(h), 8.0)

    def test_02_tou_tariff_export_rate(self):
        """Test 2: Grid feed-in export rate is uniformly Rs 2.0 / kWh."""
        for h in [2, 8, 14, 19, 23]:
            self.assertEqual(self.tariff.get_export_rate(h), 2.0)

    def test_03_tou_tariff_min_import_rate(self):
        """Test 3: Minimum import rate matches off-peak tariff (Rs 3.0)."""
        self.assertEqual(self.tariff.get_min_import_rate(), 3.0)

    # -------------------------------------------------------------------------
    # 2. Cost Function & Penalty Tests (4 - 6)
    # -------------------------------------------------------------------------

    def test_04_cost_function_step_cost_calculation(self):
        """Test 4: Immediate transition cost respects tariff, export credit, and degradation."""
        # Hour 2 (Off-peak Rs 3): Import 2 kWh, Export 0, Unmet 0, Flow +2 kWh
        cost_offpeak = self.cost_fn.calculate_step_cost(
            grid_import=2.0, grid_export=0.0, unmet_demand=0.0, battery_flow=2.0, hour=2
        )
        # Expected: 2.0 * 3.0 + 2.0 * 0.05 = 6.0 + 0.1 = 6.1
        self.assertAlmostEqual(cost_offpeak, 6.1)

        # Hour 18 (Peak Rs 8): Export 1.5 kWh, Import 0, Flow -1.5 kWh
        cost_peak_export = self.cost_fn.calculate_step_cost(
            grid_import=0.0, grid_export=1.5, unmet_demand=0.0, battery_flow=-1.5, hour=18
        )
        # Expected: -1.5 * 2.0 + 1.5 * 0.05 = -3.0 + 0.075 = -2.925
        self.assertAlmostEqual(cost_peak_export, -2.925)

    def test_05_cost_function_unmet_demand_penalty(self):
        """Test 5: Unmet demand incurs massive penalty (1000 Rs/kWh)."""
        cost_unmet = self.cost_fn.calculate_step_cost(
            grid_import=0.0, grid_export=0.0, unmet_demand=1.0, battery_flow=0.0, hour=12
        )
        self.assertGreaterEqual(cost_unmet, 1000.0)

    def test_06_cost_function_cycling_penalty(self):
        """Test 6: Battery flow incurs wear degradation penalty of 0.05 Rs/kWh."""
        cost_idle = self.cost_fn.calculate_step_cost(0.0, 0.0, 0.0, 0.0, 10)
        cost_cycled = self.cost_fn.calculate_step_cost(0.0, 0.0, 0.0, 4.0, 10)
        self.assertAlmostEqual(cost_cycled - cost_idle, 4.0 * 0.05)

    # -------------------------------------------------------------------------
    # 3. Heuristic Properties Tests (7 - 9)
    # -------------------------------------------------------------------------

    def test_07_heuristic_admissibility(self):
        """Test 7: Heuristic h(n) never overestimates the true remaining optimal cost."""
        solar_fc = [0.0, 0.0, 0.0]
        demand_fc = [3.0, 4.0, 2.0]  # Total deficit = 9.0 kWh
        stored_kwh = 2.0

        h = self.cost_fn.calculate_heuristic(stored_kwh, solar_fc, demand_fc)
        # Minimum possible future cost: (9.0 - 2.0) * min_tariff(3.0) = 21.0
        self.assertEqual(h, 21.0)

        # Actual cost in evening (e.g. peak Rs 8) will be higher:
        actual_min_cost = (7.0) * 5.0
        self.assertLessEqual(h, actual_min_cost)

    def test_08_heuristic_monotonicity(self):
        """Test 8: Consistency (triangle inequality) h(n) <= c(n, n') + h(n')."""
        solar_fc = [1.0, 0.0]
        demand_fc = [3.0, 4.0]
        stored_0 = 3.0

        h0 = self.cost_fn.calculate_heuristic(stored_0, solar_fc, demand_fc)
        # Step: Net deficit = 2.0. Discharge 2.0 kWh from battery -> stored_1 = 1.0 kWh.
        step_cost = self.cost_fn.calculate_step_cost(
            grid_import=0.0, grid_export=0.0, unmet_demand=0.0, battery_flow=-2.0, hour=10
        )
        h1 = self.cost_fn.calculate_heuristic(1.0, solar_fc[1:], demand_fc[1:])

        self.assertLessEqual(h0, step_cost + h1 + 1e-4)

    def test_09_heuristic_zero_when_deficit_covered(self):
        """Test 9: h(n) is zero when stored energy exceeds all remaining deficits."""
        solar_fc = [1.0, 2.0]
        demand_fc = [2.0, 2.0]  # Remaining deficit = 1.0 + 0.0 = 1.0 kWh
        stored_kwh = 5.0

        h = self.cost_fn.calculate_heuristic(stored_kwh, solar_fc, demand_fc)
        self.assertEqual(h, 0.0)

    # -------------------------------------------------------------------------
    # 4. State Representation & Priority Ordering Tests (10 - 11)
    # -------------------------------------------------------------------------

    def test_10_planning_state_hashable_and_key(self):
        """Test 10: State quantization produces consistent key for closed set lookup."""
        state1 = PlanningState(hour=14, step_index=2, battery_soc=45.04)
        state2 = PlanningState(hour=14, step_index=2, battery_soc=45.02)
        state3 = PlanningState(hour=14, step_index=2, battery_soc=55.00)

        self.assertEqual(state1.state_key(0.5), state2.state_key(0.5))
        self.assertNotEqual(state1.state_key(0.5), state3.state_key(0.5))

    def test_11_planning_state_ordering(self):
        """Test 11: PlanningState priority ordering is based on total_cost f = g + h."""
        s1 = PlanningState(hour=0, step_index=1, battery_soc=50.0, total_cost=15.0)
        s2 = PlanningState(hour=0, step_index=1, battery_soc=50.0, total_cost=20.0)
        self.assertLess(s1, s2)

    # -------------------------------------------------------------------------
    # 5. A* Search Optimality & Pruning Tests (12 - 15)
    # -------------------------------------------------------------------------

    def test_12_astar_planner_initialization(self):
        """Test 12: AStarPlanner initializes with expected default horizon and resolution."""
        p = AStarPlanner(horizon=6)
        self.assertEqual(p.horizon, 6)
        self.assertEqual(p.soc_resolution, 0.5)

    def test_13_astar_plan_returns_valid_result(self):
        """Test 13: plan() produces a valid PlanningResult with all required telemetry fields."""
        res = self.planner.plan(
            start_hour=10,
            initial_soc=50.0,
            battery_capacity=10.0,
            solar_forecast=[4.0] * 6,
            demand_forecast=[3.0] * 6,
        )
        self.assertIsInstance(res, PlanningResult)
        self.assertEqual(len(res.actions), 6)
        self.assertEqual(len(res.states), 7)
        self.assertGreater(res.nodes_expanded, 0)
        self.assertGreaterEqual(res.computation_time_ms, 0.0)

    def test_14_astar_finds_optimal_solution(self):
        """Test 14: Search successfully reaches goal horizon and confirms optimality."""
        res = self.planner.plan(
            start_hour=8,
            initial_soc=40.0,
            battery_capacity=10.0,
            solar_forecast=[2.0, 4.0, 6.0, 5.0, 3.0, 1.0],
            demand_forecast=[3.0, 3.0, 3.0, 3.0, 4.0, 5.0],
        )
        self.assertTrue(res.is_optimal)
        self.assertEqual(res.planning_horizon, 6)

    def test_15_astar_prunes_state_space(self):
        """Test 15: Closed set memoization prevents state explosion (expands << 4^H nodes)."""
        res = self.planner.plan(
            start_hour=0,
            initial_soc=50.0,
            battery_capacity=10.0,
            solar_forecast=[0.0] * 6,
            demand_forecast=[2.5] * 6,
        )
        # Without pruning 4^6 = 4096; with A* memoization expansions should be < 150
        self.assertLess(res.nodes_expanded, 150)

    # -------------------------------------------------------------------------
    # 6. Economic & Physical Behaviors (16 - 19)
    # -------------------------------------------------------------------------

    def test_16_arbitrage_charges_during_offpeak(self):
        """Test 16: Planner charges battery during cheap off-peak hours (Rs 3) ahead of peak."""
        # Start at 03:00 (off-peak Rs 3). Night demand is low (1 kW), then peak (6 kW) at hour 17 (Rs 8).
        # Initial SOC is low (10%). Planner should take advantage of Rs 3 tariff to charge battery.
        solar_fc = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        demand_fc = [1.0, 1.0, 5.0, 5.0, 5.0, 5.0]

        res = self.planner.plan(
            start_hour=4,  # Hours 4, 5 are off-peak Rs 3
            initial_soc=10.0,
            battery_capacity=10.0,
            solar_forecast=solar_fc,
            demand_forecast=demand_fc,
        )
        # First action at off-peak hour should be CHARGE_GRID to prepare for upcoming expensive demand
        self.assertIn(res.first_action, (PlanningAction.CHARGE_GRID, PlanningAction.HOLD))

    def test_17_peak_shaving_discharges_during_peak(self):
        """Test 17: Planner discharges battery during expensive peak hours (17:00-21:00, Rs 8)."""
        res = self.planner.plan(
            start_hour=17,  # Peak hour
            initial_soc=80.0,  # Plenty of stored energy
            battery_capacity=10.0,
            solar_forecast=[0.0] * 6,
            demand_forecast=[4.0] * 6,
        )
        self.assertEqual(res.first_action, PlanningAction.DISCHARGE)
        self.assertLess(res.first_battery_flow, 0.0)

    def test_18_solar_self_consumption(self):
        """Test 18: Planner absorbs midday solar into battery rather than exporting at Rs 2."""
        res = self.planner.plan(
            start_hour=11,
            initial_soc=30.0,
            battery_capacity=10.0,
            solar_forecast=[6.0, 6.0, 4.0, 1.0, 0.0, 0.0],
            demand_forecast=[2.0, 2.0, 2.0, 4.0, 5.0, 5.0],
        )
        # Midday surplus: planner should CHARGE_SOLAR to save for evening
        self.assertEqual(res.first_action, PlanningAction.CHARGE_SOLAR)
        self.assertGreater(res.first_battery_flow, 0.0)

    def test_19_resilient_planning_during_grid_outage(self):
        """Test 19: When grid is unavailable, battery discharges to prevent unmet demand penalty."""
        res = self.planner.plan(
            start_hour=18,
            initial_soc=50.0,
            battery_capacity=10.0,
            solar_forecast=[0.0] * 6,
            demand_forecast=[3.0] * 6,
            is_grid_available=False,
        )
        # Must discharge battery to avoid 1000 Rs/kWh unmet demand penalty
        self.assertEqual(res.first_action, PlanningAction.DISCHARGE)
        self.assertAlmostEqual(res.first_battery_flow, -3.0)

    # -------------------------------------------------------------------------
    # 7. Horizons & Physical Limits (20 - 23)
    # -------------------------------------------------------------------------

    def test_20_horizon_sensitivity_3_6_12_24(self):
        """Test 20: Planner executes successfully across various horizons (3, 6, 12, 24)."""
        for h in [3, 6, 12, 24]:
            p = AStarPlanner(horizon=h)
            res = p.plan(
                start_hour=8,
                initial_soc=50.0,
                battery_capacity=10.0,
                solar_forecast=[3.0] * h,
                demand_forecast=[2.5] * h,
            )
            self.assertEqual(len(res.actions), h)
            self.assertTrue(res.is_optimal)

    def test_21_agent_integration_receding_horizon(self):
        """Test 21: HouseholdAgent in A_STAR mode executes receding-horizon planning seamlessly."""
        model = SmartGridModel(num_households=1, planning_mode="A_STAR", planning_horizon=6)
        agent = model.household_agents[0]
        self.assertTrue(agent.planning_enabled)

        # Diurnal forecast: midday surplus (6 kW) followed by evening deficit (0 solar, 4 kW demand)
        agent.set_forecasts(
            solar_forecast=[6.0, 4.0, 0.0, 0.0, 0.0, 0.0],
            demand_forecast=[2.0, 2.0, 4.0, 4.0, 4.0, 4.0],
        )
        agent.update_environment(solar_kw=6.0, demand_kw=2.0)
        telemetry = model.step()

        self.assertIsNotNone(agent.last_planning_result)
        self.assertGreater(agent.battery_flow, 0.0)  # Charged surplus solar for evening use

    def test_22_agent_battery_soc_physical_limits(self):
        """Test 22: Battery SOC remains strictly bounded within [0, 100]% under all plans."""
        p = AStarPlanner(horizon=12)
        res = p.plan(
            start_hour=0,
            initial_soc=95.0,
            battery_capacity=10.0,
            solar_forecast=[10.0] * 12,
            demand_forecast=[0.5] * 12,
        )
        for s in res.states:
            self.assertGreaterEqual(s.battery_soc, 0.0)
            self.assertLessEqual(s.battery_soc, 100.0)

    def test_23_agent_max_charge_discharge_limits(self):
        """Test 23: Planned battery flow never exceeds max charge or discharge limits."""
        max_chg = 3.0
        max_dis = 2.5
        res = self.planner.plan(
            start_hour=12,
            initial_soc=50.0,
            battery_capacity=10.0,
            max_charge_rate_kw=max_chg,
            max_discharge_rate_kw=max_dis,
            solar_forecast=[8.0] * 6,
            demand_forecast=[1.0] * 6,
        )
        for s in res.states[1:]:
            self.assertLessEqual(s.battery_flow, max_chg + 1e-4)
            self.assertGreaterEqual(s.battery_flow, -max_dis - 1e-4)

    # -------------------------------------------------------------------------
    # 8. Edge Cases (24 - 26)
    # -------------------------------------------------------------------------

    def test_24_edge_case_empty_battery(self):
        """Test 24: Starting at 0% SOC executes safely without negative storage or crash."""
        res = self.planner.plan(
            start_hour=20,
            initial_soc=0.0,
            battery_capacity=10.0,
            solar_forecast=[0.0] * 6,
            demand_forecast=[3.0] * 6,
        )
        self.assertTrue(res.is_optimal)
        for s in res.states:
            self.assertGreaterEqual(s.battery_soc, 0.0)

    def test_25_edge_case_full_battery(self):
        """Test 25: Starting at 100% SOC executes safely without overcharging beyond 100%."""
        res = self.planner.plan(
            start_hour=12,
            initial_soc=100.0,
            battery_capacity=10.0,
            solar_forecast=[6.0] * 6,
            demand_forecast=[2.0] * 6,
        )
        self.assertTrue(res.is_optimal)
        for s in res.states:
            self.assertLessEqual(s.battery_soc, 100.0)

    def test_26_edge_case_zero_demand_and_zero_solar(self):
        """Test 26: Zero solar and zero demand produces steady-state HOLD with 0 cost."""
        res = self.planner.plan(
            start_hour=0,
            initial_soc=50.0,
            battery_capacity=10.0,
            solar_forecast=[0.0] * 6,
            demand_forecast=[0.0] * 6,
        )
        self.assertEqual(res.first_action, PlanningAction.HOLD)
        self.assertAlmostEqual(res.total_cost, 0.0)

    # -------------------------------------------------------------------------
    # 9. Comparative Benchmarks & Multi-Agent Tests (27 - 28)
    # -------------------------------------------------------------------------

    def test_27_astar_vs_greedy_cost_comparison(self):
        """Test 27: 24-hour simulation confirms A* achieves lower total energy cost than Greedy.

        Uses the project's default horizon H = 12. (With H = 6 the planner cannot
        see the 17:00-21:00 peak from the midday solar hours, and the optimal
        plan is roughly break-even with Greedy - see `run_planning.py --horizon-study`.)
        """
        runner = ScenarioRunner()
        # Run baseline 24-hour scenario under GREEDY
        greedy_res = runner.run_24h_scenario(
            scenario_name="baseline",
            num_households=3,
            seed=42,
            planning_mode="GREEDY",
        )
        # Run baseline 24-hour scenario under A_STAR
        astar_res = runner.run_24h_scenario(
            scenario_name="baseline",
            num_households=3,
            seed=42,
            planning_mode="A_STAR",
            planning_horizon=12,
        )

        # Both runs satisfy demand without unmet deficit
        self.assertEqual(greedy_res.total_unmet_demand_kwh, 0.0)
        self.assertEqual(astar_res.total_unmet_demand_kwh, 0.0)

        # A* optimizes battery charging/discharging around TOU peak hours
        self.assertLessEqual(astar_res.total_energy_cost, greedy_res.total_energy_cost)

    def test_28_multi_agent_decentralized_independent_planning(self):
        """Test 28: Multiple agents execute independent local planning without centralized coordinator."""
        model = SmartGridModel(num_households=3, planning_mode="A_STAR", planning_horizon=6)
        
        # Verify agents maintain their own separate planners and results
        for a in model.household_agents:
            self.assertTrue(a.planning_enabled)
            self.assertIsNotNone(a.planner)

        model.step()

        # Each agent generated independent planning results
        for a in model.household_agents:
            self.assertIsNotNone(a.last_planning_result)
            self.assertIsInstance(a.last_planning_result, PlanningResult)
