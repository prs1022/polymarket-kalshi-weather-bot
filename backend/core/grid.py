"""Fibonacci grid execution for reducing slippage and averaging down."""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List

from backend.config import settings

logger = logging.getLogger("trading_bot")

MIN_SHARES = 5  # Polymarket has $1 minimum trade
EXTREME_PRICE = 0.25  # Lower bound for grid (matches market_extreme filter)


@dataclass
class GridLevel:
    """A single level in the Fibonacci grid."""
    level: int          # 0, 1, 2, ...
    limit_price: float  # Limit buy price
    shares: float       # Number of shares to buy
    cost: float         # shares * limit_price


def _generate_fib_sequence(n: int) -> List[int]:
    """Generate Fibonacci sequence of length n: [1, 1, 2, 3, 5, 8, 13, 21, ...]"""
    if n <= 0:
        return []
    if n == 1:
        return [1]
    seq = [1, 1]
    for i in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq


def generate_fibonacci_grid(
    current_price: float,
    budget: float,
    min_shares: int = MIN_SHARES,
    extreme_price: float = EXTREME_PRICE,
    num_levels: int = None,
) -> List[GridLevel]:
    """
    Generate a Fibonacci-spaced grid of limit buy orders.

    Grid spans from current_price down to extreme_price.
    Price intervals follow Fibonacci sequence.
    Size multiplier: X = 1 + 0.1 * fib[i], so deeper levels buy more.

    Since there's no order book integration, all orders are considered filled
    immediately at their limit price (simulated execution).

    Args:
        current_price: Current market price of the token (UP or DOWN)
        budget: Maximum total dollar amount to spend
        min_shares: Minimum shares per level (default 5, PM $1 minimum)
        extreme_price: Lower bound of grid (default 0.25)
        num_levels: Number of grid levels (default: from config GRID_LEVELS)

    Returns:
        List of GridLevel objects, ordered from highest price to lowest
    """
    if num_levels is None:
        num_levels = settings.GRID_LEVELS

    if current_price <= extreme_price:
        shares = max(min_shares, int(budget / current_price))
        return [GridLevel(0, current_price, shares, shares * current_price)]

    price_range = current_price - extreme_price
    fib = _generate_fib_sequence(num_levels)
    fib_sum = sum(fib)

    # Cumulative Fibonacci for price positioning
    cumulative = []
    running = 0
    for f in fib:
        running += f
        cumulative.append(running)

    # Generate raw grid levels (unscaled)
    raw_levels = []
    for i, cum in enumerate(cumulative):
        price = current_price - (cum / fib_sum) * price_range
        price = max(extreme_price, price)
        size_mult = 1.0 + 0.1 * fib[i]
        shares = min_shares * size_mult
        raw_levels.append(GridLevel(i, price, shares, shares * price))

    # Scale to fit budget
    raw_total = sum(l.cost for l in raw_levels)
    if raw_total > budget:
        scale = budget / raw_total
        for l in raw_levels:
            l.shares = max(min_shares, round(l.shares * scale))
            l.cost = l.shares * l.limit_price

    # Round shares to integers
    for l in raw_levels:
        l.shares = int(round(l.shares))
        l.cost = l.shares * l.limit_price

    logger.info(
        f"Grid: {len(raw_levels)} levels, "
        f"price {raw_levels[0].limit_price:.3f} → {raw_levels[-1].limit_price:.3f}, "
        f"shares {sum(l.shares for l in raw_levels)}, "
        f"cost ${sum(l.cost for l in raw_levels):.2f}, "
        f"avg {sum(l.cost for l in raw_levels) / sum(l.shares for l in raw_levels):.3f}"
    )

    return raw_levels


def check_grid_fills(grid_orders, current_market_price: float):
    """
    Check which pending grid orders should be filled based on current market price.

    A limit BUY at price P is filled when market_price <= P.

    Args:
        grid_orders: List of GridOrder DB objects with .status, .limit_price
        current_market_price: Current market price of the token

    Returns:
        List of GridOrder objects that were newly filled
    """
    newly_filled = []
    for order in grid_orders:
        if order.status != "pending":
            continue
        if current_market_price <= order.limit_price:
            order.status = "filled"
            order.fill_price = order.limit_price
            order.filled_at = datetime.utcnow()
            newly_filled.append(order)

    return newly_filled


def update_trade_from_grid(trade, grid_orders):
    """
    Update a Trade's entry_price and size based on filled grid orders.

    Args:
        trade: Trade DB object
        grid_orders: List of GridOrder DB objects
    """
    filled = [o for o in grid_orders if o.status == "filled"]
    if not filled:
        return

    total_cost = sum(o.cost for o in filled)
    total_shares = sum(o.shares for o in filled)

    trade.entry_price = total_cost / total_shares if total_shares > 0 else 0
    trade.size = total_cost
    trade.grid_filled_cost = total_cost
    trade.grid_filled_shares = total_shares
