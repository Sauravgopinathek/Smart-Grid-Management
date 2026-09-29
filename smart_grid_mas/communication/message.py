from dataclasses import dataclass
from enum import Enum
from typing import Optional
from smart_grid_mas.energy.energy_state import EnergyState


class MessageType(str, Enum):
    """Types of communication messages exchanged between autonomous agents."""
    SURPLUS = "SURPLUS"
    DEFICIT = "DEFICIT"
    REQUEST = "REQUEST"
    OFFER = "OFFER"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass
class Message:
    """Structured message for decentralized communication between HouseholdAgents.
    
    Fields:
        sender_id: ID of the originating household agent
        receiver_id: ID of the intended recipient or 'BROADCAST' for neighborhood-wide sharing
        message_type: Category of message (SURPLUS, DEFICIT, REQUEST, OFFER, ACCEPT, REJECT)
        energy_amount: Magnitude of energy surplus or deficit in kW
        state: The EnergyState of the sender at the time of transmission
        timestamp: Discrete simulation timestep when the message was dispatched
        metadata: Optional dictionary for future negotiation parameters (prices, deadlines, etc.)
    """
    sender_id: str
    receiver_id: str
    message_type: MessageType
    energy_amount: float
    state: EnergyState
    timestamp: int
    metadata: Optional[dict] = None

    def __repr__(self) -> str:
        return (
            f"Message(from={self.sender_id}, to={self.receiver_id}, "
            f"type={self.message_type.value}, amount={self.energy_amount:.2f}kW, "
            f"t={self.timestamp})"
        )
