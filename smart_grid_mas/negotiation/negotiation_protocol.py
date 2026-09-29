import math
from typing import List, Tuple, Optional, Dict, Any
from smart_grid_mas.communication.message import Message, MessageType
from smart_grid_mas.energy.energy_state import EnergyState
from smart_grid_mas.negotiation.trade import Trade, TradeStatus


class NegotiationProtocol:
    """Decentralized Bilateral Negotiation Protocol (Contract-Net variant).
    
    This protocol coordinates peer-to-peer energy trading among autonomous households:
    1. Deficit agents send REQUEST messages with requested energy and price ceiling.
    2. Surplus agents evaluate requests against available surplus and reply with OFFER messages.
    3. Deficit agents evaluate candidate offers deterministically:
       - Reject offers exceeding the buyer's price ceiling.
       - Prefer lowest price per kWh.
       - Tie-break on highest available energy quantity.
       - Tie-break on deterministic sender ID sorting.
    4. Deficit agents issue ACCEPT to selected seller(s) and REJECT to unselected ones.
    5. Surplus agents verify physical capacity and confirm/settle the Trade.
    
    IMPORTANT:
    This class contains purely decentralized protocol logic invoked by the agents
    themselves using their own local states. It does NOT make central decisions.
    """

    @staticmethod
    def create_request(
        buyer_id: str,
        seller_id: str,
        requested_energy_kwh: float,
        max_price_per_kwh: float,
        timestamp: int,
    ) -> Message:
        """Create a structured REQUEST message from a deficit household to a surplus peer."""
        return Message(
            sender_id=buyer_id,
            receiver_id=seller_id,
            message_type=MessageType.REQUEST,
            energy_amount=round(requested_energy_kwh, 4),
            state=EnergyState.DEFICIT,
            timestamp=timestamp,
            metadata={
                "requested_energy": round(requested_energy_kwh, 4),
                "max_price_per_kwh": round(max_price_per_kwh, 2),
            },
        )

    @staticmethod
    def evaluate_request(
        seller_agent: Any,
        request_msg: Message,
        current_step: int,
        max_offer_kwh: Optional[float] = None,
    ) -> Optional[Message]:
        """Surplus agent evaluates an incoming REQUEST and optionally crafts an OFFER.
        
        Autonomous Seller Logic:
        - Must not sell to self.
        - Must have actual available surplus.
        - Request must be from current simulation timestep.
        - Caps offered energy by available surplus and physical export limits.
        - Caps offered energy by `max_offer_kwh`, the share of surplus the seller
          has reserved for this buyer (see `allocate_surplus`), so the seller
          never promises the same kWh to two buyers.
        """
        # Safety checks
        if request_msg.sender_id == seller_agent.agent_id:
            return None
        if request_msg.timestamp != current_step:
            return None
        if request_msg.energy_amount <= 1e-6:
            return None
        if seller_agent.available_surplus <= 1e-6:
            return None

        # Determine offered energy
        export_limit = getattr(seller_agent, "max_charge_rate_kw", 5.0)  # physical inverter limit
        offered_energy = min(
            seller_agent.available_surplus,
            request_msg.energy_amount,
            export_limit,
        )
        if max_offer_kwh is not None:
            offered_energy = min(offered_energy, max_offer_kwh)

        if offered_energy <= 1e-6:
            return None

        price_per_kwh = getattr(seller_agent, "preferred_p2p_sell_price", 5.0)
        total_price = round(offered_energy * price_per_kwh, 2)

        return Message(
            sender_id=seller_agent.agent_id,
            receiver_id=request_msg.sender_id,
            message_type=MessageType.OFFER,
            energy_amount=round(offered_energy, 4),
            state=EnergyState.SURPLUS,
            timestamp=current_step,
            metadata={
                "offered_energy": round(offered_energy, 4),
                "price_per_kwh": round(price_per_kwh, 2),
                "total_price": total_price,
            },
        )

    @staticmethod
    def allocate_surplus(available_kwh: float, requested_kwh: List[float]) -> List[float]:
        """Split a seller's surplus across simultaneous requests without over-committing.

        - If total demand fits in the surplus, every request is reserved in full.
        - Otherwise each buyer is reserved a share proportional to what it asked for
          (fair, order-independent, and the shares sum exactly to the surplus).

        Guarantees sum(result) <= available_kwh, so every ACCEPT a buyer sends can
        be settled in full. Energy a buyer does not take is released and can be
        re-offered in the next negotiation round.
        """
        available = max(0.0, available_kwh)
        total = sum(max(0.0, r) for r in requested_kwh)
        if total <= available + 1e-9:
            return [max(0.0, r) for r in requested_kwh]
        if total <= 1e-12:
            return [0.0 for _ in requested_kwh]
        # Round DOWN so rounding can never push the total above the surplus.
        return [math.floor(available * max(0.0, r) / total * 1e4) / 1e4 for r in requested_kwh]

    @staticmethod
    def evaluate_offers(
        buyer_agent: Any,
        offers: List[Message],
        current_step: int,
    ) -> Tuple[List[Tuple[Message, float]], List[Message]]:
        """Buyer autonomously evaluates candidate offers using deterministic criteria.
        
        Selection Criteria:
        1. Discard offers exceeding buyer's max acceptable price ceiling.
        2. Discard offers from self or stale timesteps.
        3. Sort eligible offers by:
           - Lowest unit price (ascending)
           - Highest offered quantity (descending)
           - Deterministic seller ID (ascending)
        4. Select offers incrementally until remaining deficit is satisfied.
        
        Returns:
            Tuple of:
            - List of tuples (selected_offer_msg, energy_to_accept)
            - List of rejected offer messages
        """
        accepted: List[Tuple[Message, float]] = []
        rejected: List[Message] = []

        valid_offers: List[Message] = []
        for offer in offers:
            if offer.sender_id == buyer_agent.agent_id:
                continue
            if offer.timestamp != current_step:
                continue
            if offer.message_type != MessageType.OFFER:
                continue
            
            offer_price = offer.metadata.get("price_per_kwh", float("inf")) if offer.metadata else float("inf")
            if offer_price > buyer_agent.max_p2p_buy_price:
                rejected.append(offer)
            else:
                valid_offers.append(offer)

        # Deterministic sorting: price asc, energy desc, sender_id asc
        valid_offers.sort(
            key=lambda o: (
                o.metadata.get("price_per_kwh", float("inf")),
                -o.energy_amount,
                o.sender_id,
            )
        )

        needed = buyer_agent.remaining_deficit
        for offer in valid_offers:
            if needed > 1e-6:
                take_amount = min(offer.energy_amount, needed)
                accepted.append((offer, round(take_amount, 4)))
                needed = round(needed - take_amount, 4)
            else:
                rejected.append(offer)

        return accepted, rejected

    @staticmethod
    def create_accept(
        buyer_id: str,
        seller_id: str,
        accepted_energy_kwh: float,
        price_per_kwh: float,
        timestamp: int,
    ) -> Message:
        """Create an ACCEPT message dispatched to the selected seller."""
        total = round(accepted_energy_kwh * price_per_kwh, 2)
        return Message(
            sender_id=buyer_id,
            receiver_id=seller_id,
            message_type=MessageType.ACCEPT,
            energy_amount=round(accepted_energy_kwh, 4),
            state=EnergyState.DEFICIT,
            timestamp=timestamp,
            metadata={
                "accepted_energy": round(accepted_energy_kwh, 4),
                "price_per_kwh": round(price_per_kwh, 2),
                "total_price": total,
            },
        )

    @staticmethod
    def create_reject(
        buyer_id: str,
        seller_id: str,
        reason: str,
        timestamp: int,
    ) -> Message:
        """Create a REJECT message dispatched to unselected offerers."""
        return Message(
            sender_id=buyer_id,
            receiver_id=seller_id,
            message_type=MessageType.REJECT,
            energy_amount=0.0,
            state=EnergyState.DEFICIT,
            timestamp=timestamp,
            metadata={"reason": reason},
        )

    @staticmethod
    def settle_trade(
        seller_agent: Any,
        buyer_agent: Any,
        accept_msg: Message,
        trade_id: str,
    ) -> Optional[Trade]:
        """Execute physical energy transfer and financial balance updates.
        
        Physical Safety Invariants:
        - Seller cannot sell more than available surplus.
        - Buyer cannot accept more than remaining deficit.
        - No self-trading.
        """
        if seller_agent.agent_id == buyer_agent.agent_id:
            return None

        requested_amount = accept_msg.energy_amount
        if requested_amount <= 1e-6:
            return None

        # Strict trade amount bounding
        actual_trade_kwh = min(
            seller_agent.available_surplus,
            buyer_agent.remaining_deficit,
            requested_amount,
        )

        if actual_trade_kwh <= 1e-6:
            return None

        price = accept_msg.metadata.get("price_per_kwh", seller_agent.preferred_p2p_sell_price) if accept_msg.metadata else seller_agent.preferred_p2p_sell_price
        total_val = round(actual_trade_kwh * price, 2)

        # Instantiate Trade Record
        trade = Trade(
            trade_id=trade_id,
            seller_id=seller_agent.agent_id,
            buyer_id=buyer_agent.agent_id,
            energy_amount=round(actual_trade_kwh, 4),
            price_per_kwh=round(price, 2),
            total_price=total_val,
            timestamp=accept_msg.timestamp,
            status=TradeStatus.COMPLETED,
        )

        # Update Seller State
        seller_agent.available_surplus = round(max(0.0, seller_agent.available_surplus - actual_trade_kwh), 4)
        seller_agent.p2p_energy_sold = round(seller_agent.p2p_energy_sold + actual_trade_kwh, 4)
        seller_agent.p2p_revenue = round(seller_agent.p2p_revenue + total_val, 2)
        seller_agent.completed_trades.append(trade)

        # Update Buyer State
        buyer_agent.remaining_deficit = round(max(0.0, buyer_agent.remaining_deficit - actual_trade_kwh), 4)
        buyer_agent.p2p_energy_bought = round(buyer_agent.p2p_energy_bought + actual_trade_kwh, 4)
        buyer_agent.p2p_cost = round(buyer_agent.p2p_cost + total_val, 2)
        buyer_agent.completed_trades.append(trade)

        return trade
