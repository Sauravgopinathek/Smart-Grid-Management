from abc import ABC, abstractmethod
from typing import Optional


class BaseShock(ABC):
    """Abstract Base Class for Environmental and Operational Shocks.
    
    A shock represents an external environmental or infrastructure disturbance:
    - start_hour: Discrete hour when the shock initiates [0, 23]
    - duration_hours: Duration of the shock in hours
    - name: Human-readable identifier
    """

    def __init__(self, name: str, start_hour: int, duration_hours: int) -> None:
        self.name: str = name
        self.start_hour: int = int(start_hour)
        self.duration_hours: int = int(duration_hours)

    @property
    def end_hour(self) -> int:
        """Ending hour (exclusive) of the shock event."""
        return self.start_hour + self.duration_hours

    def is_active(self, hour: int) -> bool:
        """Check whether the shock is currently active at simulation hour."""
        h = hour % 24
        return self.start_hour <= h < self.end_hour


class CloudCoverShock(BaseShock):
    """Scenario 1: Solar Generation Drop due to Sudden Cloud Cover.
    
    Temporarily attenuates solar photovoltaic generation by a reduction factor.
    Example: 6.0 kW normal solar drops to 2.4 kW during event (reduction_factor = 0.4).
    
    IMPORTANT:
    The agents do NOT know in advance that cloud cover is approaching.
    They perceive only the resulting drop in local generation.
    """

    def __init__(
        self,
        start_hour: int = 12,
        duration_hours: int = 2,
        reduction_factor: float = 0.4,
    ) -> None:
        super().__init__(
            name="CloudCoverShock",
            start_hour=start_hour,
            duration_hours=duration_hours,
        )
        self.reduction_factor: float = float(reduction_factor)

    def modify_solar(self, hour: int, normal_solar_kw: float) -> float:
        """Apply cloud cover attenuation if currently active."""
        if self.is_active(hour):
            return round(max(0.0, normal_solar_kw * self.reduction_factor), 2)
        return normal_solar_kw


class PeakDemandShock(BaseShock):
    """Scenario 2: Evening Peak Residential Demand Surge.
    
    Amplifies household consumption during selected high-demand evening hours.
    Example: 4.0 kW baseline load surges to 6.0 kW (demand_multiplier = 1.5).
    """

    def __init__(
        self,
        start_hour: int = 17,
        duration_hours: int = 3,
        demand_multiplier: float = 1.5,
    ) -> None:
        super().__init__(
            name="PeakDemandShock",
            start_hour=start_hour,
            duration_hours=duration_hours,
        )
        self.demand_multiplier: float = float(demand_multiplier)

    def modify_demand(self, hour: int, normal_demand_kw: float) -> float:
        """Apply peak surge multiplier if currently active."""
        if self.is_active(hour):
            return round(max(0.0, normal_demand_kw * self.demand_multiplier), 2)
        return normal_demand_kw


class GridOutageShock(BaseShock):
    """Scenario 3: Utility Grid Blackout / Microgrid Islanding.
    
    Simulates total disconnection from the external utility distribution grid.
    During an outage:
    - Utility grid cannot supply deficit energy (import = 0).
    - Utility grid cannot absorb surplus energy (export = 0).
    - The microgrid islands: only local solar, batteries, and peer trading can fulfill load.
    - Residual unfulfilled deficits become unmet_demand_kwh.
    """

    def __init__(
        self,
        start_hour: int = 18,
        duration_hours: int = 2,
    ) -> None:
        super().__init__(
            name="GridOutageShock",
            start_hour=start_hour,
            duration_hours=duration_hours,
        )

    def is_grid_available(self, hour: int) -> bool:
        """Return False if grid outage is active, True otherwise."""
        return not self.is_active(hour)
