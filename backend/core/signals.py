"""Signal generator for BTC 5-minute Up/Down markets."""
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field
import asyncio

from backend.config import settings
from backend.data.btc_markets import BtcMarket, fetch_active_btc_markets
from backend.data.crypto import fetch_crypto_price, compute_btc_microstructure
from backend.models.database import SessionLocal, Signal

logger = logging.getLogger("trading_bot")


@dataclass
class TradingSignal:
    """A trading signal for a BTC 5-min market."""
    market: BtcMarket

    # Core signal data
    model_probability: float = 0.5  # Our estimated probability of UP
    market_probability: float = 0.5  # Market's implied UP probability
    edge: float = 0.0
    direction: str = "up"  # "up" or "down"

    # Confidence and sizing
    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    # Metadata
    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # BTC price context
    btc_price: float = 0.0
    btc_change_1h: float = 0.0
    btc_change_24h: float = 0.0

    @property
    def passes_threshold(self) -> bool:
        """Check if signal passes minimum edge threshold."""
        return abs(self.edge) >= settings.MIN_EDGE_THRESHOLD


def calculate_edge(
    model_prob: float,
    market_price: float
) -> tuple[float, str]:
    """
    Calculate edge and determine direction.

    For BTC 5-min markets:
    - "up" is equivalent to "yes" (outcomePrices[0])
    - "down" is equivalent to "no" (outcomePrices[1])

    Returns:
        (edge, direction) where direction is "up" or "down"
    """
    # Edge for UP bet
    up_edge = model_prob - market_price

    # Edge for DOWN bet
    down_edge = (1 - model_prob) - (1 - market_price)

    if up_edge >= down_edge:
        return up_edge, "up"
    else:
        return down_edge, "down"


def calculate_kelly_size(
    edge: float,
    probability: float,
    market_price: float,
    direction: str,
    bankroll: float
) -> float:
    """
    Calculate position size using fractional Kelly criterion.

    Kelly formula: f = (p * b - q) / b
    where:
        f = fraction of bankroll to bet
        p = probability of winning
        q = probability of losing (1 - p)
        b = odds (payout ratio)
    """
    if direction == "up":
        win_prob = probability
        price = market_price
    else:
        win_prob = 1 - probability
        price = 1 - market_price

    if price <= 0 or price >= 1:
        return 0

    odds = (1 - price) / price

    lose_prob = 1 - win_prob
    kelly = (win_prob * odds - lose_prob) / odds

    # Apply fractional Kelly
    kelly *= settings.KELLY_FRACTION

    # Cap at maximum per-trade limit
    max_fraction = 0.05  # 5% max per trade
    kelly = min(kelly, max_fraction)

    kelly = max(kelly, 0)

    size = kelly * bankroll

    # Hard cap from config
    size = min(size, settings.MAX_TRADE_SIZE)

    return size


async def generate_btc_signal(market: BtcMarket) -> Optional[TradingSignal]:
    """
    Generate a trading signal for a BTC 5-min Up/Down market.

    Uses real 1-minute candle data from Binance to compute:
    - RSI (mean reversion), Momentum (trend), VWAP deviation,
      SMA crossover, and market skew as a weighted composite.
    - Convergence filter: requires 3/4 indicators to agree.
    - Entry price filter: only enter when price ≤ MAX_ENTRY_PRICE.
    """
    try:
        micro = await compute_btc_microstructure()
    except Exception as e:
        logger.warning(f"Failed to compute microstructure: {e}")
        return None

    if not micro:
        return None

    market_up_prob = market.up_price

    # Skip resolved markets
    if market_up_prob < 0.02 or market_up_prob > 0.98:
        return None

    # --- Entry price filter: only trade when price ≤ 50c ---
    entry_price = market_up_prob  # will be overridden per-direction below
    # We check after direction is determined

    # --- Individual indicator signals (each returns a bias from -1 to +1) ---

    # 1) RSI: momentum-following — high RSI = bullish, low RSI = bearish
    #    In 5-min BTC markets, strong trends keep RSI elevated for multiple candles.
    #    Mean-reversion gets crushed by short squeezes. Follow the trend instead.
    #    Linear mapping: S_rsi = (RSI - 50) / 25, clamped to [-1, +1]
    rsi_signal = max(-1.0, min(1.0, (micro.rsi - 50.0) / 25.0))

    # 2) Momentum: weighted blend of 1m, 5m, 15m changes
    #    Positive momentum = UP bias (unchanged — already momentum-following)
    mom_blend = micro.momentum_1m * 0.5 + micro.momentum_5m * 0.35 + micro.momentum_15m * 0.15
    # Normalise: ±0.1% is a strong 5-min signal for BTC
    momentum_signal = max(-1.0, min(1.0, mom_blend / 0.10))

    # 3) VWAP deviation: price above VWAP = UP momentum, below = DOWN (unchanged)
    vwap_signal = max(-1.0, min(1.0, micro.vwap_deviation / 0.05))

    # 4) SMA crossover: sma5 > sma15 = bullish (unchanged)
    sma_signal = max(-1.0, min(1.0, micro.sma_crossover / 0.03))

    # 5) Market skew: REMOVED contrarian logic
    #    Data showed the market is usually right for BTC 5-min — don't fade it.
    #    Instead, slightly follow the market: if market says UP, lean UP.
    market_skew = market_up_prob - 0.50
    skew_signal = max(-1.0, min(1.0, market_skew * 2))

    # --- Convergence filter: count how many indicators agree on direction ---
    indicator_signs = [
        rsi_signal,
        momentum_signal,
        vwap_signal,
        sma_signal,
    ]
    up_votes = sum(1 for s in indicator_signs if s > 0.05)
    down_votes = sum(1 for s in indicator_signs if s < -0.05)

    # Convergence: require all 4 indicators to agree.
    # Data analysis of 451 settled trades:
    #   4/4 convergence → 49.9% accuracy (coin flip — but model base was 0.50, not market)
    #   3/4 convergence → 35.0% accuracy (anti-predictive!)
    #   2/4 convergence → 39.5% accuracy (also anti-predictive)
    # With market-based model, 4/4 convergence + market base should improve Brier.
    min_convergence = settings.MIN_CONVERGENCE
    has_convergence = up_votes >= min_convergence or down_votes >= min_convergence

    # --- Weighted composite ---
    w = settings
    composite = (
        rsi_signal * w.WEIGHT_RSI
        + momentum_signal * w.WEIGHT_MOMENTUM
        + vwap_signal * w.WEIGHT_VWAP
        + sma_signal * w.WEIGHT_SMA
        + skew_signal * w.WEIGHT_MARKET_SKEW
    )

    # --- Market-based probability model ---
    # OLD: model started at 0.50 and ignored market price entirely.
    #   When market said 35% and model said 50%, the "15% edge" was FAKE.
    #   The market was right — actual win rate was 24%.
    #
    # NEW: model starts at MARKET PRICE, then adjusts by composite.
    #   model_prob = market_prob + composite * COMPOSITE_MULTIPLIER
    #   Edge = model_prob - market_prob = composite * COMPOSITE_MULTIPLIER
    #   When composite = 0 (no signal): model = market → edge = 0 → no trade
    #   When composite = 0.5 (moderate agreement): edge = 7.5% (real signal)
    #   When composite = 1.0 (all indicators max bullish): edge = 15%
    #
    # This eliminates fake edges from clamp artifacts and improves Brier
    # because the base prediction (market price) is well-calibrated.
    deviation = composite * settings.COMPOSITE_MULTIPLIER
    model_up_prob = market_up_prob + deviation
    # Clamp deviation to ±MAX_MODEL_DEVIATION from market price
    model_up_prob = max(
        market_up_prob - settings.MAX_MODEL_DEVIATION,
        min(market_up_prob + settings.MAX_MODEL_DEVIATION, model_up_prob)
    )
    # Safety clamp to [0.05, 0.95]
    model_up_prob = max(0.05, min(0.95, model_up_prob))

    # Calculate edge and direction
    edge, direction = calculate_edge(model_up_prob, market_up_prob)

    # --- Signal inversion switch ---
    # Data shows the model is anti-predictive (win rate < 50%).
    # Flipping the direction turns anti-predictive into predictive.
    # Toggle via config INVERT_SIGNAL.
    if settings.INVERT_SIGNAL:
        if direction == "up":
            direction = "down"
            edge = (1 - model_up_prob) - (1 - market_up_prob)  # recalculate edge for inverted direction
        else:
            direction = "up"
            edge = model_up_prob - market_up_prob

    # --- Entry price filter: only buy in the sweet spot [MIN, MAX] ---
    if direction == "up":
        entry_price = market_up_prob
    else:
        entry_price = market.down_price

    # --- Entry price floor: don't buy tokens below MIN_ENTRY_PRICE ---
    # Data analysis of 451 settled trades shows:
    #   entry < 40c → 24% win rate (fake edge from model clamp [0.40-0.60])
    #   entry 40-50c → 78% win rate (real signal)
    # The model outputs ~0.50, so when market price is 35c, the "edge" is
    # just 50%-35%=15% — a clamp artifact, not a real prediction.
    # This floor replaces the old market_extreme filter at 0.25.

    # Time-remaining filter: only trade windows in the sweet spot
    now = datetime.utcnow()
    # Handle timezone-aware window_end
    window_end = market.window_end
    if window_end.tzinfo is not None:
        window_end = window_end.replace(tzinfo=None)
    time_remaining = (window_end - now).total_seconds()
    time_ok = settings.MIN_TIME_REMAINING <= time_remaining <= settings.MAX_TIME_REMAINING

    passes_filters = (
        has_convergence
        and entry_price >= settings.MIN_ENTRY_PRICE
        and entry_price <= settings.MAX_ENTRY_PRICE
        and time_ok
    )

    # Zero out edge if filters fail (signal still returned for UI visibility)
    if not passes_filters:
        edge = 0.0

    # Confidence: based on convergence strength + volatility
    #   Low volatility = lower confidence (less movement expected)
    vol_factor = min(1.0, micro.volatility / 0.05) if micro.volatility > 0 else 0.5
    convergence_strength = max(up_votes, down_votes) / 4.0
    confidence = min(0.8, 0.3 + convergence_strength * 0.3 + abs(composite) * 0.2) * vol_factor

    # Kelly sizing
    bankroll = settings.INITIAL_BANKROLL
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_up_prob,
        market_price=market_up_prob,
        direction=direction,
        bankroll=bankroll,
    )

    # Build reasoning
    filter_status = "ACTIONABLE" if passes_filters else "FILTERED"
    filter_reasons = []
    if not has_convergence:
        filter_reasons.append(f"convergence {max(up_votes, down_votes)}/4 < {settings.MIN_CONVERGENCE}")
    if not time_ok:
        filter_reasons.append(f"time {time_remaining:.0f}s not in [{settings.MIN_TIME_REMAINING},{settings.MAX_TIME_REMAINING}]")
    if entry_price < settings.MIN_ENTRY_PRICE:
        filter_reasons.append(f"entry {entry_price:.0%} < {settings.MIN_ENTRY_PRICE:.0%}")
    if entry_price > settings.MAX_ENTRY_PRICE:
        filter_reasons.append(f"entry {entry_price:.0%} > {settings.MAX_ENTRY_PRICE:.0%}")
    filter_note = f" [{', '.join(filter_reasons)}]" if filter_reasons else ""

    reasoning = (
        f"[{filter_status}]{filter_note} "
        f"BTC ${micro.price:,.0f} | RSI:{micro.rsi:.0f} Mom1m:{micro.momentum_1m:+.3f}% "
        f"Mom5m:{micro.momentum_5m:+.3f}% VWAP:{micro.vwap_deviation:+.3f}% "
        f"SMA:{micro.sma_crossover:+.4f}% Vol:{micro.volatility:.4f}% | "
        f"Composite:{composite:+.3f} -> Model UP:{model_up_prob:.0%} vs Mkt:{market_up_prob:.0%} | "
        f"Edge:{edge:+.1%} -> {direction.upper()} @ {entry_price:.0%} | "
        f"Convergence:{max(up_votes, down_votes)}/4 | "
        f"Window ends: {market.window_end.strftime('%H:%M UTC')}"
    )

    return TradingSignal(
        market=market,
        model_probability=model_up_prob,
        market_probability=market_up_prob,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=[f"binance_microstructure_{micro.source}"],
        reasoning=reasoning,
        btc_price=micro.price,
        btc_change_1h=micro.momentum_5m * 12,  # rough annualisation for display
        btc_change_24h=micro.momentum_15m * 96,  # rough extrapolation for display
    )


async def scan_for_signals() -> List[TradingSignal]:
    """
    Scan BTC 5-min markets and generate signals.
    """
    signals = []

    logger.info("=" * 50)
    logger.info("BTC 5-MIN SCAN: Fetching markets from Polymarket...")

    try:
        markets = await fetch_active_btc_markets()
    except Exception as e:
        logger.error(f"Failed to fetch BTC markets: {e}")
        markets = []

    logger.info(f"Found {len(markets)} active BTC 5-min markets")

    for market in markets:
        try:
            signal = await generate_btc_signal(market)
            if signal:
                signals.append(signal)
        except Exception as e:
            logger.debug(f"Signal generation failed for {market.slug}: {e}")

        # Small delay to avoid CoinGecko rate limits
        # (only needed if we're making multiple calls - reuse first result)
        await asyncio.sleep(0.1)

    # Sort by absolute edge (best opportunities first)
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    actionable = [s for s in signals if s.passes_threshold]
    logger.info(f"=" * 50)
    logger.info(f"SCAN COMPLETE: {len(signals)} signals, {len(actionable)} actionable")

    for signal in actionable[:5]:
        logger.info(f"  {signal.market.slug}")
        logger.info(f"    Edge: {signal.edge:+.1%} -> {signal.direction.upper()} @ ${signal.suggested_size:.2f}")

    # Persist signals with non-zero edge to DB for calibration tracking
    _persist_signals(signals)

    return signals


def _persist_signals(signals: list):
    """Save signals with non-zero edge to DB, deduplicating on (market_ticker, timestamp)."""
    to_save = [s for s in signals if abs(s.edge) > 0]
    if not to_save:
        return

    db = SessionLocal()
    try:
        for signal in to_save:
            # Dedup: skip if we already logged this signal for this market window
            existing = db.query(Signal).filter(
                Signal.market_ticker == signal.market.market_id,
                Signal.timestamp >= signal.timestamp.replace(second=0, microsecond=0),
            ).first()
            if existing:
                continue

            db_signal = Signal(
                market_ticker=signal.market.market_id,
                platform="polymarket",
                timestamp=signal.timestamp,
                direction=signal.direction,
                model_probability=signal.model_probability,
                market_price=signal.market_probability,
                edge=signal.edge,
                confidence=signal.confidence,
                kelly_fraction=signal.kelly_fraction,
                suggested_size=signal.suggested_size,
                sources=signal.sources,
                reasoning=signal.reasoning,
                executed=False,
            )
            db.add(db_signal)

        db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist signals: {e}")
        db.rollback()
    finally:
        db.close()


async def get_actionable_signals() -> List[TradingSignal]:
    """Get only signals that pass the edge threshold."""
    all_signals = await scan_for_signals()
    return [s for s in all_signals if s.passes_threshold]


if __name__ == "__main__":
    async def test():
        print("Scanning BTC 5-min markets for signals...")
        signals = await scan_for_signals()
        print(f"\nFound {len(signals)} total signals")

        actionable = [s for s in signals if s.passes_threshold]
        print(f"Actionable signals (>{settings.MIN_EDGE_THRESHOLD:.0%} edge): {len(actionable)}")

        for signal in actionable[:5]:
            print(f"\n{signal.market.slug}")
            print(f"  BTC: ${signal.btc_price:,.0f} ({signal.btc_change_24h:+.2f}%)")
            print(f"  Model UP: {signal.model_probability:.1%} vs Market UP: {signal.market_probability:.1%}")
            print(f"  Edge: {signal.edge:+.1%} -> {signal.direction.upper()}")
            print(f"  Size: ${signal.suggested_size:.2f}")

    asyncio.run(test())
