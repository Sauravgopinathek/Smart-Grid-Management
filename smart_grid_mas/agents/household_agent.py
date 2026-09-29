from typing import List, Optional, Any, Dict, Tuple
import mesa
from smart_grid_mas.energy.energy_state import EnergyState, AgentAction
from smart_grid_mas.communication.message import Message, MessageType
from smart_grid_mas.negotiation.trade import Trade, TradeStatus
from smart_grid_mas.negotiation.negotiation_protocol import NegotiationProtocol
from smart_grid_mas.planning.astar_planner import AStarPlanner, PlanningResult
from smart_grid_mas.planning.planning_state import PlanningAction

# Physical simulation discrete timestep duration (Hours)
TIME_STEP_HOURS: float = 1.0

# Smallest amount worth negotiating over (1 Wh). Prevents extra negotiation
# rounds being spent on floating-point / rounding remainders.
MIN_TRADE_KWH: float = 1e-3


class HouseholdAgent(mesa.Agent):
    """Autonomous Household Agent in a decentralized smart grid.
    
    Each household represents a microgrid node with:
    - Sensors: solar generation, demand, battery state of charge (SOC), neighbor messages
    - Actuators: charge battery, discharge battery, consume energy, sell, buy
    - Local Decision Logic: deterministic evaluation layer & P2P negotiation protocol
    - Communication: direct and broadcast message passing for decentralized coordination
    - Energy Accounting: strict tracking of local solar, battery, P2P trades, and grid exchange
    
    Adheres strictly to Review 1 & Review 2 architecture:
    - NO centralized controller making decisions for the agent.
    - Partial observability: decisions rely exclusively on local state and received messages.
    - Discrete-time sequential execution: state persists and updates across timesteps.
    - Four-tier Energy Priority:
        1. Local Solar Generation
        2. Local Battery Storage
        3. Peer-to-Peer (P2P) Negotiation & Direct Trading
        4. External Utility Grid Fallback
    """

    def __init__(
        self,
        model: mesa.Model,
        agent_id: str,
        solar_generation: float = 0.0,
        household_demand: float = 0.0,
        battery_capacity: float = 10.0,
        battery_soc: float = 50.0,
        max_charge_rate_kw: float = 5.0,
        max_discharge_rate_kw: float = 5.0,
        max_p2p_buy_price: float = 6.0,
        preferred_p2p_sell_price: float = 5.0,
        planning_enabled: bool = False,
        planner: Optional[AStarPlanner] = None,
        planning_horizon: int = 12,
    ) -> None:
        super().__init__(model)
        self.agent_id: str = agent_id

        # Sensors / Perception attributes (physical units: kW, kWh, %)
        self.solar_generation: float = float(solar_generation)           # kW
        self.household_demand: float = float(household_demand)           # kW
        self.battery_capacity: float = float(battery_capacity)           # kWh
        self.battery_soc: float = float(battery_soc)                     # % (0.0 to 100.0)
        self.max_charge_rate_kw: float = float(max_charge_rate_kw)       # kW
        self.max_discharge_rate_kw: float = float(max_discharge_rate_kw) # kW

        # Module 2 Pricing Configurations (₹/kWh)
        self.max_p2p_buy_price: float = float(max_p2p_buy_price)
        self.preferred_p2p_sell_price: float = float(preferred_p2p_sell_price)

        # Module 4 Planning Configurations
        self.planning_enabled: bool = bool(planning_enabled)
        self.planning_horizon: int = int(planning_horizon)
        self.planner: Optional[AStarPlanner] = planner
        if self.planning_enabled and self.planner is None:
            self.planner = AStarPlanner(horizon=self.planning_horizon)
        self.solar_forecast: Optional[List[float]] = None
        self.demand_forecast: Optional[List[float]] = None
        self.last_planning_result: Optional[PlanningResult] = None

        # Local state & calculation
        self.energy_balance: float = 0.0
        self.state: EnergyState = EnergyState.BALANCED
        self.current_action: AgentAction = AgentAction.CONSUME

        # Energy buffers for Tier 2 -> Tier 3 transition (kWh)
        self.available_surplus: float = 0.0
        self.remaining_deficit: float = 0.0
        self.planned_battery_flow: float = 0.0  # + for charge, - for discharge (kWh)

        # Actuator / exchange metrics for the current step (kW or kWh)
        self.grid_import: float = 0.0
        self.grid_export: float = 0.0
        self.battery_flow: float = 0.0
        self.unmet_demand: float = 0.0
        self.curtailed_energy: float = 0.0      # surplus that could not be used/exported (islanded)
        self.charge_from_purchase: float = 0.0  # planned charge that must be bought (P2P/grid)

        # P2P Trading Metrics (Step and Cumulative)
        self.p2p_energy_bought: float = 0.0
        self.p2p_energy_sold: float = 0.0
        self.p2p_cost: float = 0.0
        self.p2p_revenue: float = 0.0
        self.completed_trades: List[Trade] = []

        # Communication foundation
        self.received_messages: List[Message] = []
        self.neighbors: List["HouseholdAgent"] = []
        self._processed_accept_ids: set = set()

        # Perform initial state observation
        self.observe_local_state()

    def set_neighbors(self, neighbors: List["HouseholdAgent"]) -> None:
        """Register neighboring household agents for peer communication."""
        self.neighbors = [n for n in neighbors if n.agent_id != self.agent_id]

    def enable_planning(self, horizon: int = 12) -> None:
        """Enable A* local planning for this agent."""
        self.planning_enabled = True
        self.planning_horizon = horizon
        if self.planner is None or self.planner.horizon != horizon:
            self.planner = AStarPlanner(horizon=horizon)

    def disable_planning(self) -> None:
        """Revert to greedy baseline decision logic."""
        self.planning_enabled = False

    def set_forecasts(self, solar_forecast: List[float], demand_forecast: List[float]) -> None:
        """Set future solar and demand predictions for receding-horizon lookahead."""
        self.solar_forecast = list(solar_forecast)
        self.demand_forecast = list(demand_forecast)

    def observe_local_state(self) -> None:
        """PHASE 1: Observe current local energy state & perform Tier 1/Tier 2 allocation.
        
        Calculates:
        1. Net power balance: solar_generation - household_demand (kW)
        2. Energy balance for timestep: power * TIME_STEP_HOURS (kWh)
        3. Local Battery allocation (Tier 2):
           - If planning enabled: optimizes trajectory via A* search over horizon H.
           - If greedy baseline: immediate heuristic allocation.
        """
        # Ensure battery SOC stays within valid physical bounds [0, 100]
        self.battery_soc = max(0.0, min(100.0, self.battery_soc))

        # Reset per-step exchange variables
        self.grid_import = 0.0
        self.grid_export = 0.0
        self.battery_flow = 0.0
        self.unmet_demand = 0.0
        self.curtailed_energy = 0.0
        self.charge_from_purchase = 0.0
        self.p2p_energy_bought = 0.0
        self.p2p_energy_sold = 0.0
        self.p2p_cost = 0.0
        self.p2p_revenue = 0.0
        self._processed_accept_ids.clear()

        # Net balance = generation - demand (kW)
        self.energy_balance = round(self.solar_generation - self.household_demand, 4)
        gross_energy_kwh = abs(self.energy_balance) * TIME_STEP_HOURS

        if self.planning_enabled and self.planner is not None:
            self._observe_with_planning()
        else:
            self._observe_greedy_baseline(gross_energy_kwh)

    def _observe_greedy_baseline(self, gross_energy_kwh: float) -> None:
        """Baseline greedy allocation (Modules 1-3)."""
        if self.energy_balance > 1e-6:
            self.state = EnergyState.SURPLUS
            # Tier 2: Use local battery to absorb surplus if room exists
            current_stored_kwh = (self.battery_soc / 100.0) * self.battery_capacity
            chargeable_space_kwh = max(0.0, self.battery_capacity - current_stored_kwh)
            max_charge_kwh = self.max_charge_rate_kw * TIME_STEP_HOURS
            battery_charge_kwh = min(gross_energy_kwh, chargeable_space_kwh, max_charge_kwh)

            self.planned_battery_flow = round(battery_charge_kwh, 4)
            self.available_surplus = round(gross_energy_kwh - battery_charge_kwh, 4)
            self.remaining_deficit = 0.0

        elif self.energy_balance < -1e-6:
            self.state = EnergyState.DEFICIT
            # Tier 2: Use local battery to supply deficit if stored energy exists
            current_stored_kwh = (self.battery_soc / 100.0) * self.battery_capacity
            max_discharge_kwh = self.max_discharge_rate_kw * TIME_STEP_HOURS
            battery_discharge_kwh = min(gross_energy_kwh, current_stored_kwh, max_discharge_kwh)

            self.planned_battery_flow = -round(battery_discharge_kwh, 4)
            self.remaining_deficit = round(gross_energy_kwh - battery_discharge_kwh, 4)
            self.available_surplus = 0.0

        else:
            self.state = EnergyState.BALANCED
            self.energy_balance = 0.0
            self.planned_battery_flow = 0.0
            self.available_surplus = 0.0
            self.remaining_deficit = 0.0

    def _observe_with_planning(self) -> None:
        """A* Predictive Trajectory Optimization (Module 4)."""
        current_step = getattr(self.model, "current_step", 1)
        current_hour = (current_step - 1) % 24

        H = self.planner.horizon if self.planner is not None else self.planning_horizon
        s_fc = list(self.solar_forecast) if self.solar_forecast is not None else [self.solar_generation] * H
        d_fc = list(self.demand_forecast) if self.demand_forecast is not None else [self.household_demand] * H

        # The current hour is OBSERVED, not forecast: overwrite step 0 with the
        # live sensor readings so an unforecast shock (e.g. sudden cloud cover)
        # is reflected in the action the agent actually commits.
        if s_fc:
            s_fc[0] = self.solar_generation
        if d_fc:
            d_fc[0] = self.household_demand

        grid_avail = True
        if hasattr(self.model, "utility_grid") and self.model.utility_grid is not None:
            grid_avail = getattr(self.model.utility_grid, "is_available", True)

        plan_res = self.planner.plan(
            start_hour=current_hour,
            initial_soc=self.battery_soc,
            battery_capacity=self.battery_capacity,
            max_charge_rate_kw=self.max_charge_rate_kw,
            max_discharge_rate_kw=self.max_discharge_rate_kw,
            solar_forecast=s_fc,
            demand_forecast=d_fc,
            is_grid_available=grid_avail,
        )
        self.last_planning_result = plan_res
        self.planned_battery_flow = plan_res.first_battery_flow

        net_balance = round(self.solar_generation - self.household_demand, 4)
        if self.planned_battery_flow > 1e-6:
            # Charging: the part of the charge not covered by local solar surplus
            # must be bought (P2P or grid). It is tracked separately so that, if
            # nobody can supply it, the charge is reduced instead of energy being
            # created from nothing.
            solar_to_batt = min(max(0.0, net_balance), self.planned_battery_flow)
            self.charge_from_purchase = round(self.planned_battery_flow - solar_to_batt, 4)
            if net_balance >= 0:
                self.available_surplus = round(net_balance - solar_to_batt, 4)
                self.remaining_deficit = self.charge_from_purchase
            else:
                self.available_surplus = 0.0
                self.remaining_deficit = round(abs(net_balance) + self.planned_battery_flow, 4)

            if self.remaining_deficit > 1e-6:
                self.state = EnergyState.DEFICIT
            elif self.available_surplus > 1e-6:
                self.state = EnergyState.SURPLUS
            else:
                self.state = EnergyState.BALANCED
        elif self.planned_battery_flow < -1e-6:
            # Discharging
            discharge_amt = abs(self.planned_battery_flow)
            if net_balance < 0:
                def_amt = abs(net_balance)
                leftover_def = max(0.0, def_amt - discharge_amt)
                self.remaining_deficit = round(leftover_def, 4)
                self.available_surplus = 0.0
                self.state = EnergyState.DEFICIT if leftover_def > 1e-6 else EnergyState.BALANCED
            else:
                self.available_surplus = round(net_balance + discharge_amt, 4)
                self.remaining_deficit = 0.0
                self.state = EnergyState.SURPLUS
        else:
            # HOLD (0 flow)
            if net_balance > 1e-6:
                self.state = EnergyState.SURPLUS
                self.available_surplus = round(net_balance, 4)
                self.remaining_deficit = 0.0
            elif net_balance < -1e-6:
                self.state = EnergyState.DEFICIT
                self.remaining_deficit = round(abs(net_balance), 4)
                self.available_surplus = 0.0
            else:
                self.state = EnergyState.BALANCED
                self.available_surplus = 0.0
                self.remaining_deficit = 0.0

    def evaluate_local_action(self) -> AgentAction:
        """LOCAL DECISION LOGIC: Baseline deterministic classification.
        
        Preserved for baseline evaluation and compatibility with Foundation tests.
        """
        if self.state == EnergyState.SURPLUS:
            if self.battery_soc < 100.0:
                return AgentAction.CHARGE
            else:
                return AgentAction.SELL
        elif self.state == EnergyState.DEFICIT:
            if self.battery_soc > 0.0:
                return AgentAction.DISCHARGE
            else:
                return AgentAction.BUY
        else:
            return AgentAction.CONSUME

    def broadcast_status(self, only_if_tradable: bool = False) -> None:
        """PHASE 2: Share surplus/deficit availability with neighbor agents.

        Args:
            only_if_tradable: used in renegotiation rounds; the agent only
                re-announces itself if it still has surplus to sell or deficit
                to buy, with its UPDATED amount.
        """
        current_step = getattr(self.model, "current_step", 1)
        if only_if_tradable:
            if self.state == EnergyState.SURPLUS and self.available_surplus < MIN_TRADE_KWH:
                return
            if self.state == EnergyState.DEFICIT and self.remaining_deficit < MIN_TRADE_KWH:
                return
        if self.state == EnergyState.SURPLUS:
            # Broadcast availability (positive energy amount)
            amount = self.available_surplus if self.available_surplus > 1e-6 else abs(self.energy_balance)
            msg = Message(
                sender_id=self.agent_id,
                receiver_id="BROADCAST",
                message_type=MessageType.SURPLUS,
                energy_amount=round(amount, 4),
                state=self.state,
                timestamp=current_step,
                metadata={"price_per_kwh": round(self.preferred_p2p_sell_price, 2)},
            )
            self._send_to_neighbors(msg)
        elif self.state == EnergyState.DEFICIT:
            amount = self.remaining_deficit if self.remaining_deficit > 1e-6 else abs(self.energy_balance)
            msg = Message(
                sender_id=self.agent_id,
                receiver_id="BROADCAST",
                message_type=MessageType.DEFICIT,
                energy_amount=round(amount, 4),
                state=self.state,
                timestamp=current_step,
            )
            self._send_to_neighbors(msg)

    def _send_to_neighbors(self, message: Message) -> None:
        """Deliver a message to all registered neighbors."""
        if hasattr(self.model, "record_message"):
            self.model.record_message(message)
        for neighbor in self.neighbors:
            neighbor.receive_message(message)

    def send_direct_message(self, receiver: "HouseholdAgent", message: Message) -> None:
        """Send a point-to-point message directly to a specific neighbor agent."""
        if hasattr(self.model, "record_message"):
            self.model.record_message(message)
        receiver.receive_message(message)

    def receive_message(self, message: Message) -> None:
        """Receive an incoming structured message from another agent into local inbox."""
        self.received_messages.append(message)

    def clear_inbox(self) -> None:
        """Clear received messages after processing."""
        self.received_messages.clear()

    # =========================================================================
    # MODULE 2: DECENTRALIZED P2P NEGOTIATION PHASES
    # =========================================================================

    def send_p2p_requests(self, current_step: int) -> None:
        """PHASE 3: Deficit agent identifies needs and sends REQUESTs to surplus peers."""
        if self.state != EnergyState.DEFICIT or self.remaining_deficit <= 1e-6:
            return

        # Find candidate surplus neighbors from received broadcasts
        # Sellers advertise their asking price in the SURPLUS broadcast; a buyer
        # does not waste a REQUEST on a seller it could never afford.
        surplus_neighbors = [
            m.sender_id for m in self.received_messages
            if m.message_type == MessageType.SURPLUS
            and m.energy_amount > 1e-6
            and m.sender_id != self.agent_id
            and (m.metadata or {}).get("price_per_kwh", 0.0) <= self.max_p2p_buy_price + 1e-9
        ]

        # Dispatch REQUEST to eligible surplus neighbors
        for neighbor in self.neighbors:
            if neighbor.agent_id in surplus_neighbors or (not surplus_neighbors and neighbor.agent_id != self.agent_id):
                req_msg = NegotiationProtocol.create_request(
                    buyer_id=self.agent_id,
                    seller_id=neighbor.agent_id,
                    requested_energy_kwh=self.remaining_deficit,
                    max_price_per_kwh=self.max_p2p_buy_price,
                    timestamp=current_step,
                )
                self.send_direct_message(neighbor, req_msg)

    def evaluate_and_respond_to_requests(self, current_step: int) -> None:
        """PHASE 4 & 5: Surplus agent evaluates REQUESTs and dispatches OFFERs."""
        if self.state != EnergyState.SURPLUS or self.available_surplus <= 1e-6:
            return

        # Collect current-step requests addressed to this agent
        requests = [
            m for m in self.received_messages
            if m.message_type == MessageType.REQUEST and m.receiver_id == self.agent_id and m.timestamp == current_step
        ]

        # Reserve surplus across all simultaneous requests so the same kWh is
        # never promised to two buyers (prevents accepted-but-undelivered trades).
        requests.sort(key=lambda m: m.sender_id)
        # Total P2P export this step is limited by the inverter rating.
        export_headroom = max(0.0, self.max_charge_rate_kw * TIME_STEP_HOURS - self.p2p_energy_sold)
        offerable = min(self.available_surplus, export_headroom)
        shares = NegotiationProtocol.allocate_surplus(
            offerable, [r.energy_amount for r in requests]
        )

        for req, share in zip(requests, shares):
            offer_msg = NegotiationProtocol.evaluate_request(
                self, req, current_step, max_offer_kwh=share
            )
            if offer_msg:
                offer_msg.metadata["round"] = getattr(self.model, "current_round", 1)
                # Find target buyer agent
                buyer_agent = next((n for n in self.neighbors if n.agent_id == req.sender_id), None)
                if buyer_agent:
                    self.send_direct_message(buyer_agent, offer_msg)

    def evaluate_and_respond_to_offers(self, current_step: int) -> None:
        """PHASE 6 & 7: Deficit agent evaluates received OFFERs, sends ACCEPT / REJECT."""
        if self.state != EnergyState.DEFICIT or self.remaining_deficit <= 1e-6:
            return

        offers = [
            m for m in self.received_messages
            if m.message_type == MessageType.OFFER and m.receiver_id == self.agent_id and m.timestamp == current_step
        ]

        if not offers:
            return

        accepted_tuples, rejected_offers = NegotiationProtocol.evaluate_offers(self, offers, current_step)

        # Dispatch ACCEPT messages
        for offer_msg, energy_take in accepted_tuples:
            seller_agent = next((n for n in self.neighbors if n.agent_id == offer_msg.sender_id), None)
            if seller_agent:
                price = offer_msg.metadata.get("price_per_kwh", 5.0) if offer_msg.metadata else 5.0
                accept_msg = NegotiationProtocol.create_accept(
                    buyer_id=self.agent_id,
                    seller_id=offer_msg.sender_id,
                    accepted_energy_kwh=energy_take,
                    price_per_kwh=price,
                    timestamp=current_step,
                )
                self.send_direct_message(seller_agent, accept_msg)

        # Dispatch REJECT messages
        for rej_offer in rejected_offers:
            seller_agent = next((n for n in self.neighbors if n.agent_id == rej_offer.sender_id), None)
            if seller_agent:
                reject_msg = NegotiationProtocol.create_reject(
                    buyer_id=self.agent_id,
                    seller_id=rej_offer.sender_id,
                    reason="Price exceeded limit or superior offer selected",
                    timestamp=current_step,
                )
                self.send_direct_message(seller_agent, reject_msg)

    def process_acceptances_and_settle(self, current_step: int) -> List[Trade]:
        """PHASE 8: Surplus agent processes incoming ACCEPT messages and settles trades."""
        settled_trades: List[Trade] = []
        if self.state != EnergyState.SURPLUS or self.available_surplus <= 1e-6:
            return settled_trades

        acceptances = [
            m for m in self.received_messages
            if m.message_type == MessageType.ACCEPT and m.receiver_id == self.agent_id and m.timestamp == current_step
        ]

        for acc in acceptances:
            rnd = getattr(self.model, "current_round", 1)
            trade_uid = f"{acc.sender_id}_{acc.timestamp}_{rnd}_{acc.energy_amount}"
            if trade_uid in self._processed_accept_ids:
                continue

            buyer_agent = next((n for n in self.neighbors if n.agent_id == acc.sender_id), None)
            if buyer_agent:
                trade_id = f"TRADE_T{current_step}_{self.agent_id}_{buyer_agent.agent_id}_{len(self.completed_trades)+1}"
                trade = NegotiationProtocol.settle_trade(self, buyer_agent, acc, trade_id)
                if trade:
                    self._processed_accept_ids.add(trade_uid)
                    settled_trades.append(trade)

        return settled_trades

    # =========================================================================
    # PHASE 9 & 10: PHYSICAL ACTUATION & UTILITY GRID FALLBACK
    # =========================================================================

    def execute_action(self) -> None:
        """PHASES 9 & 10: Settle residual imbalance with the Utility Grid, then commit battery flow.

        The grid is consulted BEFORE the battery is updated so that a planned
        charge that nobody could supply (e.g. grid offline) is reduced rather
        than creating energy. Per-step energy balance for every agent:

            solar + discharge + p2p_bought + grid_import + unmet
                = demand + charge + p2p_sold + grid_export + curtailed
        """
        grid_available = (
            hasattr(self.model, "utility_grid")
            and self.model.utility_grid is not None
            and getattr(self.model.utility_grid, "is_available", True)
        )

        # Phase 10a: residual deficit -> Utility Grid (or unmet when islanded)
        if self.remaining_deficit > 1e-6:
            supplied = self.model.utility_grid.supply(self.remaining_deficit) if grid_available else 0.0
            self.grid_import = round(supplied, 4)
            shortfall = max(0.0, self.remaining_deficit - supplied)
            # Unfunded battery charging is cancelled first; only real load becomes unmet.
            cancel_charge = min(shortfall, max(0.0, self.charge_from_purchase))
            if cancel_charge > 1e-9:
                self.planned_battery_flow = round(self.planned_battery_flow - cancel_charge, 4)
                self.charge_from_purchase = round(self.charge_from_purchase - cancel_charge, 4)
            self.unmet_demand = round(shortfall - cancel_charge, 4)

        # Phase 10b: residual surplus -> Utility Grid (or curtailed when islanded)
        if self.available_surplus > 1e-6:
            absorbed = self.model.utility_grid.absorb(self.available_surplus) if grid_available else 0.0
            self.grid_export = round(absorbed, 4)
            self.curtailed_energy = round(self.available_surplus - absorbed, 4)

        # Phase 9: commit (possibly reduced) battery flow
        current_stored_kwh = (self.battery_soc / 100.0) * self.battery_capacity
        new_stored_kwh = current_stored_kwh + self.planned_battery_flow
        self.battery_soc = round((new_stored_kwh / self.battery_capacity) * 100.0, 2)
        self.battery_soc = max(0.0, min(100.0, self.battery_soc))
        self.battery_flow = self.planned_battery_flow

        # Action classification (for display / telemetry)
        if self.state == EnergyState.DEFICIT:
            if self.p2p_energy_bought > 0 or self.grid_import > 0:
                self.current_action = AgentAction.BUY
            else:
                self.current_action = AgentAction.DISCHARGE
        elif self.state == EnergyState.SURPLUS:
            if self.p2p_energy_sold > 0 or self.grid_export > 0:
                self.current_action = AgentAction.SELL
            else:
                self.current_action = AgentAction.CHARGE
        else:
            self.current_action = AgentAction.CONSUME

    def step(self) -> None:
        """Direct step execution (used if agent is stepped independently)."""
        self.observe_local_state()
        self.broadcast_status()
        self.current_action = self.evaluate_local_action()
        self.execute_action()

    def update_environment(self, solar_kw: Optional[float] = None, demand_kw: Optional[float] = None) -> None:
        """DYNAMIC & STOCHASTIC: Update external solar generation and demand for next step."""
        if solar_kw is not None:
            self.solar_generation = float(solar_kw)
        if demand_kw is not None:
            self.household_demand = float(demand_kw)
