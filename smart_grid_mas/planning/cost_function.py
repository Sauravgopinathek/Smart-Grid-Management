from typing import List, Optional


class TOUTariff:
    """Time-of-Use (TOU) Electricity Pricing Schedule.
    
    Tariff Bands:
    - Off-Peak (00:00 to 06:00): Rs. 3.00 / kWh
    - Normal / Mid-Peak (06:00 to 17:00 & 21:00 to 24:00): Rs. 5.00 / kWh
    - Peak (17:00 to 21:00): Rs. 8.00 / kWh
    - Export / Feed-in Tariff: Rs. 2.00 / kWh
    """
    OFF_PEAK_RATE: float = 3.0
    NORMAL_RATE: float = 5.0
    PEAK_RATE: float = 8.0
    EXPORT_RATE: float = 2.0

    @classmethod
    def get_import_rate(cls, hour: int) -> float:
        """Return the grid import electricity tariff in Rs./kWh for a given hour."""
        h = hour % 24
        if 0 <= h < 6:
            return cls.OFF_PEAK_RATE
        elif 17 <= h < 21:
            return cls.PEAK_RATE
        else:
            return cls.NORMAL_RATE

    @classmethod
    def get_export_rate(cls, hour: int) -> float:
        """Return the grid export feed-in tariff in Rs./kWh for a given hour."""
        return cls.EXPORT_RATE

    @classmethod
    def get_min_import_rate(cls) -> float:
        """Return the minimum possible import tariff across all 24 hours."""
        return cls.OFF_PEAK_RATE


class CostFunction:
    """Calculates step transition costs and admissible heuristic estimates for A* search.
    
    Formula:
      Step Cost = (grid_import * import_tariff)
                - (grid_export * export_tariff)
                + (unmet_demand * unmet_penalty)
                + (|battery_flow| * degradation_penalty)
                
    Heuristic:
      h(n) = max(0, (Remaining Deficit - Stored Energy) * Min Tariff)
    """

    def __init__(
        self,
        unmet_demand_penalty: float = 1000.0,
        battery_degradation_penalty: float = 0.05,
        tariff: Optional[TOUTariff] = None,
    ) -> None:
        self.unmet_demand_penalty: float = float(unmet_demand_penalty)
        self.battery_degradation_penalty: float = float(battery_degradation_penalty)
        self.tariff: TOUTariff = tariff if tariff is not None else TOUTariff()

    def calculate_step_cost(
        self,
        grid_import: float,
        grid_export: float,
        unmet_demand: float,
        battery_flow: float,
        hour: int,
    ) -> float:
        """Calculate immediate cost for a single timestep transition."""
        import_rate = self.tariff.get_import_rate(hour)
        export_rate = self.tariff.get_export_rate(hour)

        import_cost = grid_import * import_rate
        export_revenue = grid_export * export_rate
        unmet_penalty = unmet_demand * self.unmet_demand_penalty
        degradation_cost = abs(battery_flow) * self.battery_degradation_penalty

        return round(import_cost - export_revenue + unmet_penalty + degradation_cost, 4)

    def calculate_heuristic(
        self,
        current_stored_kwh: float,
        remaining_solar_forecast: List[float],
        remaining_demand_forecast: List[float],
        remaining_hours: Optional[List[int]] = None,
        remaining_grid_available: Optional[List[bool]] = None,
    ) -> float:
        """Admissible heuristic h(n): a lower bound on the cost-to-go.

        Relaxed problem (every real plan costs at least this much):
        - Battery capacity, charge/discharge rate limits and the ORDER of hours
          are ignored: stored energy E and future solar surplus S can be moved to
          any future deficit hour.
        - A deficit hour t that is still uncovered costs c_t per kWh, where
              c_t = min( tariff(t) if the grid is online at t, else the unmet penalty,
                         cheapest tariff of any online hour in the horizon )
          (the second term allows for buying energy earlier and storing it).
        - Surplus not used to cover deficit earns at most r_max from export.
        - Battery wear cost (>= 0) is dropped.

        The relaxed problem is solved exactly and greedily: use free stored
        energy on the most expensive deficit kWh first, then use surplus on the
        remaining deficit kWh while c_t > r_max (storing saves c_t but forgoes
        r_max of export revenue). Everything left is paid at c_t / earned at r_max.

        Because this is the optimum of a relaxation, h(n) <= h*(n) (admissible),
        so A* returns the optimal plan. h(n) may be negative (export revenue).

        If hours / grid availability are not supplied, every hour is priced at
        the cheapest tariff, which is weaker but still admissible.
        """
        n = len(remaining_demand_forecast)
        if n == 0:
            return 0.0

        p_min = self.tariff.get_min_import_rate()
        r_max = max(self.tariff.get_export_rate(h) for h in range(24))
        online = list(remaining_grid_available) if remaining_grid_available is not None else [True] * n

        if remaining_hours is not None:
            online_rates = [self.tariff.get_import_rate(h) for h, on in zip(remaining_hours, online) if on]
            p_store = min(online_rates) if online_rates else float("inf")
        else:
            p_store = p_min

        surplus = 0.0
        deficits: List[List[float]] = []  # [unit_cost, kWh]
        for i, (d, s) in enumerate(zip(remaining_demand_forecast, remaining_solar_forecast)):
            net = s - d
            if net > 0:
                surplus += net
            elif net < 0:
                if remaining_hours is None:
                    direct = p_min if online[i] else self.unmet_demand_penalty
                else:
                    direct = self.tariff.get_import_rate(remaining_hours[i]) if online[i] else self.unmet_demand_penalty
                deficits.append([min(direct, p_store), -net])

        # Most expensive deficit first
        deficits.sort(key=lambda x: -x[0])

        stored = max(0.0, current_stored_kwh)
        cost = 0.0
        for item in deficits:
            use = min(stored, item[1])
            stored -= use
            item[1] -= use
        for item in deficits:
            if item[1] <= 0 or item[0] <= r_max:
                continue
            use = min(surplus, item[1])
            surplus -= use
            item[1] -= use
        for unit_cost, kwh in deficits:
            cost += unit_cost * kwh
        cost -= r_max * surplus

        return round(cost, 4)
