import unittest
from smart_grid_mas.environment.smart_grid_model import SmartGridModel, DEFAULT_HOUSEHOLD_CONFIGS
from smart_grid_mas.agents.household_agent import HouseholdAgent
from smart_grid_mas.energy.energy_state import EnergyState, AgentAction
from smart_grid_mas.communication.message import Message, MessageType


class TestSmartGridFoundation(unittest.TestCase):
    """Automated test suite verifying the 10 foundational requirements."""

    def setUp(self):
        self.model = SmartGridModel(num_households=3)

    def test_01_model_initializes(self):
        """Test 1: SmartGridModel initializes correctly."""
        self.assertIsNotNone(self.model)
        self.assertEqual(self.model.current_step, 0)
        self.assertIsNotNone(self.model.utility_grid)
        self.assertEqual(self.model.utility_grid.total_imported, 0.0)
        self.assertEqual(self.model.utility_grid.total_exported, 0.0)

    def test_02_at_least_three_households_created(self):
        """Test 2: At least three HouseholdAgent instances are created."""
        households = self.model.household_agents
        self.assertGreaterEqual(len(households), 3)
        agent_ids = [a.agent_id for a in households]
        self.assertIn("Household A", agent_ids)
        self.assertIn("Household B", agent_ids)
        self.assertIn("Household C", agent_ids)

    def test_03_independent_local_state(self):
        """Test 3: Each HouseholdAgent maintains independent local state."""
        agent_a = self.model.get_agent_by_id("Household A")
        agent_b = self.model.get_agent_by_id("Household B")
        agent_c = self.model.get_agent_by_id("Household C")

        self.assertIsNotNone(agent_a)
        self.assertIsNotNone(agent_b)
        self.assertIsNotNone(agent_c)

        # Solar generation is independent
        self.assertEqual(agent_a.solar_generation, 6.0)
        self.assertEqual(agent_b.solar_generation, 2.0)
        self.assertEqual(agent_c.solar_generation, 4.0)

        # Demand is independent
        self.assertEqual(agent_a.household_demand, 3.0)
        self.assertEqual(agent_b.household_demand, 5.0)
        self.assertEqual(agent_c.household_demand, 4.0)

        # Battery SOC is independent
        self.assertEqual(agent_a.battery_soc, 60.0)
        self.assertEqual(agent_b.battery_soc, 40.0)
        self.assertEqual(agent_c.battery_soc, 70.0)

        # Modifying one agent's state does not affect another
        agent_a.solar_generation = 10.0
        self.assertEqual(agent_b.solar_generation, 2.0)

    def test_04_energy_balance_calculation(self):
        """Test 4: Energy balance is calculated accurately as (solar - demand)."""
        agent_a = self.model.get_agent_by_id("Household A")
        agent_b = self.model.get_agent_by_id("Household B")
        agent_c = self.model.get_agent_by_id("Household C")

        agent_a.observe_local_state()
        agent_b.observe_local_state()
        agent_c.observe_local_state()

        self.assertAlmostEqual(agent_a.energy_balance, 3.0)   # 6.0 - 3.0
        self.assertAlmostEqual(agent_b.energy_balance, -3.0)  # 2.0 - 5.0
        self.assertAlmostEqual(agent_c.energy_balance, 0.0)   # 4.0 - 4.0

    def test_05_state_classification(self):
        """Test 5: SURPLUS / DEFICIT / BALANCED classification works correctly."""
        agent_a = self.model.get_agent_by_id("Household A")
        agent_b = self.model.get_agent_by_id("Household B")
        agent_c = self.model.get_agent_by_id("Household C")

        self.assertEqual(agent_a.state, EnergyState.SURPLUS)
        self.assertEqual(agent_b.state, EnergyState.DEFICIT)
        self.assertEqual(agent_c.state, EnergyState.BALANCED)

    def test_06_local_action_selection(self):
        """Test 6: Local deterministic action selection works as specified."""
        agent_a = self.model.get_agent_by_id("Household A")
        agent_b = self.model.get_agent_by_id("Household B")
        agent_c = self.model.get_agent_by_id("Household C")

        # Initial conditions:
        # A: Surplus, SOC 60% < 100% -> CHARGE
        self.assertEqual(agent_a.evaluate_local_action(), AgentAction.CHARGE)

        # B: Deficit, SOC 40% > 0% -> DISCHARGE
        self.assertEqual(agent_b.evaluate_local_action(), AgentAction.DISCHARGE)

        # C: Balanced -> CONSUME
        self.assertEqual(agent_c.evaluate_local_action(), AgentAction.CONSUME)

        # Boundary checks:
        # Full battery with surplus -> SELL
        agent_a.battery_soc = 100.0
        self.assertEqual(agent_a.evaluate_local_action(), AgentAction.SELL)

        # Empty battery with deficit -> BUY
        agent_b.battery_soc = 0.0
        self.assertEqual(agent_b.evaluate_local_action(), AgentAction.BUY)

    def test_07_simulation_advances_multiple_timesteps(self):
        """Test 7: Simulation advances across multiple timesteps and updates state sequentially."""
        self.assertEqual(self.model.current_step, 0)
        
        telemetry_1 = self.model.step()
        self.assertEqual(self.model.current_step, 1)
        self.assertEqual(telemetry_1["step"], 1)

        # In Step 1, Agent A charged (+3.0 kW into 10 kWh battery: 60% -> 90%)
        agent_a = self.model.get_agent_by_id("Household A")
        self.assertAlmostEqual(agent_a.battery_soc, 90.0)

        # In Step 1, Agent B discharged (-3.0 kW from 10 kWh battery: 40% -> 10%)
        agent_b = self.model.get_agent_by_id("Household B")
        self.assertAlmostEqual(agent_b.battery_soc, 10.0)

        # Step 2
        telemetry_2 = self.model.step()
        self.assertEqual(self.model.current_step, 2)
        self.assertEqual(telemetry_2["step"], 2)

        # State persisted and updated sequentially
        self.assertEqual(len(self.model.telemetry_history), 2)

    def test_08_battery_soc_stays_within_valid_limits(self):
        """Test 8: Battery SOC strictly stays within [0.0%, 100.0%]."""
        agent = HouseholdAgent(
            model=self.model,
            agent_id="Test Battery",
            solar_generation=15.0,
            household_demand=0.0,
            battery_capacity=10.0,
            battery_soc=95.0,
            max_charge_rate_kw=10.0,
        )
        # Attempt to overcharge
        agent.observe_local_state()
        agent.current_action = agent.evaluate_local_action()
        agent.execute_action()
        self.assertLessEqual(agent.battery_soc, 100.0)
        self.assertEqual(agent.battery_soc, 100.0)

        # Attempt to overdischarge
        agent.update_environment(solar_kw=0.0, demand_kw=20.0)
        agent.battery_soc = 5.0
        agent.observe_local_state()
        agent.current_action = agent.evaluate_local_action()
        agent.execute_action()
        self.assertGreaterEqual(agent.battery_soc, 0.0)
        self.assertEqual(agent.battery_soc, 0.0)

    def test_09_communication_messages_delivered(self):
        """Test 9: Communication messages can be created, transmitted, and received."""
        agent_a = self.model.get_agent_by_id("Household A")
        agent_b = self.model.get_agent_by_id("Household B")
        agent_c = self.model.get_agent_by_id("Household C")

        # Step the model so messages are broadcasted
        self.model.step()

        # Agent B (deficit) and Agent C (balanced) must have received Agent A's SURPLUS broadcast
        b_types = [m.message_type for m in agent_b.received_messages if m.sender_id == "Household A"]
        self.assertIn(MessageType.SURPLUS, b_types)

        # Agent A (surplus) and Agent C (balanced) must have received Agent B's DEFICIT broadcast
        a_types = [m.message_type for m in agent_a.received_messages if m.sender_id == "Household B"]
        self.assertIn(MessageType.DEFICIT, a_types)

        # Direct point-to-point message test
        custom_msg = Message(
            sender_id="Household A",
            receiver_id="Household B",
            message_type=MessageType.OFFER,
            energy_amount=2.5,
            state=EnergyState.SURPLUS,
            timestamp=self.model.current_step,
        )
        agent_a.send_direct_message(agent_b, custom_msg)
        self.assertIn(custom_msg, agent_b.received_messages)

    def test_10_configurable_num_households_scalability(self):
        """Test 10: Model dynamically supports changing num_households (e.g., 3, 5, 10)."""
        model_5 = SmartGridModel(num_households=5)
        self.assertEqual(len(model_5.household_agents), 5)

        model_10 = SmartGridModel(num_households=10)
        self.assertEqual(len(model_10.household_agents), 10)

        # Verify each agent in model_10 has 9 neighbors
        for agent in model_10.household_agents:
            self.assertEqual(len(agent.neighbors), 9)

        # Verify step works seamlessly for 10 households
        telemetry = model_10.step()
        self.assertEqual(len(telemetry["agents"]), 10)
        self.assertEqual(telemetry["step"], 1)


if __name__ == "__main__":
    unittest.main()
