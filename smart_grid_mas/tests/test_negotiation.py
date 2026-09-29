import unittest
from smart_grid_mas.environment.smart_grid_model import SmartGridModel
from smart_grid_mas.agents.household_agent import HouseholdAgent
from smart_grid_mas.energy.energy_state import EnergyState, AgentAction
from smart_grid_mas.communication.message import Message, MessageType
from smart_grid_mas.negotiation.trade import Trade, TradeStatus
from smart_grid_mas.negotiation.negotiation_protocol import NegotiationProtocol


class TestNegotiationAndP2PTrading(unittest.TestCase):
    """Test suite verifying Module 2: Decentralized P2P Negotiation & Energy Trading."""

    def setUp(self):
        # Deterministic setup with clear Surplus, Deficit, Balanced households
        self.configs = [
            {
                "agent_id": "Household A",
                "solar_generation": 6.0,
                "household_demand": 3.0,
                "battery_capacity": 10.0,
                "battery_soc": 100.0,  # Full battery: 3.0 kW surplus is available for P2P
                "max_p2p_buy_price": 6.0,
                "preferred_p2p_sell_price": 5.0,
            },
            {
                "agent_id": "Household B",
                "solar_generation": 2.0,
                "household_demand": 5.0,
                "battery_capacity": 10.0,
                "battery_soc": 0.0,    # Empty battery: 3.0 kW deficit needs external energy
                "max_p2p_buy_price": 6.0,
                "preferred_p2p_sell_price": 5.0,
            },
            {
                "agent_id": "Household C",
                "solar_generation": 4.0,
                "household_demand": 4.0,
                "battery_capacity": 10.0,
                "battery_soc": 70.0,   # Balanced
                "max_p2p_buy_price": 6.0,
                "preferred_p2p_sell_price": 5.0,
            },
        ]
        self.model = SmartGridModel(num_households=3, household_configs=self.configs, enable_p2p=True)

    def test_01_deficit_agent_creates_request(self):
        """Test 1: Deficit household can create a valid REQUEST message."""
        buyer = self.model.get_agent_by_id("Household B")
        self.assertAlmostEqual(buyer.remaining_deficit, 3.0)

        req = NegotiationProtocol.create_request(
            buyer_id=buyer.agent_id,
            seller_id="Household A",
            requested_energy_kwh=buyer.remaining_deficit,
            max_price_per_kwh=buyer.max_p2p_buy_price,
            timestamp=1,
        )
        self.assertEqual(req.message_type, MessageType.REQUEST)
        self.assertEqual(req.sender_id, "Household B")
        self.assertEqual(req.receiver_id, "Household A")
        self.assertEqual(req.energy_amount, 3.0)
        self.assertEqual(req.metadata["max_price_per_kwh"], 6.0)

    def test_02_surplus_agent_receives_request(self):
        """Test 2: Surplus household receives the REQUEST in its inbox."""
        seller = self.model.get_agent_by_id("Household A")
        buyer = self.model.get_agent_by_id("Household B")

        req = NegotiationProtocol.create_request(
            buyer_id=buyer.agent_id,
            seller_id=seller.agent_id,
            requested_energy_kwh=3.0,
            max_price_per_kwh=6.0,
            timestamp=1,
        )
        buyer.send_direct_message(seller, req)
        self.assertIn(req, seller.received_messages)

    def test_03_surplus_agent_creates_offer(self):
        """Test 3: Surplus household evaluates REQUEST and creates a valid OFFER."""
        seller = self.model.get_agent_by_id("Household A")
        self.assertAlmostEqual(seller.available_surplus, 3.0)

        req = Message(
            sender_id="Household B",
            receiver_id=seller.agent_id,
            message_type=MessageType.REQUEST,
            energy_amount=3.0,
            state=EnergyState.DEFICIT,
            timestamp=1,
            metadata={"requested_energy": 3.0, "max_price_per_kwh": 6.0},
        )
        offer = NegotiationProtocol.evaluate_request(seller, req, current_step=1)
        self.assertIsNotNone(offer)
        self.assertEqual(offer.message_type, MessageType.OFFER)
        self.assertEqual(offer.sender_id, "Household A")
        self.assertEqual(offer.receiver_id, "Household B")
        self.assertEqual(offer.energy_amount, 3.0)
        self.assertEqual(offer.metadata["price_per_kwh"], 5.0)
        self.assertEqual(offer.metadata["total_price"], 15.0)

    def test_04_buyer_evaluates_offer(self):
        """Test 4: Buyer evaluates candidate offers using local decision logic."""
        buyer = self.model.get_agent_by_id("Household B")
        offer = Message(
            sender_id="Household A",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=3.0,
            state=EnergyState.SURPLUS,
            timestamp=1,
            metadata={"offered_energy": 3.0, "price_per_kwh": 5.0, "total_price": 15.0},
        )
        accepted, rejected = NegotiationProtocol.evaluate_offers(buyer, [offer], current_step=1)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(accepted[0][0].sender_id, "Household A")
        self.assertEqual(accepted[0][1], 3.0)

    def test_05_buyer_accepts_offer_within_price_limit(self):
        """Test 5: Buyer accepts an offer whose price is <= max_p2p_buy_price."""
        buyer = self.model.get_agent_by_id("Household B")
        buyer.max_p2p_buy_price = 6.0

        offer_fair = Message(
            sender_id="Household A",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=2.0,
            state=EnergyState.SURPLUS,
            timestamp=1,
            metadata={"offered_energy": 2.0, "price_per_kwh": 5.5},
        )
        accepted, rejected = NegotiationProtocol.evaluate_offers(buyer, [offer_fair], current_step=1)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 0)

    def test_06_buyer_rejects_offer_above_price_limit(self):
        """Test 6: Buyer rejects an offer exceeding its maximum acceptable price."""
        buyer = self.model.get_agent_by_id("Household B")
        buyer.max_p2p_buy_price = 6.0

        offer_expensive = Message(
            sender_id="Household A",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=2.0,
            state=EnergyState.SURPLUS,
            timestamp=1,
            metadata={"offered_energy": 2.0, "price_per_kwh": 7.5},
        )
        accepted, rejected = NegotiationProtocol.evaluate_offers(buyer, [offer_expensive], current_step=1)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].sender_id, "Household A")

    def test_07_buyer_prefers_lower_price(self):
        """Test 7: Buyer chooses the lower-priced offer when multiple offers exist."""
        buyer = self.model.get_agent_by_id("Household B")
        buyer.remaining_deficit = 2.0
        buyer.max_p2p_buy_price = 8.0

        offer_a = Message(
            sender_id="Seller A",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=2.0,
            state=EnergyState.SURPLUS,
            timestamp=1,
            metadata={"offered_energy": 2.0, "price_per_kwh": 5.0},
        )
        offer_b = Message(
            sender_id="Seller B",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=2.0,
            state=EnergyState.SURPLUS,
            timestamp=1,
            metadata={"offered_energy": 2.0, "price_per_kwh": 4.0},
        )

        accepted, rejected = NegotiationProtocol.evaluate_offers(buyer, [offer_a, offer_b], current_step=1)
        self.assertEqual(len(accepted), 1)
        # Winner must be Seller B because 4.0 < 5.0
        self.assertEqual(accepted[0][0].sender_id, "Seller B")
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].sender_id, "Seller A")

    def test_08_deterministic_multi_offer_selection(self):
        """Test 8: Deterministic tie-breaking on quantity and agent ID."""
        buyer = self.model.get_agent_by_id("Household B")
        buyer.remaining_deficit = 2.0

        # Same price, different quantity
        offer_small = Message(
            sender_id="Seller 1",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=1.0,
            state=EnergyState.SURPLUS,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        offer_large = Message(
            sender_id="Seller 2",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=2.0,
            state=EnergyState.SURPLUS,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        accepted, rejected = NegotiationProtocol.evaluate_offers(buyer, [offer_small, offer_large], current_step=1)
        self.assertEqual(accepted[0][0].sender_id, "Seller 2")

    def test_09_accepted_trade_creates_trade_record(self):
        """Test 9: Settle trade instantiates a structured Trade object with COMPLETED status."""
        seller = self.model.get_agent_by_id("Household A")
        buyer = self.model.get_agent_by_id("Household B")

        accept_msg = Message(
            sender_id=buyer.agent_id,
            receiver_id=seller.agent_id,
            message_type=MessageType.ACCEPT,
            energy_amount=3.0,
            state=EnergyState.DEFICIT,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        trade = NegotiationProtocol.settle_trade(seller, buyer, accept_msg, "TRADE_01")
        self.assertIsNotNone(trade)
        self.assertEqual(trade.trade_id, "TRADE_01")
        self.assertEqual(trade.seller_id, "Household A")
        self.assertEqual(trade.buyer_id, "Household B")
        self.assertEqual(trade.energy_amount, 3.0)
        self.assertEqual(trade.price_per_kwh, 5.0)
        self.assertEqual(trade.total_price, 15.0)
        self.assertEqual(trade.status, TradeStatus.COMPLETED)

    def test_10_trade_changes_seller_energy_availability(self):
        """Test 10: Trade completion deducts energy from seller's available surplus."""
        seller = self.model.get_agent_by_id("Household A")
        initial_surplus = seller.available_surplus
        buyer = self.model.get_agent_by_id("Household B")

        accept_msg = Message(
            sender_id=buyer.agent_id,
            receiver_id=seller.agent_id,
            message_type=MessageType.ACCEPT,
            energy_amount=2.0,
            state=EnergyState.DEFICIT,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        NegotiationProtocol.settle_trade(seller, buyer, accept_msg, "TRADE_02")
        self.assertAlmostEqual(seller.available_surplus, initial_surplus - 2.0)
        self.assertEqual(seller.p2p_energy_sold, 2.0)
        self.assertEqual(seller.p2p_revenue, 10.0)

    def test_11_trade_reduces_buyer_deficit(self):
        """Test 11: Trade completion reduces buyer's remaining deficit."""
        seller = self.model.get_agent_by_id("Household A")
        buyer = self.model.get_agent_by_id("Household B")
        initial_deficit = buyer.remaining_deficit

        accept_msg = Message(
            sender_id=buyer.agent_id,
            receiver_id=seller.agent_id,
            message_type=MessageType.ACCEPT,
            energy_amount=2.0,
            state=EnergyState.DEFICIT,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        NegotiationProtocol.settle_trade(seller, buyer, accept_msg, "TRADE_03")
        self.assertAlmostEqual(buyer.remaining_deficit, initial_deficit - 2.0)
        self.assertEqual(buyer.p2p_energy_bought, 2.0)
        self.assertEqual(buyer.p2p_cost, 10.0)

    def test_12_p2p_trade_not_executed_twice(self):
        """Test 12: Duplicate accept messages do not cause duplicate physical settlement."""
        telemetry = self.model.step()
        trade_count_1 = telemetry["p2p_trade_count"]
        self.assertEqual(trade_count_1, 1)

        # In Step 1, A (3 kWh surplus) traded 3 kWh to B (3 kWh deficit).
        # A's available surplus should now be 0.0
        seller = self.model.get_agent_by_id("Household A")
        self.assertAlmostEqual(seller.available_surplus, 0.0)

    def test_13_seller_cannot_sell_more_than_available(self):
        """Test 13: Seller available surplus caps the trade amount."""
        seller = self.model.get_agent_by_id("Household A")
        seller.available_surplus = 1.5
        buyer = self.model.get_agent_by_id("Household B")
        buyer.remaining_deficit = 5.0

        accept_msg = Message(
            sender_id=buyer.agent_id,
            receiver_id=seller.agent_id,
            message_type=MessageType.ACCEPT,
            energy_amount=5.0,  # Buyer requests 5.0
            state=EnergyState.DEFICIT,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        trade = NegotiationProtocol.settle_trade(seller, buyer, accept_msg, "TRADE_04")
        self.assertEqual(trade.energy_amount, 1.5)  # Capped at seller available surplus
        self.assertAlmostEqual(seller.available_surplus, 0.0)
        self.assertAlmostEqual(buyer.remaining_deficit, 3.5)

    def test_14_buyer_cannot_purchase_more_than_deficit(self):
        """Test 14: Buyer cannot buy more than its remaining deficit."""
        seller = self.model.get_agent_by_id("Household A")
        seller.available_surplus = 10.0
        buyer = self.model.get_agent_by_id("Household B")
        buyer.remaining_deficit = 1.2

        accept_msg = Message(
            sender_id=buyer.agent_id,
            receiver_id=seller.agent_id,
            message_type=MessageType.ACCEPT,
            energy_amount=5.0,  # Over-acceptance attempt
            state=EnergyState.DEFICIT,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        trade = NegotiationProtocol.settle_trade(seller, buyer, accept_msg, "TRADE_05")
        self.assertEqual(trade.energy_amount, 1.2)
        self.assertAlmostEqual(buyer.remaining_deficit, 0.0)

    def test_15_remaining_deficit_falls_back_to_utility_grid(self):
        """Test 15: If P2P covers partial deficit, residual falls back to Utility Grid."""
        # A has 1.0 kW surplus, B has 3.0 kW deficit
        configs = [
            {"agent_id": "Household A", "solar_generation": 4.0, "household_demand": 3.0, "battery_soc": 100.0},
            {"agent_id": "Household B", "solar_generation": 2.0, "household_demand": 5.0, "battery_soc": 0.0},
        ]
        m = SmartGridModel(num_households=2, household_configs=configs, enable_p2p=True)
        telemetry = m.step()

        # Trade should be 1.0 kWh
        self.assertEqual(telemetry["p2p_energy_traded"], 1.0)
        # Residual 2.0 kWh imported from utility grid
        self.assertEqual(telemetry["grid_import"], 2.0)
        self.assertEqual(m.utility_grid.current_step_import, 2.0)

    def test_16_remaining_surplus_falls_back_to_utility_grid(self):
        """Test 16: If P2P absorbs partial surplus, residual falls back to Grid export."""
        # A has 5.0 kW surplus, B has 2.0 kW deficit
        configs = [
            {"agent_id": "Household A", "solar_generation": 8.0, "household_demand": 3.0, "battery_soc": 100.0},
            {"agent_id": "Household B", "solar_generation": 2.0, "household_demand": 4.0, "battery_soc": 0.0},
        ]
        m = SmartGridModel(num_households=2, household_configs=configs, enable_p2p=True)
        telemetry = m.step()

        # Trade is 2.0 kWh
        self.assertEqual(telemetry["p2p_energy_traded"], 2.0)
        # Residual 3.0 kWh exported to utility grid
        self.assertEqual(telemetry["grid_export"], 3.0)
        self.assertEqual(m.utility_grid.current_step_export, 3.0)

    def test_17_balanced_households_do_not_initiate_p2p(self):
        """Test 17: Balanced household (generation == demand) does not initiate trades."""
        agent_c = self.model.get_agent_by_id("Household C")
        self.assertEqual(agent_c.state, EnergyState.BALANCED)
        self.assertEqual(agent_c.available_surplus, 0.0)
        self.assertEqual(agent_c.remaining_deficit, 0.0)

        self.model.step()
        self.assertEqual(agent_c.p2p_energy_bought, 0.0)
        self.assertEqual(agent_c.p2p_energy_sold, 0.0)
        self.assertEqual(agent_c.current_action, AgentAction.CONSUME)

    def test_18_p2p_telemetry_statistics_updated(self):
        """Test 18: Model telemetry correctly aggregates P2P volume, value, and count."""
        telemetry = self.model.step()
        self.assertEqual(telemetry["p2p_energy_traded"], 3.0)
        self.assertEqual(telemetry["p2p_trade_count"], 1)
        self.assertEqual(telemetry["p2p_trade_value"], 15.0)
        self.assertEqual(telemetry["p2p_deficit_coverage_percent"], 100.0)
        self.assertEqual(telemetry["grid_import"], 0.0)
        self.assertEqual(telemetry["grid_export"], 0.0)

    # =========================================================================
    # EDGE CASES
    # =========================================================================

    def test_edge_case_1_no_surplus_agents_exist(self):
        """Edge Case 1: All agents in deficit or balanced -> Buyer falls back to Grid."""
        configs = [
            {"agent_id": "H1", "solar_generation": 1.0, "household_demand": 4.0, "battery_soc": 0.0},
            {"agent_id": "H2", "solar_generation": 2.0, "household_demand": 5.0, "battery_soc": 0.0},
        ]
        m = SmartGridModel(num_households=2, household_configs=configs, enable_p2p=True)
        telemetry = m.step()
        self.assertEqual(telemetry["p2p_trade_count"], 0)
        self.assertEqual(telemetry["p2p_energy_traded"], 0.0)
        # Both deficits must be imported from grid: (3.0 + 3.0 = 6.0)
        self.assertEqual(telemetry["grid_import"], 6.0)

    def test_edge_case_2_no_deficit_agents_exist(self):
        """Edge Case 2: All agents in surplus -> No trades, energy exported to grid."""
        configs = [
            {"agent_id": "H1", "solar_generation": 5.0, "household_demand": 2.0, "battery_soc": 100.0},
            {"agent_id": "H2", "solar_generation": 6.0, "household_demand": 3.0, "battery_soc": 100.0},
        ]
        m = SmartGridModel(num_households=2, household_configs=configs, enable_p2p=True)
        telemetry = m.step()
        self.assertEqual(telemetry["p2p_trade_count"], 0)
        self.assertEqual(telemetry["grid_export"], 6.0)

    def test_edge_case_3_seller_surplus_greater_than_buyer_deficit(self):
        """Edge Case 3: Seller has 5 kWh, Buyer needs 2 kWh -> Trade = 2 kWh, Seller retains 3 kWh."""
        configs = [
            {"agent_id": "H_Seller", "solar_generation": 7.0, "household_demand": 2.0, "battery_soc": 100.0},
            {"agent_id": "H_Buyer", "solar_generation": 1.0, "household_demand": 3.0, "battery_soc": 0.0},
        ]
        m = SmartGridModel(num_households=2, household_configs=configs, enable_p2p=True)
        telemetry = m.step()
        self.assertEqual(telemetry["p2p_energy_traded"], 2.0)
        # Residual 3 kWh exported
        self.assertEqual(telemetry["grid_export"], 3.0)
        self.assertEqual(telemetry["grid_import"], 0.0)

    def test_edge_case_4_buyer_deficit_greater_than_seller_surplus(self):
        """Edge Case 4: Seller has 2 kWh, Buyer needs 5 kWh -> Trade = 2 kWh, 3 kWh from Grid."""
        configs = [
            {"agent_id": "H_Seller", "solar_generation": 4.0, "household_demand": 2.0, "battery_soc": 100.0},
            {"agent_id": "H_Buyer", "solar_generation": 1.0, "household_demand": 6.0, "battery_soc": 0.0},
        ]
        m = SmartGridModel(num_households=2, household_configs=configs, enable_p2p=True)
        telemetry = m.step()
        self.assertEqual(telemetry["p2p_energy_traded"], 2.0)
        self.assertEqual(telemetry["grid_import"], 3.0)
        self.assertEqual(telemetry["grid_export"], 0.0)

    def test_edge_case_5_competing_sellers_price_selection(self):
        """Edge Case 5: Seller A at ₹5/kWh, Seller B at ₹4/kWh -> Buyer selects Seller B."""
        configs = [
            {"agent_id": "Seller A", "solar_generation": 5.0, "household_demand": 2.0, "battery_soc": 100.0, "preferred_p2p_sell_price": 5.0},
            {"agent_id": "Seller B", "solar_generation": 5.0, "household_demand": 2.0, "battery_soc": 100.0, "preferred_p2p_sell_price": 4.0},
            {"agent_id": "Buyer", "solar_generation": 1.0, "household_demand": 3.0, "battery_soc": 0.0, "max_p2p_buy_price": 6.0},
        ]
        m = SmartGridModel(num_households=3, household_configs=configs, enable_p2p=True)
        telemetry = m.step()
        self.assertEqual(telemetry["p2p_trade_count"], 1)
        trade = telemetry["trades"][0]
        self.assertEqual(trade["seller"], "Seller B")
        self.assertEqual(trade["price"], 4.0)

    def test_edge_case_6_offer_exceeds_buyer_maximum_price(self):
        """Edge Case 6: Seller price ₹8/kWh, Buyer max ₹6/kWh -> Rejected, Grid fallback."""
        configs = [
            {"agent_id": "Greedy Seller", "solar_generation": 6.0, "household_demand": 2.0, "battery_soc": 100.0, "preferred_p2p_sell_price": 8.0},
            {"agent_id": "Buyer", "solar_generation": 1.0, "household_demand": 4.0, "battery_soc": 0.0, "max_p2p_buy_price": 6.0},
        ]
        m = SmartGridModel(num_households=2, household_configs=configs, enable_p2p=True)
        telemetry = m.step()
        self.assertEqual(telemetry["p2p_trade_count"], 0)
        self.assertEqual(telemetry["grid_import"], 3.0)
        self.assertEqual(telemetry["grid_export"], 4.0)

    def test_edge_case_7_self_trading_prevented(self):
        """Edge Case 7: An agent cannot trade with itself."""
        buyer = self.model.get_agent_by_id("Household B")
        self_accept = Message(
            sender_id=buyer.agent_id,
            receiver_id=buyer.agent_id,
            message_type=MessageType.ACCEPT,
            energy_amount=2.0,
            state=EnergyState.DEFICIT,
            timestamp=1,
            metadata={"price_per_kwh": 5.0},
        )
        trade = NegotiationProtocol.settle_trade(buyer, buyer, self_accept, "INVALID")
        self.assertIsNone(trade)

    def test_edge_case_8_stale_offer_rejected(self):
        """Edge Case 8: Stale offers from previous timesteps are ignored."""
        buyer = self.model.get_agent_by_id("Household B")
        stale_offer = Message(
            sender_id="Household A",
            receiver_id=buyer.agent_id,
            message_type=MessageType.OFFER,
            energy_amount=3.0,
            state=EnergyState.SURPLUS,
            timestamp=0,  # Old timestep
            metadata={"price_per_kwh": 5.0},
        )
        accepted, rejected = NegotiationProtocol.evaluate_offers(buyer, [stale_offer], current_step=1)
        self.assertEqual(len(accepted), 0)


if __name__ == "__main__":
    unittest.main()
