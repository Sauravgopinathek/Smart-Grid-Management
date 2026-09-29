from dataclasses import dataclass
from enum import Enum


class TradeStatus(str, Enum):
    """Lifecycle statuses for a Peer-to-Peer (P2P) energy trade."""
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class Trade:
    """Structured Peer-to-Peer Energy Transaction Record.
    
    Fields:
        trade_id: Unique identifier for the trade record
        seller_id: ID of the selling household agent
        buyer_id: ID of the purchasing household agent
        energy_amount: Energy transferred in kilowatt-hours (kWh)
        price_per_kwh: Agreed unit price in ₹/kWh
        total_price: Total transaction value in ₹ (energy_amount * price_per_kwh)
        timestamp: Simulation timestep at which the trade was completed
        status: Current status of the transaction (TradeStatus)
    """
    trade_id: str
    seller_id: str
    buyer_id: str
    energy_amount: float
    price_per_kwh: float
    total_price: float
    timestamp: int
    status: TradeStatus = TradeStatus.COMPLETED

    def __repr__(self) -> str:
        return (
            f"Trade({self.trade_id}: {self.seller_id} -> {self.buyer_id}, "
            f"{self.energy_amount:.2f}kWh @ ₹{self.price_per_kwh:.2f}/kWh = ₹{self.total_price:.2f}, "
            f"t={self.timestamp}, status={self.status.value})"
        )
