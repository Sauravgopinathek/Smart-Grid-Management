# Smart Grid Multi-Agent System (MAS) — Module 1: Foundation

Decentralized Multi-Agent Smart Grid Architecture for Autonomous Microgrid Energy Management.  
*Aligned strictly with Review 1 (Problem Definition & Fundamental Understanding).*

---

## 1. Problem Statement

Modern power distribution is shifting from centralized, fossil-fuel-dominated generation to decentralized microgrids incorporating localized Distributed Energy Resources (DERs) such as rooftop solar photovoltaics (PV) and battery energy storage systems (BESS). In such settings:
- Households experience fluctuating, intermittent renewable generation and stochastic consumption patterns.
- Individual households alternate between energy **Surplus**, **Deficit**, and **Balanced** states.
- Traditional centralized grid control suffers from single-point-of-failure vulnerabilities, communication bottlenecks, privacy intrusion into residential usage profiles, and poor scalability.

This project implements a **Decentralized Multi-Agent Smart Grid** where each household is modeled as an autonomous agent that manages its local generation, storage, and demand, while communicating with neighbor agents to coordinate energy sharing without central control.

---

## 2. Why This is a Multi-Agent System (MAS)

Energy management in a distributed residential microgrid is inherently a multi-agent problem:
- **Autonomy**: Each household owns physical assets (solar PV, battery) and has independent economic and operational goals (minimizing costs, maximizing self-sufficiency).
- **Decentralization**: No central coordinator dictates when households charge, discharge, or consume.
- **Partial Observability**: Households know their own generation, demand, and storage, but do not possess omniscient knowledge of neighbors' private states.
- **Cooperation & Coordination**: Individual actions collectively impact neighborhood load balance and external grid dependency. Coordinated peer-to-peer sharing yields mutual benefits.

---

## 3. Why Mesa Was Selected

**Mesa** (Mesa 3.5.1 on Python 3.13) was selected as specified in the Review 1 presentation because:
1. **Agent-Based Modeling (ABM) Standard in Python**: Mesa provides built-in abstractions for autonomous agents (`Agent`), environment coordination (`Model`), discrete time simulation, and scheduler execution.
2. **Modular Extensibility**: Its separation of agent behavior, model mechanics, and telemetry provides a clean substrate for layering future A* search planning and peer-to-peer negotiation protocols.
3. **Reproducibility**: Mesa supports explicit random number generator seeding (`rng`) enabling deterministic validation of stochastic simulation scenarios.

---

## 4. HouseholdAgent Architecture

Each household is an instance of [`HouseholdAgent`](file:///d:/Smart_Grid_Management/smart_grid_mas/agents/household_agent.py#L8-L200) inheriting from `mesa.Agent`:

### Sensors / Perception:
- **Solar Generation ($P_{\text{solar}}$)**: Current photovoltaic generation in **kW**.
- **Household Demand ($P_{\text{demand}}$)**: Real-time electrical load in **kW**.
- **Battery Capacity ($E_{\text{cap}}$)**: Storage capacity in **kWh**.
- **Battery State of Charge ($\text{SOC}$)**: Usable charge level in percent (**%**, bounded in $[0.0, 100.0]$).
- **Neighbor Messages**: Inbound peer communications detailing neighbor surplus/deficit declarations.

### Actuators / Actions:
- **`CHARGE`**: Direct surplus solar energy into the local battery storage.
- **`DISCHARGE`**: Draw energy from the battery to satisfy unmet household load.
- **`CONSUME`**: Direct self-consumption where solar generation precisely matches load.
- **`SELL`**: Export excess energy (to the external utility grid or peer households in later modules).
- **`BUY`**: Import deficit energy (from the utility grid or peer households in later modules).

### Isolated Local Decision Layer:
The decision logic is encapsulated in `evaluate_local_action()` and classifies state based on net balance:
$$\text{Energy Balance} = P_{\text{solar}} - P_{\text{demand}}$$

- $\text{Balance} > 0 \implies \mathbf{SURPLUS}$
- $\text{Balance} < 0 \implies \mathbf{DEFICIT}$
- $\text{Balance} = 0 \implies \mathbf{BALANCED}$

The baseline deterministic decision rules are:
- **SURPLUS**: If $\text{SOC} < 100\%$, choose `CHARGE`; if $\text{SOC} = 100\%$, choose `SELL`.
- **DEFICIT**: If $\text{SOC} > 0\%$, choose `DISCHARGE`; if $\text{SOC} = 0\%$, choose `BUY`.
- **BALANCED**: Choose `CONSUME`.

> **Note**: This function is explicitly isolated so that subsequent modules can substitute it with A* local sequence planning, battery degradation cost functions, and negotiation-informed policies.

---

## 5. SmartGridModel Architecture

[`SmartGridModel`](file:///d:/Smart_Grid_Management/smart_grid_mas/environment/smart_grid_model.py#L42-L195) inherits from `mesa.Model` and coordinates the environment:
- **Instantiates Household Agents**: Configurable to run with 3, 5, 10, or $N$ households without code alterations.
- **Maintains External Utility Grid**: Interfaces with the utility grid for physical energy balance.
- **Wires Neighborhood Peer Channels**: Registers peer households in local neighbor sets for communication.
- **Executes Discrete Timesteps**: Governs the multi-phase discrete simulation loop.
- **Collects Observability Telemetry**: Computes aggregate metrics strictly for reporting, without violating agent autonomy.

---

## 6. UtilityGrid Role

[`UtilityGrid`](file:///d:/Smart_Grid_Management/smart_grid_mas/environment/utility_grid.py#L1-L55) represents the external medium-voltage distribution grid.

**Strict Architectural Constraint**:
The `UtilityGrid` is **NOT** a central controller or decision-maker. It has **no authority** over household choices. It acts solely as a physical energy source (supplying unfulfilled deficits) and sink (absorbing unabsorbed surplus), recording step and cumulative imports and exports ($E_{\text{import}}, E_{\text{export}}$).

---

## 7. Local State

Each household maintains strictly isolated local variables:
- `agent_id`
- `solar_generation`
- `household_demand`
- `battery_capacity`
- `battery_soc`
- `energy_balance`
- `state`
- `current_action`
- `received_messages`
- `neighbors`

No agent directly mutates or reads another agent's private state variables.

---

## 8. Partial Observability

In accordance with the Review 1 Environment Classification:
- Agents **do not** possess omniscient awareness of the neighborhood or other households' battery levels, exact load curves, or internal thresholds.
- Agents interact with the environment through local sensor measurements and explicit structured message passing.
- Global metrics collected by `SmartGridModel` are strictly for researcher telemetry and external evaluation; they are completely inaccessible to agent decision functions.

---

## 9. Discrete Timestep Execution

The simulation advances across discrete, sequential timesteps ($t = 1, 2, 3, \dots$):
1. **Clear Inboxes**: Old messages from previous steps are flushed.
2. **Perception & Status Sharing (Phase 1)**: Each household reads its sensors ($P_{\text{solar}}, P_{\text{demand}}, \text{SOC}$) and broadcasts its energy condition (`SURPLUS` or `DEFICIT`) to its registered neighbors.
3. **Autonomous Decision & Actuation (Phase 2)**: Each household independently runs `evaluate_local_action()` and executes `execute_action()`, updating its battery SOC and interacting with the grid for residual imbalances.
4. **Environment Telemetry & State Persistence**: Physical state (e.g., updated battery SOC) persists to step $t+1$.

---

## 10. Communication Foundation

Inter-agent communication is structured using the [`Message`](file:///d:/Smart_Grid_Management/smart_grid_mas/communication/message.py#L16-L45) dataclass:
- `sender_id`: Originating agent ID
- `receiver_id`: Target agent ID or `"BROADCAST"`
- `message_type`: `SURPLUS`, `DEFICIT`, `REQUEST`, `OFFER`, `ACCEPT`, `REJECT`
- `energy_amount`: Magnitude of energy imbalance (kW)
- `state`: Sender's `EnergyState`
- `timestamp`: Simulation step

In Module 1, households use this foundation to broadcast their `SURPLUS` and `DEFICIT` availability to neighbors. In subsequent modules, these messages trigger direct P2P auctions and negotiation counter-proposals.

---

## 11. Installation

### Requirements:
- Python 3.10+ (Verified on **Python 3.13.5**)
- Dependencies listed in `requirements.txt`:
  - `mesa>=3.5.0` (Verified on **Mesa 3.5.1**)
  - `networkx>=3.0`
  - `pytest>=8.0.0`

### Setup:
```bash
pip install -r requirements.txt
```

---

## 12. Running the Simulation

Run the simulation via terminal:
```bash
python run_simulation.py
```

### Optional Command-Line Arguments:
- Run 5 timesteps:
  ```bash
  python run_simulation.py --steps 5
  ```
- Test scalability with 10 autonomous households:
  ```bash
  python run_simulation.py --households 10 --steps 2
  ```

---

## 13. Running Tests

Run the automated test suite using `unittest` or `pytest`:

```bash
# Run all tests using unittest
python -m unittest discover -s smart_grid_mas/tests -p "test_*.py"

# Or run all 112 tests using pytest
pytest smart_grid_mas/tests/ -v
```

See Section 17 for what each suite covers.

---

## 14. Module 2 — Decentralized P2P Negotiation (Contract-Net with Renegotiation)

Implemented in [`negotiation_protocol.py`](smart_grid_mas/negotiation/negotiation_protocol.py) and the negotiation phases of [`HouseholdAgent`](smart_grid_mas/agents/household_agent.py). Every decision is taken by the agents themselves; the model only delivers messages and keeps the ledger.

### 1. One negotiation round
1. **Announce** — every household broadcasts `SURPLUS` (with the amount it can sell and its asking price) or `DEFICIT` (the amount it still needs).
2. **Call for proposals** — each buyer sends a `REQUEST` (amount + price ceiling) to the surplus neighbours whose advertised price it can afford.
3. **Offer with reservation** — each seller splits its sellable energy across all the requests it received *at the same time* (`NegotiationProtocol.allocate_surplus`):
   - if total demand fits, every request is reserved in full;
   - otherwise each buyer is reserved a share proportional to what it asked for.

   The offers therefore never add up to more than the seller has, and never exceed the inverter limit for the hour (`max_charge_rate_kw × Δt`, counted across *all* buyers).
4. **Accept / Reject** — each buyer ranks offers by price (then quantity, then seller ID), `ACCEPT`s the cheapest until its need is covered and `REJECT`s the rest.
5. **Settle** — each seller confirms its accepted offers and records the trades. Because offers were reserved, **every ACCEPT is delivered in full** (verified by `test_every_accept_is_delivered_in_full`).

### 2. Renegotiation rounds (dynamic renegotiation & deadlock handling)
Energy can remain on the table after a round — a buyer may decline a seller's reserved share because it found a cheaper offer, while another buyer that can only reach that seller is still short. The step therefore repeats the round:

- agents re-announce their **updated** amounts (only if they still have at least 1 Wh to trade), and the round runs again;
- **termination is guaranteed**: negotiation stops as soon as (a) a round settles no trade (no progress), (b) no buyer or no seller is left, or (c) `max_negotiation_rounds` is reached (default 3, `--rounds` on `run_scenario.py`).

Example (`test_renegotiation_recovers_declined_energy`): buyer B1 can only reach seller S1. In round 1, S1 reserves 1 kWh for B1 and 1 kWh for B2, but B2 buys from the cheaper S2 instead. With a single round, B1 imports 1 kWh from the grid; with renegotiation, B1 buys S1's released 1 kWh in round 2.

With a fully connected neighbourhood and proportional reservation, most hours already clear in round 1; renegotiation matters when the neighbour network is partial or buyers decline shares.

---

## 15. Module 3 — Dynamic Environmental Shocks & Scenario Testing

### 1. Why Module 3 is Required
Static single-step models cannot evaluate whether autonomous household agents remain robust under unpredictable real-world disturbances. Module 3 subjects the decentralized multi-agent system to dynamic diurnal solar variations, residential consumption cycles, and environmental shocks to evaluate resilience, microgrid islanding, and P2P coordination under stress.

### 2. 24-Hour Environment
Simulation progresses through discrete hourly timesteps ($t = 0 \dots 23$ hours, $\Delta t = 1.0\text{ h}$). State (battery State of Charge, energy balances, cumulative trades, and grid exchange) persists sequentially from hour to hour.

### 3. Solar Generation Profile
Implemented in [`SolarGenerationProfile`](file:///d:/Smart_Grid_Management/smart_grid_mas/scenarios/profiles.py):
- Night (00:00–05:00 and 19:00–23:00): Zero generation.
- Daylight (06:00–18:00): Deterministic half-sine irradiance curve peaking at 12:00:
  $$P_{\text{solar}}(h) = \max\left(0.0, P_{\text{peak}} \times \sin\left(\frac{\pi (h - 6)}{12}\right) \times f_{\text{household}}\right)$$
- Guaranteed strictly non-negative.

### 4. Residential Demand Profile
Implemented in [`HouseholdDemandProfile`](file:///d:/Smart_Grid_Management/smart_grid_mas/scenarios/profiles.py):
- Night (00:00–05:00): Low baseload consumption (~1.2–1.6 kW).
- Morning (06:00–09:00): Morning rise (~2.4–3.5 kW).
- Daytime (10:00–16:00): Moderate daytime activities (~2.5–3.0 kW).
- Evening Peak (17:00–21:00): Significant evening surge (~4.5–5.8 kW).
- Late Night (22:00–23:00): Gradual decline (~1.9–2.8 kW).
- Scaled by heterogeneous household multipliers ($m_{\text{household}}$).

### 5. Environmental Shock Framework
Implemented in [`smart_grid_mas/scenarios/shocks.py`](file:///d:/Smart_Grid_Management/smart_grid_mas/scenarios/shocks.py):
- **Scenario 1: CloudCoverShock**:
  - Time window: 12:00 to 14:00 (2 hours).
  - Magnitude: Solar generation attenuated by 60% ($\text{reduction\_factor} = 0.4$).
  - Partial Observability: Agents do not anticipate cloud cover; they observe only the sudden drop in solar generation.
- **Scenario 2: PeakDemandShock**:
  - Time window: 17:00 to 20:00 (3 hours).
  - Magnitude: Household demand multiplied by 1.5 (+50% load surge).
  - Agents respond autonomously via battery discharge and P2P request spikes.
- **Scenario 3: GridOutageShock**:
  - Time window: 18:00 to 20:00 (2 hours).
  - Utility grid disconnected (`grid_available = False`).
  - Import and export refused by the external grid ($P_{\text{import}} = 0$, $P_{\text{export}} = 0$).

### 6. Decentralized Microgrid Islanding
During a utility grid outage:
- The microgrid islands autonomously without human or central intervention.
- Households rely exclusively on local solar, battery reserves, and P2P energy trades.
- If total localized energy is insufficient, the unmet deficit is recorded in `unmet_demand_kwh` without masking the failure.

### 7. Combined Stress Scenario
Applies all three shocks concurrently across a single 24-hour cycle:
- 12:00–14:00: Cloud Cover Drop
- 17:00–20:00: Evening Peak Demand Surge
- 18:00–20:00: Utility Grid Blackout

### 8. Scenario Execution CLI
Run individual scenarios or full comparative suites:
```bash
# Run specific 24-hour scenario with detailed hourly log
python run_scenario.py --scenario combined
python run_scenario.py --scenario cloud_cover
python run_scenario.py --scenario peak_demand
python run_scenario.py --scenario grid_outage
python run_scenario.py --scenario baseline

# Run comprehensive comparative resilience benchmark across all 5 scenarios
python run_scenario.py --compare-all
```

### 9. Resilience Metrics Summary (24-Hour Benchmark)

| Metric | Baseline | Cloud Cover | Peak Demand | Grid Outage | Combined Stress |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Total Solar (kWh)** | 109.4 | **92.4** | 109.4 | 109.4 | **92.4** |
| **Total Demand (kWh)** | 208.3 | 208.3 | **232.2** | 208.3 | **232.2** |
| **P2P Energy Traded (kWh)** | 12.46 | 9.88 | 12.46 | 12.46 | 9.88 |
| **Utility Grid Import (kWh)** | 102.63 | 108.86 | 126.57 | **83.49** | **90.65** |
| **Utility Grid Export (kWh)** | 16.72 | 5.96 | 16.72 | 16.72 | 5.96 |
| **Unmet Demand (kWh)** | 0.00 | 0.00 | 0.00 | **19.14** | **42.15** |
| **Min Battery SOC (%)** | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| **Avg Battery SOC (%)** | 24.0% | 21.2% | 23.0% | 24.0% | 20.3% |
| **Outage Duration (hours)** | 0h | 0h | 0h | **2h** | **2h** |
| **Unmet Demand Hours** | 0h | 0h | 0h | **2h** | **2h** |

---

---

## 16. Module 4: A* Local Planning & Predictive Energy Optimization

### 1. Problem Formulation & Motivation
Reactive battery control (Modules 1–3) makes greedy, instantaneous decisions without anticipating future tariffs, solar cycles, or demand spikes. Under **Time-of-Use (TOU)** pricing schedules where peak tariffs reach ₹8/kWh while off-peak tariffs are only ₹3/kWh, greedy discharging during mid-day or morning hours depletes the battery prematurely, exposing households to severe grid import expenses during evening peak hours.

Module 4 implements **Decentralized A* Local Trajectory Planning** within each autonomous [`HouseholdAgent`](file:///d:/Smart_Grid_Management/smart_grid_mas/agents/household_agent.py). Each agent computes an optimal charge/discharge trajectory over a lookahead horizon $H \in \{3, 6, 12, 24\}$ hours to minimize cumulative monetary expense while strictly respecting battery physical bounds and preserving Contract-Net P2P negotiation.

### 2. Time-of-Use (TOU) Electricity Pricing Schedule
Implemented in [`TOUTariff`](file:///d:/Smart_Grid_Management/smart_grid_mas/planning/cost_function.py):

| Pricing Band | Hours of Day | Import Tariff | Export Feed-in Tariff | Economic Intent |
| :--- | :--- | :--- | :--- | :--- |
| **Off-Peak** | 00:00 to 06:00 | **Rs. 3.00 / kWh** | Rs. 2.00 / kWh | Pre-charge battery at low tariff |
| **Normal / Mid-Peak** | 06:00 to 17:00 & 21:00 to 24:00 | **Rs. 5.00 / kWh** | Rs. 2.00 / kWh | Balance local solar and load |
| **Peak (Evening)** | 17:00 to 21:00 | **Rs. 8.00 / kWh** | Rs. 2.00 / kWh | Maximize battery discharge (Peak Shaving) |

### 3. Mathematical State-Space & Cost Function
Implemented in [`CostFunction`](file:///d:/Smart_Grid_Management/smart_grid_mas/planning/cost_function.py):
The A* search minimizes total estimated trajectory cost:
$$f(n) = g(n) + h(n)$$

#### A. Cumulative Path Cost $g(n)$
Accumulates the step costs from step 0 to step $k$:
$$g(n) = \sum_{t=0}^{k-1} C(t)$$
Where step transition cost $C(t)$ is defined as:
$$C(t) = \Big(E_{\text{import}}(t) \times \text{Tariff}(h)\Big) - \Big(E_{\text{export}}(t) \times \text{ExportTariff}\Big) + \Big(E_{\text{unmet}}(t) \times P_{\text{unmet}}\Big) + \Big(|E_{\text{battery\_flow}}(t)| \times P_{\text{cycling}}\Big)$$
- $P_{\text{unmet}} = 1000.0\text{ Rs/kWh}$: Extreme penalty guaranteeing priority of meeting local demand.
- $P_{\text{cycling}} = 0.05\text{ Rs/kWh}$: Battery cell wear degradation penalty preventing idle micro-cycling.

#### B. Admissible Heuristic $h(n)$ (relaxation-based)
$h(n)$ is the **exact optimum of a relaxed problem** in which battery capacity, charge/discharge rate limits and the order of hours are ignored. Over the remaining steps of the horizon:

- $E$ = energy stored now, $S$ = total future solar surplus, and each future deficit hour $t$ has a unit cost
  $$c_t = \min\big(\text{Tariff}(t)\ \text{(or the unmet penalty if the grid is offline at } t),\ \min_{\text{online hours}} \text{Tariff}\big)$$
  (the second term allows for buying energy earlier and storing it);
- stored energy is used on the most expensive deficit kWh first, then surplus is used on the next most expensive kWh while $c_t > r_{\text{export}}$ (storing surplus saves $c_t$ but gives up the export revenue $r_{\text{export}} = 2$ Rs/kWh);
- remaining deficit is paid at $c_t$, and remaining surplus earns $r_{\text{export}}$ (so $h$ may be negative).

- **Admissibility**: every real plan is also a feasible plan of the relaxed problem (the relaxation only removes constraints and drops the non-negative battery-wear cost), so $h(n) \le h^*(n)$ and A* returns the optimal plan.
- **Verified**: `test_astar_matches_exhaustive_search` compares A* with a brute-force search over *every* action sequence (`AStarPlanner.exhaustive_optimal_cost`) on 200 random instances; `test_heuristic_never_exceeds_optimum_random` checks $h \le h^*$ directly.
- **Consistency is not claimed.** The planner re-opens a state if it is reached later with a lower $g$, so optimality only needs admissibility.
- **Why this version**: the earlier heuristic $(D - E)\times 3$ ignored future surplus and export revenue and was **not admissible** (surplus 5 kWh then deficit 5 kWh with an empty battery: $h = 15$ Rs but the optimum is 0.50 Rs), and A* returned a costlier plan than uniform-cost search in about 10% of random cases. A simpler admissible bound (cheapest tariff everywhere) was also tried: it was correct but expanded *more* nodes than uniform-cost search, so the tariff-aware bound above is used (`test_heuristic_prunes_versus_uniform_cost_search`).

#### C. Tie-breaking
When two plans have the same cost, the planner prefers serving load **now** and leaving any unavoidable shortfall to later hours (an extra 0.01 Rs per kWh of unmet demand per remaining horizon hour). The agent replans every hour, so a later shortfall may never happen, for example if the grid returns early.

### 4. Search Algorithm & Pruning
Implemented in [`AStarPlanner`](file:///d:/Smart_Grid_Management/smart_grid_mas/planning/astar_planner.py):
- **Candidate Actions**:
  - `HOLD`: Zero battery flow (0 kW). Imbalance exchanged with grid/P2P.
  - `CHARGE_SOLAR`: Store surplus solar generation into battery.
  - `CHARGE_GRID`: Pre-charge battery from grid during off-peak hours (TOU arbitrage).
  - `DISCHARGE`: Discharge battery to cover local deficit, avoiding high-tariff grid purchase.
- **Closed-Set State Pruning**:
  State space is memoized via quantized keys `(hour % 24, step_index, round(soc / resolution) * resolution)`.
  Measured cost (3 households, 24 hours = 72 plans): about 830 nodes / 0.03 s per day at $H=6$, 7,300 nodes / 0.3 s at $H=12$ (≈ 4 ms per plan), and 72,000 nodes / 4 s at $H=24$. See `python run_planning.py --horizon-study`.

### 5. Receding-Horizon Multi-Agent Execution Loop
1. At simulation step $t$, each household agent observes current battery State of Charge ($0\% \le \text{SOC} \le 100\%$) and reads lookahead forecasts $S(t \dots t+H-1)$, $D(t \dots t+H-1)$. The current hour always uses the **observed** sensor values, not the forecast, so an unforecast shock (e.g. sudden cloud cover) is reflected in the action taken.
2. The agent independently solves local A* search over horizon $H$.
3. The agent commits the **first action** only, setting `planned_battery_flow`.
4. Residual balances feed directly into **Tier 3 P2P Contract-Net Negotiation** (peers trade energy autonomously).
5. Any remaining net surplus/deficit falls back to **Tier 4 Utility Grid** (or islanded curtailment). If a planned battery charge cannot be bought from anyone (e.g. grid offline), the charge is reduced rather than counted as unmet demand, so no energy is ever created. Every agent satisfies, every hour: solar + discharge + P2P bought + grid import + unmet = demand + charge + P2P sold + grid export + curtailed (`test_every_agent_balances_every_hour`).
6. Time advances to $t+1$; the agent observes its new physical state and replans.

### 6. Benchmark Results (GREEDY Baseline vs A* PREDICTIVE Planning)

Default horizon **H = 12 h**, 3 households, 24 hours, seed 42 (`python run_planning.py --scenario <name>`).

| Scenario | Greedy cost (Rs.) | A* cost (Rs.) | Saving | Greedy unmet (kWh) | A* unmet (kWh) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 575.41 | **503.76** | 12.5% | 0.00 | 0.00 |
| Dataset profile | 475.10 | **407.10** | 14.3% | 0.00 | 0.00 |
| Cloud cover | 634.77 | **564.17** | 11.1% | 0.00 | 0.00 |
| Peak demand | 766.93 | **695.28** | 9.3% | 0.00 | 0.00 |
| Grid outage | 422.29 | **393.04** | 6.9% | 19.14 | **13.84** |
| Combined stress | 489.09 | **464.97** | 4.9% | 42.15 | **36.34** |

Baseline detail: peak-hour (17–21 h) grid import falls from 39.70 to **29.40 kWh**, total grid import from 102.63 to 100.70 kWh, and P2P trading rises from 12.46 to 14.41 kWh.

> In outage scenarios, energy that could not be served is not billed, so **read cost together with unmet demand**.

#### Horizon study (baseline day, `python run_planning.py --horizon-study`)

| Policy | Cost (Rs.) | Saving vs Greedy | Nodes / day |
| :--- | ---: | ---: | ---: |
| Greedy | 575.41 | – | – |
| A* H = 3 | 633.81 | −10.1% | 268 |
| A* H = 6 | 576.77 | −0.2% | 828 |
| **A* H = 12** | **503.76** | **+12.5%** | 7,280 |
| A* H = 24 | 512.88 | +10.9% | 71,943 |

A horizon of 3–6 h cannot "see" the 17:00–21:00 peak tariff from the midday solar hours, so the plan is no better than Greedy; 12 h covers it. Going to 24 h costs ~10× more search for no gain, because each agent's plan ignores what neighbours will buy or sell and the extra hours mostly concern the next day. **H = 12 is therefore the project default.**

### 7. Execution CLI Commands
```bash
# 1. Run A* Local Trajectory Planning demo with step-by-step search trace
python run_planning.py --trace --horizon 6

# 2. Side-by-side benchmark comparing Greedy vs A* (default H = 12)
python run_planning.py --compare --scenario baseline
python run_planning.py --compare --scenario real_world_dataset
python run_planning.py --compare --scenario cloud_cover
python run_planning.py --compare --scenario peak_demand
python run_planning.py --compare --scenario grid_outage
python run_planning.py --compare --scenario combined

# 3. Horizon study (Greedy vs A* at H = 3, 6, 12, 24)
python run_planning.py --horizon-study --scenario baseline

# 4. Run dynamic 24-hour scenario simulation with A* predictive mode
python run_scenario.py --scenario combined --mode astar --horizon 12
python run_scenario.py --scenario combined --mode astar --rounds 1   # without renegotiation
```

---

## 17. Automated Test Suite (112 Passing Tests)

Total: **112 passing automated tests** across six suites:
- [`test_foundation.py`](smart_grid_mas/tests/test_foundation.py): 10 tests (Module 1 Foundation)
- [`test_negotiation.py`](smart_grid_mas/tests/test_negotiation.py): 26 tests (Module 2 Decentralized P2P Negotiation)
- [`test_scenarios.py`](smart_grid_mas/tests/test_scenarios.py): 24 tests (Module 3 Dynamic Scenarios & Environmental Shocks)
- [`test_planning.py`](smart_grid_mas/tests/test_planning.py): 28 tests (Module 4 A* Local Planning & Optimization)
- [`test_dashboard_pipeline.py`](smart_grid_mas/tests/test_dashboard_pipeline.py): 11 tests (Dashboard Telemetry Pipeline & Multi-Agent Scalability)
- [`test_correctness.py`](smart_grid_mas/tests/test_correctness.py): 13 tests that check properties for *any* input, not single examples:
  - **A\* optimality**: A* equals brute-force search on 200 random instances; $h \le h^*$; the heuristic expands no more nodes than uniform-cost search.
  - **Energy conservation**: every agent balances every hour, in all 6 scenarios, both modes, with 3 and 10 households.
  - **Negotiation**: no accepted trade is left undelivered (3, 10 and 25 households); surplus is never over-committed; the inverter limit holds across buyers; renegotiation recovers declined energy; negotiation always terminates within the round limit.

Run the complete test suite:
```bash
pytest smart_grid_mas/tests/ -v
```

---

## 18. Known Limitations & Future Work

1. **Adaptive Dynamic Pricing**: P2P offer prices currently follow deterministic bounded ranges rather than continuous marginal clearing double auctions.
2. **Stochastic Weather Forecasters**: Agents utilize deterministic or persistent forecasts rather than full Monte Carlo probabilistic solar prediction.
3. **Planner ignores P2P prices**: each agent's A* cost model prices energy only at grid tariffs (import at TOU rate, export at Rs. 2), so it undervalues selling surplus to neighbours. This is why a longer horizon (24 h) does not beat 12 h.
4. **Unforecast outages**: agents are not told about outages in advance. Passing a known outage schedule to the planner (`grid_available_forecast`) would let agents pre-charge before planned load-shedding.

---

## 19. Interactive SCADA Dashboard (Live Demonstration)

A zero-dependency, single-file HTML industrial SCADA control room dashboard (`dashboard.html`) designed for live academic demonstration and comprehensive multi-agent observability. All telemetry values are 100% simulation-backed from the Python backend (no hardcoded metrics).

### Key Demonstration Features

1. **Top Operations & Scenario Controller**:
   - Scenario Selector: Switch between all 6 simulation environments:
     - `Empirical Smart Meter Dataset (NREL / Ausgrid)`
     - `Standard Baseline Day (Analytical Formula)`
     - `Shock 1: Sudden Cloud Cover (0.4× PV / 60% Reduction)`
     - `Shock 2: Residential Peak Demand Surge (1.5× Load / +50% Surge)`
     - `Shock 3: Macro-Grid Blackout (Microgrid Islanding)`
     - `Combined Stress Test (Multi-Shock Failure)`
   - Segmented Mode Switch: Instant toggle between `Greedy Baseline` (myopic reactive dispatch) and `A* Predictive` (optimal lookahead energy arbitrage).
   - Interactive Quick-Trigger Shock Buttons: One-click demonstration of environmental perturbations during presentations.

2. **Executive SCADA KPI Gauges**:
   - **Total 24h Electricity Cost (Rs.)**: Displays Time-of-Use bill and active A* economic optimization badge.
   - **Macro-Grid Inflow (kWh)**: Substation 11kV/230V import status with live directional flow indicators.
   - **Decentralized P2P Traded (kWh)**: Contract-Net bilateral clearing volume within the neighborhood mesh.
   - **Microgrid Reliability & Unmet Demand (kWh)**: Grid resilience indicator showing 100% served status or outage deficit.

3. **Cyber-Physical Electrical Mimic Panel (SVG)**:
   - High-fidelity single-line schematic depicting:
     - 11kV/230V Substation transformer with closed/tripped circuit breaker indicators.
     - 230V / 50 Hz Common AC Busbar (Point of Common Coupling - PCC).
     - Feeder drop lines with animated current flow particles for grid import and export.
     - Inter-household P2P interconnection mesh with dynamic cyan particle animation during active trades.
     - Prosumer node cards with live PV generation, residential load, battery State-of-Charge gauges, and physical action badges.

4. **Authentic FIPA ACL Protocol Message Stream**:
   - Real-time terminal log displaying simulation-backed message packets directly from `HouseholdAgent` communication channels:
     - `BROADCAST_SURPLUS` / `BROADCAST_DEFICIT`: Decentralized status sharing.
     - `CFP_REQUEST`: Call-for-Proposals with energy demand and price caps.
     - `PROPOSE_OFFER`: Supplier bids with quantity and tariff quotes.
     - `ACCEPT_PROPOSAL` / `REJECT_PROPOSAL`: Bilateral evaluation and agreement.
     - `CONTRACT_SETTLED`: Ledger clearings with transacted kWh, clearing rates, and financial savings.

5. **24-Hour Diurnal Dispatch Canvas Chart**:
   - High-DPI canvas graph tracking Solar PV Generation, Household Demand, Macro-Grid Import, and Average Battery SOC across 24 hours.
   - Color-coded Time-of-Use tariff background bands (Off-Peak: Rs. 3/kWh, Normal: Rs. 5/kWh, Peak: Rs. 8/kWh).
   - Interactive scrub line synchronized with the timestep controller.

6. **Dynamic Algorithm Optimization Scorecard**:
   - Side-by-side head-to-head comparison of Greedy Baseline vs A* Planning across 7 key metrics:
     - Total 24h Energy Bill (Rs.) + calculated economic arbitrage savings.
     - Macro-Grid Inflow (kWh) + peak import reduction.
     - Peak-Hour Grid Import (17:00–21:00) (kWh).
     - Decentralized P2P Traded Volume (kWh).
     - Grid Export Volume (kWh).
     - Unmet Demand (kWh).
     - Average Battery State of Charge (%).

7. **Autonomous Household Agent Fleet Panel**:
   - Dynamic, responsive agent cards that scale seamlessly across variable prosumer populations (3, 10, 25, or 50 households).
   - Each card displays real-time agent ID, operational state, battery SOC fill gauge, PV generation, load, and internal battery/P2P energy flows.

8. **Floating SCADA Operations Dock**:
   - Playback controls: `⏮ Reset` (return to 00:00), `◀ Prev` (-1 hour), `▶ / ⏸ Play/Pause` animation, and `Next ▶` (+1 hour).
   - 00:00–23:00 timeline scrubber slider.
   - Digital clock readout and dynamic TOU tariff badge.
   - Variable playback speed selector (1.0x Realtime, 2.0x Fast, 4.0x Turbo).

### Running the Dashboard

```bash
# Step 1: Execute simulation data export (runs all 6 scenarios in GREEDY and A_STAR modes)
python export_dashboard_data.py

# Step 2: Transform telemetry JSON to browser-compatible JavaScript payload
python generate_dashboard_js.py

# Step 3: Open dashboard in any modern web browser
# Option A: Direct file opening (Windows)
start dashboard.html

# Option B: Local HTTP server
python -m http.server 8000
# Navigate to: http://localhost:8000/dashboard.html
```

### Dashboard Pipeline Files

| File | Purpose |
|------|---------|
| `dashboard.html` | Self-contained SCADA dashboard (vanilla HTML5, CSS3, Canvas API, SVG, JS) |
| `dashboard_data.js` | Auto-generated simulation dataset payload binding `window.GRID_DATA` |
| `dashboard_data.json` | Raw structured telemetry exported directly from `ScenarioRunner` |
| `export_dashboard_data.py` | Multi-scenario simulation runner generating complete hourly telemetry |
| `generate_dashboard_js.py` | Transforms JSON telemetry into dashboard-ready data structure |
| `data/benchmark_microgrid_dataset.csv` | Empirical solar PV and smart meter demand dataset (NREL/Ausgrid) |
| `smart_grid_mas/tests/test_dashboard_pipeline.py` | Automated pipeline validation test suite |

---

## 20. Review 2 Rubric Mapping

| Evaluation Criteria | Marks | Project Implementation & Evidence |
|---------------------|-------|-----------------------------------|
| **1. Tool/Package Selection & Setup** | **3M** | - **Mesa 3.5.1 on Python 3.13.5**: Full ABM framework providing agent lifecycle, model scheduling, and discrete step orchestration.<br>- **NetworkX 3.0**: Decentralized peer communication topology without central master controller.<br>- **NumPy 2.x**: High-performance numerical computations.<br>- **Pytest**: Automated testing harness with reproducible random seeding (`seed=42`).<br>- Verified, documented `requirements.txt` with straightforward setup instructions. |
| **2. Multi-Agent Execution & Interaction** | **3M** | - **11-Phase Discrete Execution Lifecycle**: Strict separation of perception, status broadcast, bilateral negotiation, physical actuation, and telemetry collection.<br>- **FIPA Contract-Net Protocol (CNP)**: Structured message exchanges (`SURPLUS`, `DEFICIT`, `REQUEST`, `OFFER`, `ACCEPT`, `REJECT`, `SETTLE`) logged in telemetry and visually rendered in the SCADA terminal.<br>- **Informed A\* Lookahead Planning**: Dynamic battery state trajectory optimization over configurable horizon (default $H = 12\text{h}$) with an admissible, brute-force-verified heuristic, providing 5–14% Time-of-Use cost savings across all six scenarios.<br>- **Dynamic Renegotiation**: sellers reserve offers so no accepted trade goes undelivered; bounded renegotiation rounds with guaranteed termination recover energy that buyers declined.<br>- **Partial Observability**: Zero global state leakage; agents operate strictly on local sensors and direct peer messages. |
| **3. Demo Quality & Testing Scenarios** | **3M** | - **Industrial SCADA Frontend (`dashboard.html`)**: Complete cyber-physical mimic board, live FIPA protocol feed, 24h diurnal canvas chart, dynamic fleet viewer, and bottom dock controller.<br>- **6 Comprehensive Scenarios**: Empirical Smart Meter Dataset (NREL/Ausgrid), Analytical Baseline, Sudden Cloud Cover (0.4× PV / 60% Reduction), Residential Peak Surge (1.5× Load / +50% Surge), Macro-Grid Blackout (Islanding), and Combined Stress Test.<br>- **112 Passing Automated Tests**: Coverage across Foundation, Negotiation, Dynamic Scenarios, A\* Planning and Dashboard Pipeline, plus property tests for A\* optimality, energy conservation and negotiation invariants. |
| **4. Code Structure & Scalability** | **1M** | - **Layered Modular Architecture**: Clean decoupling across `agents`, `environment`, `communication`, `energy`, `planning`, `scenarios`, `data`, and `tests`.<br>- **Dynamic Scalability**: Verified dynamic scaling from 3 to 10, 25, and 50 household agents without code changes or architectural bottlenecks (tested in `test_multi_agent_scalability`). |


---

## 21. Review Fixes (what changed and why)

| # | Problem found | Fix | Evidence |
| :-- | :-- | :-- | :-- |
| 1 | A* heuristic was **not admissible**: it ignored future solar surplus and export revenue. A* returned a costlier plan than uniform-cost search in ~10% of random cases. | Heuristic is now the exact optimum of a relaxed problem, using each hour's tariff and grid availability. Added `exhaustive_optimal_cost` as a reference solver. | `test_astar_matches_exhaustive_search`, `test_heuristic_admissible_with_future_surplus` |
| 2 | **Energy created from nothing** in A* mode (4.07 kWh at 13:00 in cloud-cover / combined): the planner used the sunny forecast instead of the cloudy sensor reading, and a charge larger than the surplus was not paid for. | Current hour uses observed values; unfunded charge is bought (P2P / grid) or cancelled; curtailment is tracked. | `test_every_agent_balances_every_hour`, `test_cloud_shock_uses_observed_solar_not_forecast` |
| 3 | `run_planning.py --compare` printed fixed labels ("Peak Shaving", "Zero Unmet", "reduced cost by Rs. -1.67") even when A* was worse. | Labels are computed from the numbers (`better` / `WORSE` / `no change`); outage note about unbilled unmet demand; `--horizon-study` added. | `python run_planning.py --scenario combined` |
| 4 | **Sellers over-committed**: the same surplus was offered to every buyer, later ACCEPTs were silently cut and the buyer fell back to the grid. The inverter limit applied per offer instead of per hour. | Proportional reservation of surplus across simultaneous requests; hourly inverter cap across all buyers; price advertised in `SURPLUS` so buyers skip unaffordable sellers. | `test_every_accept_is_delivered_in_full`, `test_seller_p2p_export_respects_inverter_limit` |
| 5 | No renegotiation: energy declined by one buyer was not re-offered to others. | Bounded renegotiation rounds with guaranteed termination (no progress / nobody left / round limit). | `test_renegotiation_recovers_declined_energy`, `test_negotiation_always_terminates_within_round_limit` |
| 6 | A tie-break in the corrected planner left batteries idle during an outage while load went unmet. | Tie-breaker prefers serving load now over later. | `test_19_resilient_planning_during_grid_outage` |
| 7 | With the correct planner, the old default H = 6 was break-even with Greedy. | Default horizon is now **H = 12** (horizon study in Section 16.6). | `test_27_astar_vs_greedy_cost_comparison` |
