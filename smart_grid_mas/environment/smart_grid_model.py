from typing import List, Dict, Any, Optional
import mesa
from smart_grid_mas.agents.household_agent import HouseholdAgent, TIME_STEP_HOURS, MIN_TRADE_KWH
from smart_grid_mas.environment.utility_grid import UtilityGrid
from smart_grid_mas.energy.energy_state import EnergyState
from smart_grid_mas.negotiation.trade import Trade


DEFAULT_HOUSEHOLD_CONFIGS = [
    {
        "agent_id": "Household A",
        "solar_generation": 6.0,
        "household_demand": 3.0,
        "battery_capacity": 10.0,
        "battery_soc": 60.0,
        "max_charge_rate_kw": 5.0,
        "max_discharge_rate_kw": 5.0,
        "max_p2p_buy_price": 6.0,
        "preferred_p2p_sell_price": 5.0,
    },
    {
        "agent_id": "Household B",
        "solar_generation": 2.0,
        "household_demand": 5.0,
        "battery_capacity": 10.0,
        "battery_soc": 40.0,
        "max_charge_rate_kw": 5.0,
        "max_discharge_rate_kw": 5.0,
        "max_p2p_buy_price": 6.0,
        "preferred_p2p_sell_price": 5.0,
    },
    {
        "agent_id": "Household C",
        "solar_generation": 4.0,
        "household_demand": 4.0,
        "battery_capacity": 10.0,
        "battery_soc": 70.0,
        "max_charge_rate_kw": 5.0,
        "max_discharge_rate_kw": 5.0,
        "max_p2p_buy_price": 6.0,
        "preferred_p2p_sell_price": 5.0,
    },
]


class SmartGridModel(mesa.Model):
    """Decentralized Multi-Agent Smart Grid Simulation Model.
    
    Responsibilities:
    - Initialize simulation and instantiate autonomous HouseholdAgent nodes.
    - Maintain the external UtilityGrid (external source/sink, NOT a decision-maker).
    - Manage discrete simulation time steps across the 11-phase negotiation lifecycle.
    - Facilitate peer neighbor connections for decentralized communication.
    - Maintain transaction ledger and collect neighborhood-level telemetry.
    
    IMPORTANT:
    The model provides message transport and ledger bookkeeping. It NEVER assigns
    trades or selects winners. Individual HouseholdAgents negotiate autonomously.
    """

    def __init__(
        self,
        num_households: int = 3,
        household_configs: Optional[List[Dict[str, Any]]] = None,
        seed: Optional[int] = 42,
        rng: Optional[Any] = None,
        enable_p2p: bool = True,
        planning_mode: str = "GREEDY",
        planning_horizon: int = 12,
        max_negotiation_rounds: int = 3,
    ) -> None:
        effective_rng = rng if rng is not None else seed
        super().__init__(rng=effective_rng)

        self.num_households: int = num_households
        self.enable_p2p: bool = enable_p2p
        self.planning_mode: str = planning_mode.upper()
        self.planning_horizon: int = int(planning_horizon)
        self.current_step: int = 0
        self.max_negotiation_rounds: int = max(1, int(max_negotiation_rounds))
        self.current_round: int = 1
        self.negotiation_rounds_used: int = 0
        self.utility_grid: UtilityGrid = UtilityGrid(name="Main Utility Grid")

        # P2P Transaction Ledger
        self.trade_history: List[Trade] = []
        self.step_trades: List[Trade] = []
        self.step_messages: List[Any] = []
        self.message_history: List[Any] = []
        self.active_shocks: List[str] = []

        # Telemetry history & latest step cache
        self.latest_telemetry: Optional[Dict[str, Any]] = None
        self.telemetry_history: List[Dict[str, Any]] = []

        # Initialize household agents
        self._setup_households(household_configs)

        # Wire neighborhood communication channels
        self._connect_neighbors()

        # If A_STAR planning is requested, enable planning on all household agents
        if self.planning_mode in ("A_STAR", "ASTAR", "PLANNING"):
            for a in self.household_agents:
                a.enable_planning(horizon=self.planning_horizon)

        # Mesa 3.5.1 step wrapper to return telemetry for direct callers
        original_step = self.step
        def step_wrapper(*args, **kwargs) -> Dict[str, Any]:
            original_step(*args, **kwargs)
            return self.latest_telemetry
        self.step = step_wrapper

    def _setup_households(self, custom_configs: Optional[List[Dict[str, Any]]]) -> None:
        """Create and configure household agents dynamically."""
        configs = [dict(c) for c in custom_configs] if custom_configs is not None else [dict(c) for c in DEFAULT_HOUSEHOLD_CONFIGS]

        # If num_households exceeds provided configs, generate systematic variations
        for i in range(len(configs), self.num_households):
            solar = round(2.0 + (i % 5) * 1.5, 2)
            demand = round(2.5 + ((i + 2) % 4) * 1.2, 2)
            soc = round(30.0 + (i % 6) * 10.0, 1)
            configs.append({
                "agent_id": f"Household {chr(65 + i) if i < 26 else f'H{i+1}'}",
                "solar_generation": solar,
                "household_demand": demand,
                "battery_capacity": 10.0,
                "battery_soc": soc,
                "max_charge_rate_kw": 5.0,
                "max_discharge_rate_kw": 5.0,
                "max_p2p_buy_price": 6.0,
                "preferred_p2p_sell_price": 5.0,
            })

        # Instantiate agents for the requested num_households
        for i in range(self.num_households):
            cfg = configs[i]
            HouseholdAgent(
                model=self,
                agent_id=cfg["agent_id"],
                solar_generation=cfg.get("solar_generation", 0.0),
                household_demand=cfg.get("household_demand", 0.0),
                battery_capacity=cfg.get("battery_capacity", 10.0),
                battery_soc=cfg.get("battery_soc", 50.0),
                max_charge_rate_kw=cfg.get("max_charge_rate_kw", 5.0),
                max_discharge_rate_kw=cfg.get("max_discharge_rate_kw", 5.0),
                max_p2p_buy_price=cfg.get("max_p2p_buy_price", 6.0),
                preferred_p2p_sell_price=cfg.get("preferred_p2p_sell_price", 5.0),
            )

    def _connect_neighbors(self) -> None:
        """Register all peers as neighbors in the neighborhood network."""
        all_households = [a for a in self.agents if isinstance(a, HouseholdAgent)]
        for agent in all_households:
            agent.set_neighbors(all_households)

    @property
    def household_agents(self) -> List[HouseholdAgent]:
        """Convenience accessor for household agents."""
        return [a for a in self.agents if isinstance(a, HouseholdAgent)]

    def get_agent_by_id(self, agent_id: str) -> Optional[HouseholdAgent]:
        """Lookup an agent by its human-readable agent_id."""
        for agent in self.household_agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def record_trade(self, trade: Trade) -> None:
        """Ledger bookkeeping: record a confirmed P2P trade."""
        self.trade_history.append(trade)
        self.step_trades.append(trade)

    def record_message(self, message: Any) -> None:
        """Ledger bookkeeping: record an exchanged FIPA message."""
        self.step_messages.append(message)
        self.message_history.append(message)

    def step(self) -> Dict[str, Any]:
        """DISCRETE-TIME SIMULATION STEP: 11-Phase Lifecycle.
        
        PHASE 1: Observe local state (Tier 1 Solar & Tier 2 Battery allocation)
        PHASE 2: Broadcast SURPLUS / DEFICIT status
        PHASE 3: Deficit agents send REQUEST messages
        PHASE 4: Surplus agents evaluate REQUEST messages
        PHASE 5: Surplus agents send OFFER messages
        PHASE 6: Deficit agents evaluate OFFERS
        PHASE 7: Deficit agents send ACCEPT / REJECT
        PHASE 8: Accepted trades are settled and recorded
        PHASE 9: Battery physical state update
        PHASE 10: Utility Grid fallback for residual imbalances
        PHASE 11: Collect telemetry & bookkeeping
        """
        self.current_step += 1
        self.utility_grid.reset_step()
        self.step_trades.clear()
        self.step_messages.clear()

        households = self.household_agents

        # PHASE 1: Clear inboxes & Observe local physical state
        for agent in households:
            agent.clear_inbox()
            agent.observe_local_state()

        # PHASE 2: Decentralized Status Sharing
        for agent in households:
            agent.broadcast_status()

        # PHASES 3-8: Contract-Net negotiation, repeated for up to
        # `max_negotiation_rounds` rounds. Each round the agents re-announce
        # their UPDATED surplus/deficit; buyers whose needs were only partly met,
        # and sellers holding energy that other buyers declined, trade again.
        # Termination (no deadlock / livelock): stop as soon as a round settles
        # no trade, when no buyer or no seller is left, or at the round limit.
        self.negotiation_rounds_used = 0
        if self.enable_p2p:
            for rnd in range(1, self.max_negotiation_rounds + 1):
                self.current_round = rnd
                if rnd > 1:
                    buyers_left = any(
                        a.state == EnergyState.DEFICIT and a.remaining_deficit >= MIN_TRADE_KWH for a in households
                    )
                    sellers_left = any(
                        a.state == EnergyState.SURPLUS and a.available_surplus >= MIN_TRADE_KWH for a in households
                    )
                    if not (buyers_left and sellers_left):
                        break
                    for agent in households:
                        agent.clear_inbox()
                    for agent in households:
                        agent.broadcast_status(only_if_tradable=True)

                # PHASE 3: Deficit agents send REQUEST messages to surplus neighbors
                for agent in households:
                    agent.send_p2p_requests(self.current_step)

                # PHASE 4 & 5: Surplus agents evaluate REQUESTs and dispatch OFFERs
                for agent in households:
                    agent.evaluate_and_respond_to_requests(self.current_step)

                # PHASE 6 & 7: Deficit agents evaluate candidate OFFERs, send ACCEPT / REJECT
                for agent in households:
                    agent.evaluate_and_respond_to_offers(self.current_step)

                # PHASE 8: Surplus agents process ACCEPTs and execute trades
                settled_this_round = 0
                for agent in households:
                    trades = agent.process_acceptances_and_settle(self.current_step)
                    for t in trades:
                        if t not in self.trade_history:
                            self.record_trade(t)
                            settled_this_round += 1

                self.negotiation_rounds_used = rnd
                if settled_this_round == 0:
                    break  # no progress -> stop negotiating this step

        # PHASES 9 & 10: Commit battery changes & fallback residual to Utility Grid
        for agent in households:
            agent.execute_action()

        # PHASE 11: Collect neighborhood telemetry
        telemetry = self._collect_telemetry()
        self.latest_telemetry = telemetry
        self.telemetry_history.append(telemetry)
        return telemetry

    def _collect_telemetry(self) -> Dict[str, Any]:
        """Aggregate neighborhood telemetry for bookkeeping and observability."""
        households = self.household_agents
        total_solar = round(sum(a.solar_generation for a in households), 2)
        total_demand = round(sum(a.household_demand for a in households), 2)
        
        total_surplus = round(sum(a.energy_balance for a in households if a.state == EnergyState.SURPLUS), 2)
        total_deficit = round(sum(abs(a.energy_balance) for a in households if a.state == EnergyState.DEFICIT), 2)
        
        grid_import = round(self.utility_grid.current_step_import, 2)
        grid_export = round(self.utility_grid.current_step_export, 2)

        # Module 2 P2P Metrics
        step_p2p_energy = round(sum(t.energy_amount for t in self.step_trades), 2)
        step_p2p_value = round(sum(t.total_price for t in self.step_trades), 2)
        step_p2p_count = len(self.step_trades)

        total_p2p_energy = round(sum(t.energy_amount for t in self.trade_history), 2)
        total_p2p_value = round(sum(t.total_price for t in self.trade_history), 2)

        # P2P Deficit Coverage Ratio
        deficit_coverage = round((step_p2p_energy / total_deficit) * 100.0, 1) if total_deficit > 1e-6 else 100.0

        agent_details = []
        for a in households:
            plan_res = getattr(a, "last_planning_result", None)
            agent_details.append({
                "agent_id": a.agent_id,
                "solar_generation": a.solar_generation,
                "household_demand": a.household_demand,
                "battery_soc": a.battery_soc,
                "energy_balance": a.energy_balance,
                "state": a.state.value,
                "action": a.current_action.value,
                "available_surplus": a.available_surplus,
                "remaining_deficit": a.remaining_deficit,
                "unmet_demand": getattr(a, "unmet_demand", 0.0),
                "grid_import": a.grid_import,
                "grid_export": a.grid_export,
                "battery_flow": a.battery_flow,
                "curtailed_energy": a.curtailed_energy,
                "planned_battery_flow": getattr(a, "planned_battery_flow", 0.0),
                "planning_enabled": getattr(a, "planning_enabled", False),
                "nodes_expanded": plan_res.nodes_expanded if plan_res is not None else 0,
                "p2p_bought": a.p2p_energy_bought,
                "p2p_sold": a.p2p_energy_sold,
                "p2p_cost": a.p2p_cost,
                "p2p_revenue": a.p2p_revenue,
                "messages_received_count": len(a.received_messages),
            })

        total_unmet = round(sum(getattr(a, "unmet_demand", 0.0) for a in households), 2)
        avg_soc = round(sum(a.battery_soc for a in households) / len(households), 1) if households else 0.0
        min_soc = round(min(a.battery_soc for a in households), 1) if households else 0.0
        grid_avail = bool(getattr(self.utility_grid, "is_available", True))
        active_shocks_list = list(getattr(self, "active_shocks", []))
        total_nodes = sum(
            a.last_planning_result.nodes_expanded
            for a in households
            if getattr(a, "last_planning_result", None) is not None
        )

        return {
            "step": self.current_step,
            "hour": (self.current_step - 1) % 24,
            "planning_mode": self.planning_mode,
            "total_nodes_expanded": total_nodes,
            "total_solar_generation": total_solar,
            "total_demand": total_demand,
            "total_surplus": total_surplus,
            "total_deficit": total_deficit,
            "grid_import": grid_import,
            "grid_export": grid_export,
            "unmet_demand": total_unmet,
            "curtailed_energy": round(sum(a.curtailed_energy for a in households), 4),
            "average_battery_soc": avg_soc,
            "minimum_battery_soc": min_soc,
            "grid_available": grid_avail,
            "active_shocks": active_shocks_list,
            "p2p_energy_traded": step_p2p_energy,
            "negotiation_rounds": self.negotiation_rounds_used,
            "p2p_trade_count": step_p2p_count,
            "p2p_trade_value": step_p2p_value,
            "p2p_deficit_coverage_percent": deficit_coverage,
            "cumulative_p2p_energy_traded": total_p2p_energy,
            "cumulative_p2p_trade_value": total_p2p_value,
            "trades": [
                {
                    "trade_id": t.trade_id,
                    "seller": t.seller_id,
                    "buyer": t.buyer_id,
                    "amount": t.energy_amount,
                    "price": t.price_per_kwh,
                    "total": t.total_price,
                    "status": t.status.value,
                }
                for t in self.step_trades
            ],
            "messages": [
                {
                    "sender": m.sender_id,
                    "receiver": m.receiver_id,
                    "type": m.message_type.value if hasattr(m.message_type, "value") else str(m.message_type),
                    "amount": round(m.energy_amount, 4),
                    "state": m.state.value if hasattr(m.state, "value") else str(m.state),
                    "timestamp": m.timestamp,
                    "metadata": m.metadata or {},
                }
                for m in self.step_messages
            ],
            "agents": agent_details,
        }
