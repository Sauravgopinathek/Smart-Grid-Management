import heapq
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from smart_grid_mas.planning.planning_state import PlanningAction, PlanningState
from smart_grid_mas.planning.cost_function import CostFunction, TOUTariff


@dataclass
class PlanningResult:
    """Encapsulates the outcome of an A* local planning search."""
    actions: List[PlanningAction]
    states: List[PlanningState]
    total_cost: float
    nodes_expanded: int
    planning_horizon: int
    computation_time_ms: float
    first_action: PlanningAction
    first_battery_flow: float
    is_optimal: bool = True


class AStarPlanner:
    """Decentralized A* Local Trajectory Planner for HouseholdAgent.
    
    Operates strictly within the local agent boundary:
    - Finds the optimal battery charge/discharge schedule over horizon H.
    - Minimizes total energy costs (TOU tariffs, cycling wear, unmet demand penalty).
    - Employs an admissible, consistent heuristic function h(n).
    - Discretizes state-space via closed-set memoization for rapid convergence.
    - Supports receding-horizon execution (commit first action, observe, replan).
    """

    UNMET_URGENCY_COST: float = 0.01  # Rs per kWh of unmet demand per remaining horizon hour

    def __init__(
        self,
        horizon: int = 6,
        cost_function: Optional[CostFunction] = None,
        soc_resolution: float = 0.5,
    ) -> None:
        self.horizon: int = max(1, int(horizon))
        self.cost_function: CostFunction = cost_function if cost_function is not None else CostFunction()
        self.soc_resolution: float = float(soc_resolution)

    def plan(
        self,
        start_hour: int,
        initial_soc: float,
        battery_capacity: float = 10.0,
        max_charge_rate_kw: float = 5.0,
        max_discharge_rate_kw: float = 5.0,
        solar_forecast: Optional[List[float]] = None,
        demand_forecast: Optional[List[float]] = None,
        is_grid_available: bool = True,
        grid_available_forecast: Optional[List[bool]] = None,
    ) -> PlanningResult:
        """Execute A* search to compute the optimal battery action schedule over horizon H.
        
        Args:
            start_hour: Current simulation hour of the day [0, 23].
            initial_soc: Current battery State of Charge [%] [0.0, 100.0].
            battery_capacity: Total capacity in kWh.
            max_charge_rate_kw: Maximum charging power in kW.
            max_discharge_rate_kw: Maximum discharging power in kW.
            solar_forecast: List of predicted solar generation (kW) for next H steps.
            demand_forecast: List of predicted household demand (kW) for next H steps.
            is_grid_available: Whether utility grid is currently online.
            grid_available_forecast: Optional per-step forecast of grid availability.
            
        Returns:
            PlanningResult containing optimal action trajectory and search telemetry.
        """
        start_time = time.perf_counter()

        H = self.horizon
        solar = list(solar_forecast) if solar_forecast is not None else [0.0] * H
        demand = list(demand_forecast) if demand_forecast is not None else [2.5] * H

        # Pad forecasts if shorter than horizon
        if len(solar) < H:
            solar.extend([0.0] * (H - len(solar)))
        if len(demand) < H:
            demand.extend([2.5] * (H - len(demand)))

        grid_avail_list = (
            list(grid_available_forecast)
            if grid_available_forecast is not None
            else [is_grid_available] * H
        )
        if len(grid_avail_list) < H:
            grid_avail_list.extend([is_grid_available] * (H - len(grid_avail_list)))

        # Clamp initial SOC
        clamped_soc = max(0.0, min(100.0, float(initial_soc)))
        init_stored_kwh = (clamped_soc / 100.0) * battery_capacity

        # Compute initial heuristic h(0)
        h0 = self.cost_function.calculate_heuristic(
            current_stored_kwh=init_stored_kwh,
            remaining_solar_forecast=solar,
            remaining_demand_forecast=demand,
            remaining_hours=[(start_hour + i) % 24 for i in range(H)],
            remaining_grid_available=grid_avail_list,
        )

        root = PlanningState(
            hour=start_hour % 24,
            step_index=0,
            battery_soc=clamped_soc,
            battery_capacity=battery_capacity,
            action=None,
            battery_flow=0.0,
            grid_import=0.0,
            grid_export=0.0,
            unmet_demand=0.0,
            step_cost=0.0,
            cumulative_cost=0.0,
            heuristic_cost=h0,
            total_cost=h0,
            parent=None,
        )

        # Priority queue entries: (f_cost, tie_breaker_counter, state_node)
        open_set: List[Tuple[float, int, PlanningState]] = []
        counter = 0
        heapq.heappush(open_set, (root.total_cost, counter, root))

        # Closed set: key -> lowest g_cost observed
        closed_set: Dict[tuple, float] = {}
        nodes_expanded = 0
        goal_state: Optional[PlanningState] = None

        while open_set:
            f, _, current = heapq.heappop(open_set)

            # Check if goal horizon is reached
            if current.step_index >= H:
                goal_state = current
                break

            state_key = current.state_key(self.soc_resolution)
            if state_key in closed_set and closed_set[state_key] <= current.cumulative_cost + 1e-6:
                continue
            closed_set[state_key] = current.cumulative_cost
            nodes_expanded += 1

            for succ in self._successors(
                current, start_hour, solar, demand, grid_avail_list,
                battery_capacity, max_charge_rate_kw, max_discharge_rate_kw, H,
            ):
                succ_key = succ.state_key(self.soc_resolution)
                if succ_key in closed_set and closed_set[succ_key] <= succ.cumulative_cost + 1e-6:
                    continue

                counter += 1
                heapq.heappush(open_set, (succ.total_cost, counter, succ))

        # Reconstruct path
        actions: List[PlanningAction] = []
        states: List[PlanningState] = []
        curr = goal_state if goal_state is not None else root

        while curr.parent is not None:
            if curr.action is not None:
                actions.append(curr.action)
            states.append(curr)
            curr = curr.parent
        states.append(curr)

        actions.reverse()
        states.reverse()

        first_action = actions[0] if actions else PlanningAction.HOLD
        first_battery_flow = states[1].battery_flow if len(states) > 1 else 0.0
        total_cost = goal_state.cumulative_cost if goal_state is not None else 0.0

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return PlanningResult(
            actions=actions,
            states=states,
            total_cost=round(total_cost, 4),
            nodes_expanded=nodes_expanded,
            planning_horizon=H,
            computation_time_ms=round(elapsed_ms, 2),
            first_action=first_action,
            first_battery_flow=round(first_battery_flow, 4),
            is_optimal=goal_state is not None,
        )

    def _successors(
        self,
        current: PlanningState,
        start_hour: int,
        solar: List[float],
        demand: List[float],
        grid_avail_list: List[bool],
        battery_capacity: float,
        max_charge_rate_kw: float,
        max_discharge_rate_kw: float,
        H: int,
    ) -> List[PlanningState]:
        """Generate every successor state of `current` (one per viable action)."""
        k = current.step_index
        step_hour = (start_hour + k) % 24
        next_hour = (step_hour + 1) % 24
        step_solar = solar[k]
        step_demand = demand[k]
        grid_online = grid_avail_list[k]

        stored_kwh = (current.battery_soc / 100.0) * battery_capacity
        space_kwh = max(0.0, battery_capacity - stored_kwh)
        max_chg_kwh = min(max_charge_rate_kw, space_kwh)
        max_dis_kwh = min(max_discharge_rate_kw, stored_kwh)

        # Determine viable candidate actions for this step
        candidate_actions: List[PlanningAction] = [PlanningAction.HOLD]
        net_power = step_solar - step_demand

        if net_power > 1e-6:
            # Solar surplus: charging from solar is viable if space exists
            if max_chg_kwh > 1e-4:
                candidate_actions.append(PlanningAction.CHARGE_SOLAR)
        elif net_power < -1e-6:
            # Deficit: discharging to support load is viable if stored energy exists
            if max_dis_kwh > 1e-4:
                candidate_actions.append(PlanningAction.DISCHARGE)

        # Grid charging for arbitrage or backup reserve: viable when the grid is
        # online, space exists, and either the off-peak rate applies or an outage
        # is forecast for the next step.
        if grid_online and max_chg_kwh > 1e-4:
            tariff_rate = self.cost_function.tariff.get_import_rate(step_hour)
            if tariff_rate <= TOUTariff.OFF_PEAK_RATE or (k + 1 < H and not grid_avail_list[k + 1]):
                candidate_actions.append(PlanningAction.CHARGE_GRID)

        return [
            self._apply_action(
                current=current,
                action=act,
                step_index=k,
                step_hour=step_hour,
                next_hour=next_hour,
                solar=step_solar,
                demand=step_demand,
                grid_online=grid_online,
                battery_capacity=battery_capacity,
                max_chg_kwh=max_chg_kwh,
                max_dis_kwh=max_dis_kwh,
                solar_forecast=solar,
                demand_forecast=demand,
                H=H,
                grid_forecast=grid_avail_list,
            )
            for act in candidate_actions
        ]

    def exhaustive_optimal_cost(
        self,
        start_hour: int,
        initial_soc: float,
        battery_capacity: float = 10.0,
        max_charge_rate_kw: float = 5.0,
        max_discharge_rate_kw: float = 5.0,
        solar_forecast: Optional[List[float]] = None,
        demand_forecast: Optional[List[float]] = None,
        is_grid_available: bool = True,
        grid_available_forecast: Optional[List[bool]] = None,
    ) -> float:
        """Reference solver: enumerate EVERY action sequence (no heuristic, no pruning).

        Exponential in H, so only for verification with small horizons. Used by the
        test suite to check that A* returns the true optimum.
        """
        H = self.horizon
        solar = list(solar_forecast or [0.0] * H)[:H]
        demand = list(demand_forecast or [2.5] * H)[:H]
        solar += [0.0] * (H - len(solar))
        demand += [2.5] * (H - len(demand))
        grid = list(grid_available_forecast) if grid_available_forecast is not None else [is_grid_available] * H
        grid += [is_grid_available] * (H - len(grid))

        root = PlanningState(
            hour=start_hour % 24,
            step_index=0,
            battery_soc=max(0.0, min(100.0, float(initial_soc))),
            battery_capacity=battery_capacity,
        )
        best = float("inf")
        stack = [root]
        while stack:
            node = stack.pop()
            if node.step_index >= H:
                best = min(best, node.cumulative_cost)
                continue
            stack.extend(self._successors(
                node, start_hour, solar, demand, grid,
                battery_capacity, max_charge_rate_kw, max_discharge_rate_kw, H,
            ))
        return round(best, 4)

    def _apply_action(
        self,
        current: PlanningState,
        action: PlanningAction,
        step_index: int,
        step_hour: int,
        next_hour: int,
        solar: float,
        demand: float,
        grid_online: bool,
        battery_capacity: float,
        max_chg_kwh: float,
        max_dis_kwh: float,
        solar_forecast: List[float],
        demand_forecast: List[float],
        H: int,
        grid_forecast: Optional[List[bool]] = None,
    ) -> PlanningState:
        """Compute state transition and physical accounting for a given action."""
        net_balance = solar - demand

        battery_flow = 0.0
        grid_import = 0.0
        grid_export = 0.0
        unmet_demand = 0.0

        if action == PlanningAction.HOLD:
            battery_flow = 0.0
            if net_balance >= 0:
                if grid_online:
                    grid_export = net_balance
                else:
                    grid_export = 0.0
            else:
                deficit = abs(net_balance)
                if grid_online:
                    grid_import = deficit
                else:
                    unmet_demand = deficit

        elif action == PlanningAction.CHARGE_SOLAR:
            surplus = max(0.0, net_balance)
            charge_kwh = min(surplus, max_chg_kwh)
            battery_flow = charge_kwh
            leftover_surplus = surplus - charge_kwh
            if grid_online:
                grid_export = leftover_surplus
            else:
                grid_export = 0.0

        elif action == PlanningAction.CHARGE_GRID:
            # Maximize charge using surplus solar first, and grid import for the rest
            target_charge = max_chg_kwh
            battery_flow = target_charge
            if net_balance >= 0:
                surplus_solar = net_balance
                solar_to_batt = min(surplus_solar, target_charge)
                grid_to_batt = target_charge - solar_to_batt
                grid_import = grid_to_batt
                grid_export = surplus_solar - solar_to_batt if grid_online else 0.0
            else:
                local_deficit = abs(net_balance)
                # Must import local deficit plus the energy desired for charging
                grid_import = local_deficit + target_charge

        elif action == PlanningAction.DISCHARGE:
            deficit = max(0.0, abs(net_balance))
            dis_kwh = min(deficit, max_dis_kwh)
            battery_flow = -dis_kwh
            remaining_def = deficit - dis_kwh
            if grid_online:
                grid_import = remaining_def
            else:
                unmet_demand = remaining_def

        # Physical battery state update
        stored_kwh = (current.battery_soc / 100.0) * battery_capacity
        new_stored_kwh = max(0.0, min(battery_capacity, stored_kwh + battery_flow))
        new_soc = round((new_stored_kwh / battery_capacity) * 100.0, 2)

        # Step and cumulative costs
        step_cost = self.cost_function.calculate_step_cost(
            grid_import=grid_import,
            grid_export=grid_export,
            unmet_demand=unmet_demand,
            battery_flow=battery_flow,
            hour=step_hour,
        )
        # Tie-breaker: among plans with the same unmet energy, prefer serving
        # load NOW and letting any unavoidable shortfall fall later in the
        # horizon (it may never happen: the grid can return, and the agent
        # replans every hour). Unmet energy at step k costs an extra
        # UNMET_URGENCY_COST * (H - k): 1 paisa per kWh per remaining hour.
        # The extra term is >= 0, so the heuristic stays admissible.
        step_cost = round(step_cost + unmet_demand * self.UNMET_URGENCY_COST * (H - step_index), 4)
        cum_cost = round(current.cumulative_cost + step_cost, 4)

        # Remaining heuristic calculation
        rem_solar = solar_forecast[step_index + 1 : H]
        rem_demand = demand_forecast[step_index + 1 : H]
        h_cost = self.cost_function.calculate_heuristic(
            current_stored_kwh=new_stored_kwh,
            remaining_solar_forecast=rem_solar,
            remaining_demand_forecast=rem_demand,
            remaining_hours=[(next_hour + i) % 24 for i in range(len(rem_demand))],
            remaining_grid_available=(
                grid_forecast[step_index + 1 : H] if grid_forecast is not None else None
            ),
        )

        return PlanningState(
            hour=next_hour,
            step_index=step_index + 1,
            battery_soc=new_soc,
            battery_capacity=battery_capacity,
            action=action,
            battery_flow=round(battery_flow, 4),
            grid_import=round(grid_import, 4),
            grid_export=round(grid_export, 4),
            unmet_demand=round(unmet_demand, 4),
            step_cost=step_cost,
            cumulative_cost=cum_cost,
            heuristic_cost=h_cost,
            total_cost=round(cum_cost + h_cost, 4),
            parent=current,
        )
