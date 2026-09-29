from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PlanningAction(Enum):
    """Discrete candidate battery actuation choices for local A* planning."""
    HOLD = "HOLD"                      # No battery action (0 kW flow)
    CHARGE_SOLAR = "CHARGE_SOLAR"      # Absorb local solar surplus into battery
    CHARGE_GRID = "CHARGE_GRID"        # Charge battery from grid (arbitrage / reserve)
    DISCHARGE = "DISCHARGE"            # Discharge battery to cover local deficit
    DISCHARGE_MAX = "DISCHARGE_MAX"    # Maximum battery discharge


@dataclass
class PlanningState:
    """State node in the decentralized A* local planning state-space.
    
    Represents the microgrid state at a specific planning timestep:
    - hour: Current hour in 24-hour cycle [0, 23]
    - step_index: Relative step within the planning horizon [0, H]
    - battery_soc: State of charge in percentage [0.0, 100.0]
    - battery_capacity: Total battery capacity in kWh
    
    Tracking and path reconstruction:
    - action: The action that led to this state
    - battery_flow: Energy flow in kWh (+ for charge, - for discharge)
    - grid_import: Energy imported from grid in kWh
    - grid_export: Energy exported to grid in kWh
    - unmet_demand: Demand not covered by solar, battery, or grid in kWh
    - step_cost: Immediate cost incurred in this step
    - cumulative_cost: Accumulated path cost g(n) from start state
    - heuristic_cost: Admissible estimated cost-to-go h(n)
    - total_cost: f(n) = g(n) + h(n)
    - parent: Backpointer to previous PlanningState node
    """
    hour: int
    step_index: int
    battery_soc: float
    battery_capacity: float = 10.0
    action: Optional[PlanningAction] = None
    battery_flow: float = 0.0
    grid_import: float = 0.0
    grid_export: float = 0.0
    unmet_demand: float = 0.0
    step_cost: float = 0.0
    cumulative_cost: float = 0.0
    heuristic_cost: float = 0.0
    total_cost: float = 0.0
    parent: Optional["PlanningState"] = field(default=None, repr=False)

    @property
    def stored_energy_kwh(self) -> float:
        """Physical energy stored in battery in kWh."""
        return (self.battery_soc / 100.0) * self.battery_capacity

    @property
    def available_capacity_kwh(self) -> float:
        """Remaining capacity available for charging in kWh."""
        return max(0.0, self.battery_capacity - self.stored_energy_kwh)

    def state_key(self, soc_resolution: float = 0.5) -> tuple:
        """Quantized state representation for A* closed-set memoization.
        
        Rounds SOC to avoid redundant floating-point micro-state exploration.
        """
        quantized_soc = round(self.battery_soc / soc_resolution) * soc_resolution
        return (self.hour % 24, self.step_index, round(quantized_soc, 2))

    def __lt__(self, other: "PlanningState") -> bool:
        """Priority queue ordering by total estimated cost f(n) = g(n) + h(n).
        
        Ties are broken deterministically by cumulative cost g(n) and then step_index.
        """
        if abs(self.total_cost - other.total_cost) > 1e-6:
            return self.total_cost < other.total_cost
        if abs(self.cumulative_cost - other.cumulative_cost) > 1e-6:
            return self.cumulative_cost < other.cumulative_cost
        return self.step_index > other.step_index
