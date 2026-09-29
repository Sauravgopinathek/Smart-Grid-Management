"""Correctness & invariant tests (added after code review).

These tests check properties that must hold for ANY input, rather than a
single hand-picked example:

1. A* optimality     - heuristic is admissible; A* matches exhaustive search.
2. Energy balance    - no agent ever creates or loses energy, in every scenario.
3. Negotiation       - no accepted trade is left undelivered; surplus is never
                       over-committed; renegotiation rounds recover energy and
                       always terminate.
"""

import random
import unittest

from smart_grid_mas.planning.astar_planner import AStarPlanner
from smart_grid_mas.planning.cost_function import CostFunction
from smart_grid_mas.negotiation.negotiation_protocol import NegotiationProtocol
from smart_grid_mas.environment.smart_grid_model import SmartGridModel
from smart_grid_mas.scenarios.scenario_runner import ScenarioRunner

ALL_SCENARIOS = ["baseline", "cloud_cover", "peak_demand", "grid_outage", "combined", "real_world_dataset"]


def _random_instance(rng: random.Random, horizon: int):
    solar = [round(rng.uniform(0, 7), 2) if rng.random() < 0.7 else 0.0 for _ in range(horizon)]
    demand = [round(rng.uniform(0.3, 6), 2) for _ in range(horizon)]
    grid = [rng.random() > 0.2 for _ in range(horizon)]
    return dict(
        start_hour=rng.randint(0, 23),
        initial_soc=rng.choice([0, 10, 35, 50, 80, 100]),
        solar_forecast=solar,
        demand_forecast=demand,
        grid_available_forecast=grid,
    )


class TestAStarOptimality(unittest.TestCase):

    def test_heuristic_admissible_with_future_surplus(self):
        """Counter-example to the old heuristic: surplus then deficit, empty battery.

        Old h = (5 - 0) * 3 = Rs 15, but the optimum (store solar, then discharge)
        costs only Rs 0.50. The heuristic must never exceed the true optimum.
        """
        planner = AStarPlanner(horizon=2)
        solar, demand = [6.0, 0.0], [1.0, 5.0]
        optimum = planner.exhaustive_optimal_cost(10, 0.0, solar_forecast=solar, demand_forecast=demand)
        h_root = planner.cost_function.calculate_heuristic(0.0, solar, demand)
        self.assertAlmostEqual(optimum, 0.5, places=3)
        self.assertLessEqual(h_root, optimum + 1e-6)

    def test_heuristic_never_exceeds_optimum_random(self):
        rng = random.Random(11)
        for _ in range(200):
            H = rng.choice([2, 3, 4, 5])
            inst = _random_instance(rng, H)
            planner = AStarPlanner(horizon=H)
            optimum = planner.exhaustive_optimal_cost(**inst)
            stored = inst["initial_soc"] / 100.0 * 10.0
            h_root = planner.cost_function.calculate_heuristic(
                stored, inst["solar_forecast"], inst["demand_forecast"]
            )
            self.assertLessEqual(h_root, optimum + 1e-6, msg=str(inst))

    def test_astar_matches_exhaustive_search(self):
        """A* must return exactly the optimal cost found by brute force."""
        rng = random.Random(7)
        for _ in range(200):
            H = rng.choice([3, 4, 5, 6])
            inst = _random_instance(rng, H)
            planner = AStarPlanner(horizon=H)
            astar = planner.plan(**inst)
            optimum = planner.exhaustive_optimal_cost(**inst)
            self.assertAlmostEqual(astar.total_cost, optimum, places=3, msg=str(inst))

    def test_heuristic_prunes_versus_uniform_cost_search(self):
        """A* with h(n) should never expand more nodes than h = 0 (uniform-cost search)."""

        class ZeroHeuristic(CostFunction):
            def calculate_heuristic(self, *args, **kwargs):
                return 0.0

        rng = random.Random(3)
        astar_nodes = ucs_nodes = 0
        for _ in range(100):
            inst = _random_instance(rng, 6)
            astar_nodes += AStarPlanner(horizon=6).plan(**inst).nodes_expanded
            ucs_nodes += AStarPlanner(horizon=6, cost_function=ZeroHeuristic()).plan(**inst).nodes_expanded
        self.assertLessEqual(astar_nodes, ucs_nodes)


class TestEnergyConservation(unittest.TestCase):

    def _assert_balanced(self, result):
        for rec in result.hourly_records:
            for a in rec["agents"]:
                supply = (a["solar_generation"] + max(0.0, -a["battery_flow"]) + a["p2p_bought"]
                          + a["grid_import"] + a["unmet_demand"])
                use = (a["household_demand"] + max(0.0, a["battery_flow"]) + a["p2p_sold"]
                       + a["grid_export"] + a["curtailed_energy"])
                self.assertAlmostEqual(
                    supply, use, places=3,
                    msg=f"{result.scenario_name}/{result.planning_mode} hour {rec['hour']} {a['agent_id']}",
                )

    def test_every_agent_balances_every_hour(self):
        runner = ScenarioRunner()
        for mode in ("GREEDY", "A_STAR"):
            for scenario in ALL_SCENARIOS:
                for n in (3, 10):
                    self._assert_balanced(runner.run_24h_scenario(scenario, num_households=n, planning_mode=mode))

    def test_cloud_shock_uses_observed_solar_not_forecast(self):
        """Regression: at 13:00 in the cloud scenario the planner used the sunny
        forecast and charged 5 kWh from 0.93 kWh of surplus (4.07 kWh from nowhere)."""
        res = ScenarioRunner().run_24h_scenario("cloud_cover", planning_mode="A_STAR")
        for a in res.hourly_records[13]["agents"]:
            charge = max(0.0, a["battery_flow"])
            local_surplus = max(0.0, a["solar_generation"] - a["household_demand"])
            self.assertLessEqual(charge, local_surplus + a["p2p_bought"] + a["grid_import"] + 1e-6)

    def test_unfunded_charge_is_cancelled_when_grid_offline(self):
        model = SmartGridModel(num_households=1, household_configs=[dict(
            agent_id="H", solar_generation=1.0, household_demand=1.0, battery_soc=20.0)])
        agent = model.household_agents[0]
        model.utility_grid.set_availability(False)
        agent.observe_local_state()
        # Simulate a plan that wants to charge 3 kWh with no local surplus.
        agent.planned_battery_flow = 3.0
        agent.charge_from_purchase = 3.0
        agent.remaining_deficit = 3.0
        agent.state = agent.state.__class__.DEFICIT
        agent.execute_action()
        self.assertAlmostEqual(agent.battery_soc, 20.0)
        self.assertAlmostEqual(agent.unmet_demand, 0.0)


class TestNegotiationInvariants(unittest.TestCase):

    def test_allocate_surplus_never_overcommits(self):
        rng = random.Random(5)
        for _ in range(500):
            available = rng.uniform(0, 6)
            requests = [rng.uniform(0, 4) for _ in range(rng.randint(1, 6))]
            shares = NegotiationProtocol.allocate_surplus(available, requests)
            self.assertLessEqual(sum(shares), available + 1e-9)
            for share, req in zip(shares, requests):
                self.assertLessEqual(share, req + 1e-9)

    def test_allocate_surplus_is_proportional_when_oversubscribed(self):
        shares = NegotiationProtocol.allocate_surplus(3.0, [1.0, 2.0, 3.0])
        self.assertEqual(shares, [0.5, 1.0, 1.5])

    def test_every_accept_is_delivered_in_full(self):
        runner = ScenarioRunner()
        for mode in ("GREEDY", "A_STAR"):
            for scenario in ALL_SCENARIOS:
                for n in (3, 10, 25):
                    res = runner.run_24h_scenario(scenario, num_households=n, planning_mode=mode)
                    for rec in res.hourly_records:
                        accepted, delivered = {}, {}
                        for m in rec["messages"]:
                            if m["type"] == "ACCEPT":
                                key = (m["sender"], m["receiver"])
                                accepted[key] = accepted.get(key, 0.0) + m["amount"]
                        for t in rec["trades"]:
                            key = (t["buyer"], t["seller"])
                            delivered[key] = delivered.get(key, 0.0) + t["amount"]
                        for key, amount in accepted.items():
                            self.assertAlmostEqual(delivered.get(key, 0.0), amount, places=3,
                                                   msg=f"{scenario}/{mode}/N={n} hour {rec['hour']} {key}")

    def test_seller_p2p_export_respects_inverter_limit(self):
        cfg = [dict(agent_id="S", solar_generation=10.0, household_demand=0.0, battery_soc=100.0,
                    max_charge_rate_kw=5.0)]
        cfg += [dict(agent_id=f"B{i}", solar_generation=0.0, household_demand=3.0, battery_soc=0.0)
                for i in range(3)]
        telemetry = SmartGridModel(num_households=4, household_configs=cfg).step()
        seller = next(a for a in telemetry["agents"] if a["agent_id"] == "S")
        self.assertLessEqual(seller["p2p_sold"], 5.0 + 1e-6)

    @staticmethod
    def _partial_topology_model(rounds: int) -> SmartGridModel:
        """B1 can only reach the expensive seller S1; B2 reaches both.

        Round 1: S1 splits its 2 kWh between B1 and B2 (1 + 1). B2 prefers the
        cheaper S2 and declines S1's share, so B1 is left 1 kWh short while S1
        still holds 1 kWh. Round 2 lets them trade it.
        """
        cfg = [
            dict(agent_id="S1", solar_generation=3.0, household_demand=1.0, battery_soc=100.0, preferred_p2p_sell_price=5.0),
            dict(agent_id="S2", solar_generation=3.0, household_demand=1.0, battery_soc=100.0, preferred_p2p_sell_price=4.0),
            dict(agent_id="B1", solar_generation=0.0, household_demand=2.0, battery_soc=0.0),
            dict(agent_id="B2", solar_generation=0.0, household_demand=2.0, battery_soc=0.0),
        ]
        model = SmartGridModel(num_households=4, household_configs=cfg, max_negotiation_rounds=rounds)
        by_id = {a.agent_id: a for a in model.household_agents}
        topology = {"S1": ["B1", "B2"], "S2": ["B2"], "B1": ["S1"], "B2": ["S1", "S2"]}
        for agent_id, peers in topology.items():
            by_id[agent_id].neighbors = [by_id[p] for p in peers]
        return model

    def test_renegotiation_recovers_declined_energy(self):
        one_round = self._partial_topology_model(rounds=1).step()
        multi_round = self._partial_topology_model(rounds=3).step()

        b1_one = next(a for a in one_round["agents"] if a["agent_id"] == "B1")
        b1_multi = next(a for a in multi_round["agents"] if a["agent_id"] == "B1")

        self.assertAlmostEqual(b1_one["grid_import"], 1.0, places=3)   # left short after round 1
        self.assertAlmostEqual(b1_multi["grid_import"], 0.0, places=3)  # recovered in round 2
        self.assertAlmostEqual(b1_multi["p2p_bought"], 2.0, places=3)
        self.assertEqual(multi_round["negotiation_rounds"], 2)          # stopped early: nothing left

    def test_negotiation_always_terminates_within_round_limit(self):
        runner = ScenarioRunner()
        for rounds in (1, 2, 5):
            res = runner.run_24h_scenario("real_world_dataset", num_households=10, negotiation_rounds=rounds)
            for rec in res.hourly_records:
                self.assertLessEqual(rec["negotiation_rounds"], rounds)


if __name__ == "__main__":
    unittest.main()
