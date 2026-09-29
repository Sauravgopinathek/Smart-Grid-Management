from enum import Enum


class EnergyState(str, Enum):
    """Energy balance state of a HouseholdAgent."""
    SURPLUS = "SURPLUS"
    DEFICIT = "DEFICIT"
    BALANCED = "BALANCED"


class AgentAction(str, Enum):
    """Actuators / Actions available to a HouseholdAgent.
    
    Review 1 Actuators:
    - CHARGE: Store surplus energy into the local battery
    - DISCHARGE: Use energy from the local battery to cover local deficit
    - CONSUME: Directly utilize generated solar energy to meet local demand
    - SELL: Export surplus energy (to neighborhood peers or utility grid)
    - BUY: Import energy from external source (grid or peer) when battery cannot cover deficit
    """
    CHARGE = "CHARGE"
    DISCHARGE = "DISCHARGE"
    CONSUME = "CONSUME"
    SELL = "SELL"
    BUY = "BUY"
