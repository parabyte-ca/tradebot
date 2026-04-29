"""Position sizing using the half-Kelly criterion.

Position size = (edge / odds) / 2  × portfolio_value, capped at MAX_POSITION_PCT.

edge  = predicted_prob - 0.5  (excess probability over chance)
odds  = take_profit_pct / stop_loss_pct  (reward-to-risk ratio)

A minimum edge of 2% is required before any capital is committed.
Each position is capped at MAX_POSITION_PCT of portfolio equity.
Total capital deployed across all positions is capped at
MAX_POSITIONS × MAX_POSITION_PCT.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List

from config.settings import get_settings

logger = logging.getLogger(__name__)

_MIN_EDGE = 0.02  # require at least 2% edge above 50% to size a position


@dataclass
class PositionOrder:
    """Recommended position for a single symbol."""
    symbol: str
    quantity: int          # whole shares
    dollar_value: float
    kelly_fraction: float
    predicted_prob: float


def half_kelly_size(
    predicted_prob: float,
    portfolio_value: float,
    price: float,
) -> PositionOrder | None:
    """Compute a half-Kelly position size for a single symbol.

    Args:
        predicted_prob: Model's up-probability (0–1).
        portfolio_value: Current total equity in dollars.
        price:           Current share price.

    Returns:
        PositionOrder, or None if edge is below minimum or price is zero.
    """
    cfg = get_settings()

    if price <= 0:
        return None

    edge = predicted_prob - 0.5
    if edge < _MIN_EDGE:
        return None

    odds = cfg.take_profit_pct / cfg.stop_loss_pct
    kelly = edge / odds
    half_k = kelly / 2.0

    # Cap at max position %
    capped_fraction = min(half_k, cfg.max_position_pct)
    dollar_value = portfolio_value * capped_fraction
    quantity = int(dollar_value / price)

    if quantity < 1:
        return None

    return PositionOrder(
        symbol="",  # caller fills in
        quantity=quantity,
        dollar_value=quantity * price,
        kelly_fraction=capped_fraction,
        predicted_prob=predicted_prob,
    )


def size_positions(
    scores: Dict[str, float],
    prices: Dict[str, float],
    portfolio_value: float,
    max_positions: int | None = None,
) -> List[PositionOrder]:
    """Rank and size positions for all scored symbols.

    Args:
        scores:          {symbol: predicted_up_probability}
        prices:          {symbol: current_price}
        portfolio_value: Current equity.
        max_positions:   Override for max simultaneous positions (defaults to config).

    Returns:
        List of PositionOrder sorted by predicted_prob descending, capped at
        max_positions.
    """
    cfg = get_settings()
    if max_positions is None:
        max_positions = cfg.max_positions

    orders: List[PositionOrder] = []
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    for symbol, prob in ranked:
        if len(orders) >= max_positions:
            break
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue
        order = half_kelly_size(prob, portfolio_value, price)
        if order is None:
            continue
        order.symbol = symbol
        orders.append(order)
        logger.debug(
            "Sized %s: prob=%.3f kelly=%.3f qty=%d $%.0f",
            symbol, prob, order.kelly_fraction, order.quantity, order.dollar_value,
        )

    return orders
