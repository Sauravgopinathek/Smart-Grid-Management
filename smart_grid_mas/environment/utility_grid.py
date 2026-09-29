class UtilityGrid:
    """External Utility Grid component.
    
    Acts strictly as an external energy source and sink for the neighborhood microgrid.
    IMPORTANT (Review 1 Architectural Requirement):
    The UtilityGrid is NOT a central controller or decision-maker. It does not
    assign actions to agents. Individual HouseholdAgents make their own decisions
    and interact with the grid only when their local generation and storage cannot
    fulfill demand, or when local surplus exceeds battery storage capacity.
    
    Module 3 Islanding Support:
    During a GridOutageShock, is_available can be set to False. While disconnected:
    - supply() refuses import requests (returns 0.0 kW).
    - absorb() refuses export requests (returns 0.0 kW).
    - The microgrid operates in islanded mode relying on solar, batteries, and P2P trades.
    """

    def __init__(self, name: str = "Main Utility Grid", is_available: bool = True) -> None:
        self.name: str = name
        self.is_available: bool = is_available

        # Cumulative tracking (kWh or kW-step)
        self.total_imported: float = 0.0
        self.total_exported: float = 0.0
        
        # Step-level tracking
        self.current_step_import: float = 0.0
        self.current_step_export: float = 0.0

    @property
    def grid_available(self) -> bool:
        """Alias for grid availability status."""
        return self.is_available

    @grid_available.setter
    def grid_available(self, value: bool) -> None:
        self.is_available = bool(value)

    def set_availability(self, available: bool) -> None:
        """Set grid connectivity status."""
        self.is_available = bool(available)

    def reset_step(self) -> None:
        """Reset step-level exchange counters at the beginning of a simulation step."""
        self.current_step_import = 0.0
        self.current_step_export = 0.0

    def supply(self, amount_kw: float) -> float:
        """Supply energy to a household agent experiencing an unfulfilled deficit.
        
        Returns:
            The amount of power supplied in kW, or 0.0 if the grid is unavailable (blackout).
        """
        if not self.is_available or amount_kw <= 0:
            return 0.0
        self.current_step_import += amount_kw
        self.total_imported += amount_kw
        return amount_kw

    def absorb(self, amount_kw: float) -> float:
        """Absorb surplus energy exported by a household agent.
        
        Returns:
            The amount of power absorbed in kW, or 0.0 if the grid is unavailable.
        """
        if not self.is_available or amount_kw <= 0:
            return 0.0
        self.current_step_export += amount_kw
        self.total_exported += amount_kw
        return amount_kw

    def __repr__(self) -> str:
        status_str = "ONLINE" if self.is_available else "OFFLINE (BLACKOUT)"
        return (
            f"UtilityGrid(status={status_str}, step_import={self.current_step_import:.2f}kW, "
            f"step_export={self.current_step_export:.2f}kW, "
            f"total_import={self.total_imported:.2f}kWh, "
            f"total_export={self.total_exported:.2f}kWh)"
        )
