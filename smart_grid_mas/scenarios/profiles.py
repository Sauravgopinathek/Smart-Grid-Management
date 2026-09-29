import math
from typing import Dict, Optional


class SolarGenerationProfile:
    """Deterministic 24-hour Diurnal Solar Photovoltaic Generation Profile.
    
    Generates physically realistic solar generation curves:
    - 00:00 to 05:00: Zero generation (nighttime)
    - 06:00 to 18:00: Half-sine solar irradiance curve peaking at 12:00
    - 19:00 to 23:00: Zero generation (nighttime)
    
    Supports household-specific scaling factors (e.g., PV system capacity variations).
    """

    def __init__(self, base_peak_kw: float = 6.0) -> None:
        self.base_peak_kw: float = float(base_peak_kw)

    def get_solar(self, hour: int, household_factor: float = 1.0) -> float:
        """Calculate solar generation in kW for a given hour of the day (0-23).
        
        Args:
            hour: Integer hour of the day [0, 23].
            household_factor: Scaling multiplier representing relative PV capacity.
            
        Returns:
            Solar generation in kW (strictly non-negative).
        """
        h = hour % 24
        if 6 <= h <= 18:
            # Half-sine curve from sunrise (06:00) to sunset (18:00)
            angle = (math.pi * (h - 6)) / 12.0
            solar_kw = self.base_peak_kw * math.sin(angle) * household_factor
            return round(max(0.0, solar_kw), 2)
        return 0.0


class HouseholdDemandProfile:
    """Deterministic 24-hour Residential Demand Profile.
    
    Reflects typical residential consumption patterns:
    - 00:00 to 05:00: Low baseload demand (nighttime)
    - 06:00 to 09:00: Morning rise (wake up, cooking, heating/appliances)
    - 10:00 to 16:00: Moderate daytime consumption
    - 17:00 to 21:00: Evening peak demand (lighting, cooking, entertainment)
    - 22:00 to 23:00: Gradual wind-down
    """

    # Hourly baseline demand profile in kW for an average residential home
    BASE_HOURLY_DEMAND_KW: Dict[int, float] = {
        0: 1.5,
        1: 1.3,
        2: 1.2,
        3: 1.2,
        4: 1.3,
        5: 1.6,
        6: 2.4,  # Morning rise begins
        7: 3.2,
        8: 3.5,
        9: 3.0,
        10: 2.6, # Moderate daytime
        11: 2.5,
        12: 2.8,
        13: 2.6,
        14: 2.5,
        15: 2.7,
        16: 3.0,
        17: 4.5, # Evening peak begins
        18: 5.4, # Peak hour
        19: 5.8, # Peak maximum
        20: 5.0, # Peak winding down
        21: 4.0,
        22: 2.8,
        23: 1.9,
    }

    def __init__(self, base_profile: Optional[Dict[int, float]] = None) -> None:
        self.profile = base_profile if base_profile is not None else self.BASE_HOURLY_DEMAND_KW

    def get_demand(self, hour: int, household_multiplier: float = 1.0) -> float:
        """Calculate household demand in kW for a given hour of the day (0-23).
        
        Args:
            hour: Integer hour of the day [0, 23].
            household_multiplier: Household-specific multiplier (e.g. 1.2 for higher load).
            
        Returns:
            Household demand in kW (strictly non-negative).
        """
        h = hour % 24
        base = self.profile.get(h, 2.5)
        demand = base * household_multiplier
        return round(max(0.0, demand), 2)


class MicrogridDatasetLoader:
    """Loads real-world 24-hour smart meter energy traces from CSV datasets.
    
    Provides empirical hourly solar generation and household load data,
    incorporating ambient diffuse light, natural cloud dynamics, and
    stochastic residential consumption patterns (e.g., NREL/Ausgrid benchmarks).
    """

    def __init__(self, csv_path: str = "data/benchmark_microgrid_dataset.csv") -> None:
        self.csv_path = csv_path
        self.solar_data: Dict[int, Dict[int, float]] = {}  # hour -> {agent_idx: solar_kw}
        self.demand_data: Dict[int, Dict[int, float]] = {} # hour -> {agent_idx: demand_kw}
        self.total_solar: Dict[int, float] = {}
        self.total_demand: Dict[int, float] = {}
        self._load_csv()

    def _load_csv(self) -> None:
        import csv
        import os
        if not os.path.exists(self.csv_path):
            return

        with open(self.csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                h = int(row["hour"])
                self.solar_data[h] = {
                    0: float(row.get("h1_solar_kw", 0.0)),
                    1: float(row.get("h2_solar_kw", 0.0)),
                    2: float(row.get("h3_solar_kw", 0.0)),
                }
                self.demand_data[h] = {
                    0: float(row.get("h1_demand_kw", 1.5)),
                    1: float(row.get("h2_demand_kw", 1.2)),
                    2: float(row.get("h3_demand_kw", 1.0)),
                }
                self.total_solar[h] = float(row.get("solar_global_kw", 0.0))
                self.total_demand[h] = sum(self.demand_data[h].values())

    def get_agent_solar(self, hour: int, agent_index: int) -> float:
        h = hour % 24
        agent_idx = agent_index % 3
        return self.solar_data.get(h, {}).get(agent_idx, 0.0)

    def get_agent_demand(self, hour: int, agent_index: int) -> float:
        h = hour % 24
        agent_idx = agent_index % 3
        return self.demand_data.get(h, {}).get(agent_idx, 1.5)

