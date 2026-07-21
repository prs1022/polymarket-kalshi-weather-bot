"""Grid execution for reducing slippage and averaging down.

Supports two price-spacing modes:
- "fibonacci": Fibonacci cumulative spacing (denser near current price)
- "equal": Equal spacing across the price range

Both modes use Fibonacci share multiplier (deeper levels buy more).
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List

from backend.config import settings

logger = logging.getLogger("trading_bot")

MIN_SHARES = 5  # Polymarket has $1 minimum trade


def _get_extreme_price() -> float:
    """Get grid lower bound from config."""
    return settings.GRID_LOWER_BOUND


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
    extreme_price: float = None,
    num_levels: int = None,
) -> List[GridLevel]:
    """
    Generate a grid of limit buy orders.

    Grid spans from MIN_ENTRY_PRICE (fixed upper bound) down to extreme_price.
    Price spacing depends on GRID_MODE:
    - "fibonacci": Fibonacci cumulative spacing (denser near current price)
    - "equal": Equal spacing across the range

    Share multiplier: X = 1 + 0.1 * fib[i], so deeper levels buy more.

    Args:
        current_price: Current market price of the token (UP or DOWN) — used for fallback only
        budget: Maximum total dollar amount to spend
        min_shares: Minimum shares per level (default 5, PM $1 minimum)
        extreme_price: Lower bound of grid (default: GRID_LOWER_BOUND from config)
        num_levels: Number of grid levels (default: from config GRID_LEVELS)

    Returns:
        List of GridLevel objects, ordered from highest price to lowest
    """
    if num_levels is None:
        num_levels = settings.GRID_LEVELS
    if extreme_price is None:
        extreme_price = settings.GRID_LOWER_BOUND

    # Fixed upper bound: MIN_ENTRY_PRICE (e.g. 0.48)
    grid_upper = settings.MIN_ENTRY_PRICE

    if grid_upper <= extreme_price:
        shares = max(min_shares, int(budget / grid_upper))
        return [GridLevel(0, grid_upper, shares, shares * grid_upper)]

    price_range = grid_upper - extreme_price
    fib = _generate_fib_sequence(num_levels)
    fib_sum = sum(fib)

    # Generate raw grid levels (unscaled)
    raw_levels = []
    for i in range(num_levels):
        if settings.GRID_MODE == "equal":
            # Equal spacing: each level is 1/N of the range apart
            price = grid_upper - ((i + 1) / num_levels) * price_range
        else:
            # Fibonacci spacing: cumulative Fibonacci distribution
            cumulative = sum(fib[:i + 1])
            price = grid_upper - (cumulative / fib_sum) * price_range

        price = round(max(extreme_price, price), 2)
        size_mult = 1.0 + 0.1 * fib[i]
        shares = min_shares * size_mult
        raw_levels.append(GridLevel(i, price, round(shares, 2), round(shares * price, 2)))

    # Scale to fit budget
    raw_total = sum(l.cost for l in raw_levels)
    if raw_total > budget:
        scale = budget / raw_total
        for l in raw_levels:
            l.shares = round(max(min_shares, l.shares * scale), 2)
            l.cost = round(l.shares * l.limit_price, 2)

    # Round to 2 decimal places
    for l in raw_levels:
        l.shares = round(l.shares, 2)
        l.cost = round(l.shares * l.limit_price, 2)

    logger.info(
        f"Grid [{settings.GRID_MODE}]: {len(raw_levels)} levels, "
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
    trade.size = total_cost        # Dollars spent
    trade.shares = total_shares    # Shares bought
    trade.grid_filled_cost = total_cost
    trade.grid_filled_shares = total_shares
