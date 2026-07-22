"""FastAPI backend for BTC 5-min trading bot dashboard."""
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio
import json
import os

from backend.config import settings
from backend.models.database import (
    get_db, init_db, SessionLocal,
    Signal, Trade, BotState, AILog, ScanLog, GridOrder, get_bot_state
)
from backend.core.signals import scan_for_signals, TradingSignal
from backend.data.btc_markets import fetch_active_btc_markets, BtcMarket
from backend.data.crypto import fetch_crypto_price, compute_btc_microstructure

from pydantic import BaseModel

app = FastAPI(
    title="BTC 5-Min Trading Bot",
    description="Polymarket BTC Up/Down 5-minute market trading bot",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


ws_manager = ConnectionManager()


# Pydantic response models
class BtcPriceResponse(BaseModel):
    price: float
    change_24h: float
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


class BtcWindowResponse(BaseModel):
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    is_active: bool
    is_upcoming: bool
    time_until_end: float
    spread: float


class MicrostructureResponse(BaseModel):
    rsi: float = 50.0
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    vwap_deviation: float = 0.0
    sma_crossover: float = 0.0
    volatility: float = 0.0
    price: float = 0.0
    source: str = "unknown"


class SignalResponse(BaseModel):
    market_ticker: str
    market_title: str
    platform: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    timestamp: datetime
    category: str = "crypto"
    event_slug: Optional[str] = None
    btc_price: float = 0.0
    btc_change_24h: float = 0.0
    window_end: Optional[datetime] = None
    actionable: bool = False


class GridOrderResponse(BaseModel):
    id: int
    trade_id: int
    level: int
    limit_price: float
    shares: float
    cost: float
    status: str
    filled_at: Optional[datetime] = None
    fill_price: Optional[float] = None


class TradeResponse(BaseModel):
    id: int
    market_ticker: str
    platform: str
    event_slug: Optional[str] = None
    direction: str
    entry_price: float
    size: float           # Dollar amount spent
    shares: float = 0.0   # Number of shares bought
    timestamp: datetime
    settled: bool
    result: str
    pnl: Optional[float]
    grid_total_budget: float = 0.0
    grid_filled_cost: float = 0.0
    grid_filled_shares: float = 0.0
    grid_orders: List[GridOrderResponse] = []
    stop_loss_price: Optional[float] = None
    stop_loss_filled: bool = False
    stop_loss_filled_at: Optional[datetime] = None
    is_live: bool = False  # False=sim, True=live


class BotStats(BaseModel):
    bankroll: float
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    is_running: bool
    last_run: Optional[datetime]
    is_live: bool = False  # False=sim, True=live


class CalibrationBucket(BaseModel):
    bucket: str
    predicted_avg: float
    actual_rate: float
    count: int


class CalibrationSummary(BaseModel):
    total_signals: int
    total_with_outcome: int
    accuracy: float
    avg_predicted_edge: float
    avg_actual_edge: float
    brier_score: float


class WeatherForecastResponse(BaseModel):
    city_key: str
    city_name: str
    target_date: str
    mean_high: float
    std_high: float
    mean_low: float
    std_low: float
    num_members: int
    ensemble_agreement: float


class WeatherMarketResponse(BaseModel):
    slug: str
    market_id: str
    platform: str = "polymarket"
    title: str
    city_key: str
    city_name: str
    target_date: str
    threshold_c: float
    metric: str
    direction: str
    yes_price: float
    no_price: float
    volume: float


class WeatherSignalResponse(BaseModel):
    market_id: str
    city_key: str
    city_name: str
    target_date: str
    threshold_c: float
    metric: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    ensemble_mean: float
    ensemble_std: float
    ensemble_members: int
    actionable: bool = False


class DashboardData(BaseModel):
    stats: BotStats
    live_stats: Optional[BotStats] = None
    live_enabled: bool = False
    btc_price: Optional[BtcPriceResponse]
    microstructure: Optional[MicrostructureResponse] = None
    windows: List[BtcWindowResponse]
    active_signals: List[SignalResponse]
    recent_trades: List[TradeResponse]
    equity_curve: List[dict]
    calibration: Optional[CalibrationSummary] = None
    weather_signals: List[WeatherSignalResponse] = []
    weather_forecasts: List[WeatherForecastResponse] = []


class EventResponse(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}


# Startup / Shutdown
@app.on_event("startup")
async def startup():
    print("=" * 60)
    print("BTC 5-MIN TRADING BOT v3.0")
    print("=" * 60)
    print("Initializing database...")

    init_db()

    db = SessionLocal()
    try:
        # Ensure both sim and live states exist
        sim_state = get_bot_state(db, is_live=False)
        live_state = get_bot_state(db, is_live=True)

        sim_state.is_running = True
        if settings.LIVE_TRADING_ENABLED:
            live_state.is_running = True
            # Sync live bankroll with actual USDC balance on startup
            try:
                from backend.data.polymarket_executor import get_executor
                executor = get_executor()
                if not executor.is_stub:
                    actual_balance = executor.get_usdc_balance()
                    live_state.bankroll = round(actual_balance, 2)
                    print(f"[LIVE] Bankroll synced to actual USDC: ${actual_balance:.2f}")
            except Exception as e:
                print(f"[LIVE] Failed to sync USDC balance: {e}")
        db.commit()
        print(f"[SIM] Bankroll ${sim_state.bankroll:,.2f}, P&L ${sim_state.total_pnl:+,.2f}, {sim_state.total_trades} trades")
        if settings.LIVE_TRADING_ENABLED:
            print(f"[LIVE] Bankroll ${live_state.bankroll:,.2f}, P&L ${live_state.total_pnl:+,.2f}, {live_state.total_trades} trades")
        else:
            print("[LIVE] Live trading DISABLED")
    finally:
        db.close()

    print("")
    print("Configuration:")
    print(f"  - Simulation mode: {settings.SIMULATION_MODE}")
    print(f"  - Live trading: {'ENABLED' if settings.LIVE_TRADING_ENABLED else 'DISABLED'}")
    print(f"  - Min edge threshold: {settings.MIN_EDGE_THRESHOLD:.0%}")
    print(f"  - Kelly fraction: {settings.KELLY_FRACTION:.0%}")
    print(f"  - Scan interval: {settings.SCAN_INTERVAL_SECONDS}s")
    print(f"  - Settlement interval: {settings.SETTLEMENT_INTERVAL_SECONDS}s")
    print("")

    from backend.core.scheduler import start_scheduler, log_event
    start_scheduler()
    log_event("success", "BTC 5-min trading bot initialized")

    print("Bot is now running!")
    print(f"  - BTC scan: every {settings.SCAN_INTERVAL_SECONDS}s (edge >= {settings.MIN_EDGE_THRESHOLD:.0%})")
    print(f"  - Settlement check: every {settings.SETTLEMENT_INTERVAL_SECONDS}s")
    if settings.WEATHER_ENABLED:
        print(f"  - Weather scan: every {settings.WEATHER_SCAN_INTERVAL_SECONDS}s (edge >= {settings.WEATHER_MIN_EDGE_THRESHOLD:.0%})")
        print(f"  - Weather cities: {settings.WEATHER_CITIES}")
    else:
        print("  - Weather trading: DISABLED")
    print("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    from backend.core.scheduler import stop_scheduler
    stop_scheduler()


# Core endpoints
@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get stats for both sim and live modes."""
    sim_state = get_bot_state(db, is_live=False)
    live_state = get_bot_state(db, is_live=True)

    sim_win_rate = sim_state.winning_trades / sim_state.total_trades if sim_state.total_trades > 0 else 0
    live_win_rate = live_state.winning_trades / live_state.total_trades if live_state.total_trades > 0 else 0

    return {
        "sim": BotStats(
            bankroll=sim_state.bankroll,
            total_trades=sim_state.total_trades,
            winning_trades=sim_state.winning_trades,
            win_rate=sim_win_rate,
            total_pnl=sim_state.total_pnl,
            is_running=sim_state.is_running,
            last_run=sim_state.last_run,
            is_live=False,
        ),
        "live": BotStats(
            bankroll=live_state.bankroll,
            total_trades=live_state.total_trades,
            winning_trades=live_state.winning_trades,
            win_rate=live_win_rate,
            total_pnl=live_state.total_pnl,
            is_running=live_state.is_running,
            last_run=live_state.last_run,
            is_live=True,
        ),
        "live_enabled": settings.LIVE_TRADING_ENABLED,
    }


# BTC-specific endpoints
@app.get("/api/btc/price", response_model=Optional[BtcPriceResponse])
async def get_btc_price():
    """Get current BTC price and momentum data."""
    try:
        btc = await fetch_crypto_price("BTC")
        if not btc:
            return None

        return BtcPriceResponse(
            price=btc.current_price,
            change_24h=btc.change_24h,
            change_7d=btc.change_7d,
            market_cap=btc.market_cap,
            volume_24h=btc.volume_24h,
            last_updated=btc.last_updated
        )
    except Exception:
        return None


@app.get("/api/btc/windows", response_model=List[BtcWindowResponse])
async def get_btc_windows():
    """Get upcoming BTC 5-min windows with prices."""
    try:
        markets = await fetch_active_btc_markets()
        return [
            BtcWindowResponse(
                slug=m.slug,
                market_id=m.market_id,
                up_price=m.up_price,
                down_price=m.down_price,
                window_start=m.window_start,
                window_end=m.window_end,
                volume=m.volume,
                is_active=m.is_active,
                is_upcoming=m.is_upcoming,
                time_until_end=m.time_until_end,
                spread=m.spread,
            )
            for m in markets
        ]
    except Exception:
        return []


@app.get("/api/signals", response_model=List[SignalResponse])
async def get_signals():
    """Get current BTC trading signals."""
    try:
        signals = await scan_for_signals()
        return [_signal_to_response(s) for s in signals]
    except Exception:
        return []


@app.get("/api/signals/actionable", response_model=List[SignalResponse])
async def get_actionable_signals():
    """Get only signals that pass the edge threshold."""
    try:
        signals = await scan_for_signals()
        actionable = [s for s in signals if s.passes_threshold]
        return [_signal_to_response(s) for s in actionable]
    except Exception:
        return []


def _signal_to_response(s: TradingSignal, actionable: bool = False) -> SignalResponse:
    return SignalResponse(
        market_ticker=s.market.market_id,
        market_title=f"BTC 5m - {s.market.slug}",
        platform="polymarket",
        direction=s.direction,
        model_probability=s.model_probability,
        market_probability=s.market_probability,
        edge=s.edge,
        confidence=s.confidence,
        suggested_size=s.suggested_size,
        reasoning=s.reasoning,
        timestamp=s.timestamp,
        category="crypto",
        event_slug=s.market.slug,
        btc_price=s.btc_price,
        btc_change_24h=s.btc_change_24h,
        window_end=s.market.window_end,
        actionable=actionable,
    )


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Trade)
    if status:
        query = query.filter(Trade.result == status)
    trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()

    return [
        TradeResponse(
            id=t.id,
            market_ticker=t.market_ticker,
            platform=t.platform,
            event_slug=t.event_slug,
            direction=t.direction,
            entry_price=t.entry_price,
            size=t.size,
            shares=getattr(t, 'shares', 0.0) or 0.0,
            timestamp=t.timestamp,
            settled=t.settled,
            result=t.result,
            pnl=t.pnl,
            grid_total_budget=t.grid_total_budget or 0.0,
            grid_filled_cost=t.grid_filled_cost or 0.0,
            grid_filled_shares=t.grid_filled_shares or 0.0,
            grid_orders=[
                GridOrderResponse(
                    id=g.id, trade_id=g.trade_id, level=g.level,
                    limit_price=g.limit_price, shares=g.shares, cost=g.cost,
                    status=g.status, filled_at=g.filled_at, fill_price=g.fill_price,
                )
                for g in (t.grid_orders if hasattr(t, 'grid_orders') else db.query(GridOrder).filter(GridOrder.trade_id == t.id).all())
            ],
            stop_loss_price=getattr(t, 'stop_loss_price', None),
            stop_loss_filled=getattr(t, 'stop_loss_filled', False),
            stop_loss_filled_at=getattr(t, 'stop_loss_filled_at', None),
            is_live=getattr(t, 'is_live', False),
        )
        for t in trades
    ]


@app.get("/api/equity-curve")
async def get_equity_curve(db: Session = Depends(get_db)):
    trades = db.query(Trade).filter(Trade.settled == True).order_by(Trade.timestamp).all()

    curve = []
    cumulative_pnl = 0
    bankroll = settings.INITIAL_BANKROLL

    for trade in trades:
        if trade.pnl is not None:
            cumulative_pnl += trade.pnl
            curve.append({
                "timestamp": trade.timestamp.isoformat(),
                "pnl": cumulative_pnl,
                "bankroll": bankroll + cumulative_pnl,
                "trade_id": trade.id
            })

    return curve


@app.get("/api/stop-loss-stats")
async def get_stop_loss_stats(db: Session = Depends(get_db)):
    """Stop-loss statistics: how many stop-losses triggered, direction correctness."""
    settled = db.query(Trade).filter(Trade.settled == True).all()

    total_settled = len(settled)
    stop_loss_trades = [t for t in settled if getattr(t, 'stop_loss_filled', False)]
    stop_loss_count = len(stop_loss_trades)

    # Among stop-loss trades, check if direction was correct (would have won)
    direction_correct = 0
    direction_wrong = 0
    for t in stop_loss_trades:
        if t.settlement_value is not None:
            mapped_dir = "up" if t.direction in ("up", "yes") else "down"
            actual = "up" if t.settlement_value == 1.0 else "down"
            if mapped_dir == actual:
                direction_correct += 1  # Would have won, stop-loss was unnecessary
            else:
                direction_wrong += 1    # Would have lost, stop-loss saved us

    # Trades where grid fully filled but stop-loss did NOT fill (held to settlement)
    grid_filled_no_stop = [
        t for t in settled
        if getattr(t, 'stop_loss_price', None) is not None
        and not getattr(t, 'stop_loss_filled', False)
    ]
    grid_filled_no_stop_count = len(grid_filled_no_stop)
    grid_filled_no_stop_loss = sum(1 for t in grid_filled_no_stop if t.result == "loss")

    return {
        "total_settled": total_settled,
        "stop_loss_count": stop_loss_count,
        "stop_loss_direction_correct": direction_correct,
        "stop_loss_direction_wrong": direction_wrong,
        "grid_filled_no_stop_count": grid_filled_no_stop_count,
        "grid_filled_no_stop_losses": grid_filled_no_stop_loss,
    }


@app.post("/api/simulate-trade")
async def simulate_trade(signal_ticker: str, db: Session = Depends(get_db)):
    from backend.core.scheduler import log_event

    signals = await scan_for_signals()
    signal = next((s for s in signals if s.market.market_id == signal_ticker), None)

    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    state = get_bot_state(db, is_live=False)

    entry_price = signal.market.up_price if signal.direction == "up" else signal.market.down_price

    trade = Trade(
        market_ticker=signal.market.market_id,
        platform="polymarket",
        event_slug=signal.market.slug,
        direction=signal.direction,
        entry_price=entry_price,
        size=min(signal.suggested_size, state.bankroll * 0.05),
        model_probability=signal.model_probability,
        market_price_at_entry=signal.market_probability,
        edge_at_entry=signal.edge
    )

    db.add(trade)
    state.total_trades += 1
    db.commit()

    log_event("trade", f"Manual BTC trade: {signal.direction.upper()} {signal.market.slug}")
    return {"status": "ok", "trade_id": trade.id, "size": trade.size}


@app.post("/api/run-scan")
async def run_scan(db: Session = Depends(get_db)):
    from backend.core.scheduler import run_manual_scan, log_event

    state = get_bot_state(db, is_live=False)
    if state:
        state.last_run = datetime.utcnow()
        db.commit()

    log_event("info", "Manual scan triggered (BTC + Weather)")
    await run_manual_scan()

    signals = await scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]

    result = {
        "status": "ok",
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Also run weather scan if enabled
    if settings.WEATHER_ENABLED:
        try:
            from backend.core.weather_signals import scan_for_weather_signals
            wx_signals = await scan_for_weather_signals()
            wx_actionable = [s for s in wx_signals if s.passes_threshold]
            result["weather_signals"] = len(wx_signals)
            result["weather_actionable"] = len(wx_actionable)
        except Exception:
            result["weather_signals"] = 0
            result["weather_actionable"] = 0

    return result


@app.post("/api/settle-trades")
async def settle_trades_endpoint(db: Session = Depends(get_db)):
    from backend.core.settlement import settle_pending_trades, update_bot_state_with_settlements
    from backend.core.scheduler import log_event

    log_event("info", "Manual settlement triggered")

    settled = await settle_pending_trades(db)
    await update_bot_state_with_settlements(db, settled)

    return {
        "status": "ok",
        "settled_count": len(settled),
        "trades": [{"id": t.id, "result": t.result, "pnl": t.pnl} for t in settled]
    }


def _compute_calibration_summary(db: Session) -> Optional[CalibrationSummary]:
    """Compute calibration summary from settled signals."""
    total_signals = db.query(Signal).count()
    settled_signals = db.query(Signal).filter(Signal.outcome_correct.isnot(None)).all()

    if not settled_signals:
        if total_signals == 0:
            return None
        return CalibrationSummary(
            total_signals=total_signals,
            total_with_outcome=0,
            accuracy=0.0,
            avg_predicted_edge=0.0,
            avg_actual_edge=0.0,
            brier_score=0.0,
        )

    total_with_outcome = len(settled_signals)
    correct = sum(1 for s in settled_signals if s.outcome_correct)
    accuracy = correct / total_with_outcome if total_with_outcome > 0 else 0.0

    avg_predicted_edge = sum(abs(s.edge) for s in settled_signals) / total_with_outcome
    # Actual edge: for correct predictions, edge was real; for incorrect, edge was negative
    avg_actual_edge = sum(
        abs(s.edge) if s.outcome_correct else -abs(s.edge)
        for s in settled_signals
    ) / total_with_outcome

    # Brier score: mean squared error of probability forecasts
    # For each signal: (predicted_prob - actual_outcome)^2
    brier_sum = 0.0
    for s in settled_signals:
        # Model probability is for UP; actual is 1.0 if UP won, 0.0 if DOWN won
        actual = s.settlement_value if s.settlement_value is not None else 0.5
        brier_sum += (s.model_probability - actual) ** 2
    brier_score = brier_sum / total_with_outcome

    return CalibrationSummary(
        total_signals=total_signals,
        total_with_outcome=total_with_outcome,
        accuracy=accuracy,
        avg_predicted_edge=avg_predicted_edge,
        avg_actual_edge=avg_actual_edge,
        brier_score=brier_score,
    )


@app.get("/api/calibration")
async def get_calibration(db: Session = Depends(get_db)):
    """Return calibration data: predicted probability vs actual win rate."""
    signals = db.query(Signal).filter(Signal.outcome_correct.isnot(None)).all()

    if not signals:
        return {"buckets": [], "summary": None}

    # Bucket signals by model_probability into 5% bins
    from collections import defaultdict
    buckets_data = defaultdict(lambda: {"predicted_sum": 0.0, "correct": 0, "total": 0})

    for s in signals:
        # Bin by 5% increments
        bin_start = int(s.model_probability * 100 // 5) * 5
        bin_end = bin_start + 5
        bucket_key = f"{bin_start}-{bin_end}%"

        buckets_data[bucket_key]["predicted_sum"] += s.model_probability
        buckets_data[bucket_key]["total"] += 1
        if s.outcome_correct:
            buckets_data[bucket_key]["correct"] += 1

    buckets = []
    for bucket_key in sorted(buckets_data.keys()):
        d = buckets_data[bucket_key]
        buckets.append(CalibrationBucket(
            bucket=bucket_key,
            predicted_avg=d["predicted_sum"] / d["total"],
            actual_rate=d["correct"] / d["total"],
            count=d["total"],
        ))

    summary = _compute_calibration_summary(db)

    return {"buckets": buckets, "summary": summary}


# Kalshi endpoints
@app.get("/api/kalshi/status")
async def get_kalshi_status():
    """Test Kalshi API authentication and return connection status."""
    from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present

    if not kalshi_credentials_present():
        return {
            "connected": False,
            "error": "Kalshi credentials not configured (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH)",
        }

    try:
        client = KalshiClient()
        balance_data = await client.get_balance()
        return {
            "connected": True,
            "balance": balance_data,
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }


# Weather endpoints
@app.get("/api/weather/forecasts", response_model=List[WeatherForecastResponse])
async def get_weather_forecasts():
    """Get ensemble forecasts for configured cities."""
    if not settings.WEATHER_ENABLED:
        return []

    try:
        from backend.data.weather import fetch_ensemble_forecast, CITY_CONFIG
        from datetime import date

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        forecasts = []

        for city_key in city_keys:
            if city_key not in CITY_CONFIG:
                continue
            forecast = await fetch_ensemble_forecast(city_key)
            if forecast:
                forecasts.append(WeatherForecastResponse(
                    city_key=forecast.city_key,
                    city_name=forecast.city_name,
                    target_date=forecast.target_date.isoformat(),
                    mean_high=forecast.mean_high,
                    std_high=forecast.std_high,
                    mean_low=forecast.mean_low,
                    std_low=forecast.std_low,
                    num_members=forecast.num_members,
                    ensemble_agreement=forecast.ensemble_agreement,
                ))

        return forecasts
    except Exception:
        return []


@app.get("/api/weather/markets", response_model=List[WeatherMarketResponse])
async def get_weather_markets():
    """Get active weather temperature markets."""
    if not settings.WEATHER_ENABLED:
        return []

    try:
        from backend.data.weather_markets import fetch_polymarket_weather_markets

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        markets = await fetch_polymarket_weather_markets(city_keys)

        # Also fetch Kalshi markets if enabled
        if settings.KALSHI_ENABLED:
            try:
                from backend.data.kalshi_client import kalshi_credentials_present
                from backend.data.kalshi_markets import fetch_kalshi_weather_markets
                if kalshi_credentials_present():
                    kalshi_markets = await fetch_kalshi_weather_markets(city_keys)
                    markets.extend(kalshi_markets)
            except Exception:
                pass

        return [
            WeatherMarketResponse(
                slug=m.slug,
                market_id=m.market_id,
                platform=m.platform,
                title=m.title,
                city_key=m.city_key,
                city_name=m.city_name,
                target_date=m.target_date.isoformat(),
                threshold_c=m.threshold_c,
                metric=m.metric,
                direction=m.direction,
                yes_price=m.yes_price,
                no_price=m.no_price,
                volume=m.volume,
            )
            for m in markets
        ]
    except Exception:
        return []


@app.get("/api/weather/signals", response_model=List[WeatherSignalResponse])
async def get_weather_signals():
    """Get current weather trading signals."""
    if not settings.WEATHER_ENABLED:
        return []

    try:
        from backend.core.weather_signals import scan_for_weather_signals

        signals = await scan_for_weather_signals()
        return [_weather_signal_to_response(s) for s in signals]
    except Exception:
        return []


def _weather_signal_to_response(s) -> WeatherSignalResponse:
    return WeatherSignalResponse(
        market_id=s.market.market_id,
        city_key=s.market.city_key,
        city_name=s.market.city_name,
        target_date=s.market.target_date.isoformat(),
        threshold_c=s.market.threshold_c,
        metric=s.market.metric,
        direction=s.direction,
        model_probability=s.model_probability,
        market_probability=s.market_probability,
        edge=s.edge,
        confidence=s.confidence,
        suggested_size=s.suggested_size,
        reasoning=s.reasoning,
        ensemble_mean=s.ensemble_mean,
        ensemble_std=s.ensemble_std,
        ensemble_members=s.ensemble_members,
        actionable=s.passes_threshold,
    )


@app.get("/api/events", response_model=List[EventResponse])
async def get_events(limit: int = 50):
    from backend.core.scheduler import get_recent_events
    events = get_recent_events(limit)
    return [
        EventResponse(
            timestamp=e["timestamp"],
            type=e["type"],
            message=e["message"],
            data=e.get("data", {})
        )
        for e in events
    ]


# Bot control
@app.post("/api/bot/start")
async def start_bot(db: Session = Depends(get_db)):
    from backend.core.scheduler import start_scheduler, log_event, is_scheduler_running

    sim_state = get_bot_state(db, is_live=False)
    sim_state.is_running = True
    db.commit()

    if not is_scheduler_running():
        start_scheduler()

    log_event("success", "Trading bot started")
    return {"status": "started", "is_running": True}


@app.post("/api/bot/stop")
async def stop_bot(db: Session = Depends(get_db)):
    from backend.core.scheduler import log_event

    sim_state = get_bot_state(db, is_live=False)
    sim_state.is_running = False
    db.commit()

    log_event("info", "Trading bot paused")
    return {"status": "stopped", "is_running": False}


@app.post("/api/live/toggle")
async def toggle_live_trading(db: Session = Depends(get_db)):
    """Toggle live trading on/off."""
    from backend.core.scheduler import log_event

    settings.LIVE_TRADING_ENABLED = not settings.LIVE_TRADING_ENABLED
    live_state = get_bot_state(db, is_live=True)
    live_state.is_running = settings.LIVE_TRADING_ENABLED

    # When enabling live trading, sync bankroll with actual USDC balance
    if settings.LIVE_TRADING_ENABLED:
        try:
            from backend.data.polymarket_executor import get_executor
            executor = get_executor()
            if not executor.is_stub:
                actual_balance = executor.get_usdc_balance()
                live_state.bankroll = round(actual_balance, 2)
                live_state.total_pnl = 0.0
                live_state.total_trades = 0
                live_state.winning_trades = 0
                log_event("success",
                    f"【实盘】Live trading ENABLED | USDC balance: ${actual_balance:.2f} | Bankroll synced")
            else:
                log_event("success", f"【实盘】Live trading ENABLED (stub mode)")
        except Exception as e:
            log_event("error", f"【实盘】Failed to sync USDC balance: {e}")
    else:
        log_event("info", f"【实盘】Live trading DISABLED")

    db.commit()
    return {"live_enabled": settings.LIVE_TRADING_ENABLED, "is_running": live_state.is_running, "bankroll": live_state.bankroll}


@app.get("/api/live/status")
async def get_live_status(db: Session = Depends(get_db)):
    """Get live trading status."""
    from backend.data.polymarket_executor import get_executor
    executor = get_executor()
    live_state = get_bot_state(db, is_live=True)
    return {
        "live_enabled": settings.LIVE_TRADING_ENABLED,
        "is_running": live_state.is_running,
        "executor_stub": executor.is_stub,
        "bankroll": live_state.bankroll,
        "total_trades": live_state.total_trades,
        "total_pnl": live_state.total_pnl,
    }


@app.post("/api/live/sync-balance")
async def sync_live_balance(db: Session = Depends(get_db)):
    """Sync live bankroll with actual USDC balance from Polymarket."""
    from backend.core.scheduler import log_event

    try:
        from backend.data.polymarket_executor import get_executor
        executor = get_executor()
        if executor.is_stub:
            return {"success": False, "message": "Executor is in stub mode"}

        actual_balance = executor.get_usdc_balance()
        live_state = get_bot_state(db, is_live=True)
        live_state.bankroll = round(actual_balance, 2)
        db.commit()

        log_event("success", f"【实盘】Bankroll synced to USDC: ${actual_balance:.2f}")
        return {"success": True, "bankroll": actual_balance}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/bot/reset")
async def reset_bot(db: Session = Depends(get_db)):
    from backend.core.scheduler import log_event

    try:
        trades_deleted = db.query(Trade).delete()
        # Reset sim state
        sim_state = get_bot_state(db, is_live=False)
        sim_state.bankroll = settings.INITIAL_BANKROLL
        sim_state.total_trades = 0
        sim_state.winning_trades = 0
        sim_state.total_pnl = 0.0
        sim_state.is_running = True
        # Reset live state
        live_state = get_bot_state(db, is_live=True)
        live_state.bankroll = settings.LIVE_BANKROLL
        live_state.total_trades = 0
        live_state.winning_trades = 0
        live_state.total_pnl = 0.0

        ai_logs_deleted = db.query(AILog).delete()
        db.commit()

        log_event("success", f"Bot reset: {trades_deleted} trades deleted. Fresh start with ${settings.INITIAL_BANKROLL:,.2f}")

        return {
            "status": "reset",
            "trades_deleted": trades_deleted,
            "ai_logs_deleted": ai_logs_deleted,
            "new_bankroll": settings.INITIAL_BANKROLL,
            "live_bankroll": settings.LIVE_BANKROLL,
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")


@app.get("/api/dashboard", response_model=DashboardData)
async def get_dashboard(db: Session = Depends(get_db)):
    """Get all dashboard data in one call."""
    import asyncio

    stats = await get_stats(db)

    # Extract sim and live stats from the stats response
    sim_stats = stats["sim"]
    live_stats = stats["live"]
    live_enabled = stats["live_enabled"]

    # Fetch microstructure, markets, and signals in parallel
    micro_task = asyncio.create_task(_safe_compute_microstructure())
    markets_task = asyncio.create_task(fetch_active_btc_markets())
    signals_task = asyncio.create_task(scan_for_signals())

    # DB queries can run while network calls are in flight
    trades = db.query(Trade).order_by(Trade.timestamp.desc()).limit(50).all()
    equity_trades = db.query(Trade).filter(
        Trade.settled == True,
        Trade.is_live == False
    ).order_by(Trade.timestamp).all()
    calibration = _compute_calibration_summary(db)

    # Await parallel results
    micro_data, btc_price_data, micro = await micro_task
    markets = await markets_task
    raw_signals = await signals_task

    # Build windows from fetched markets
    windows = [
        BtcWindowResponse(
            slug=m.slug,
            market_id=m.market_id,
            up_price=m.up_price,
            down_price=m.down_price,
            window_start=m.window_start,
            window_end=m.window_end,
            volume=m.volume,
            is_active=m.is_active,
            is_upcoming=m.is_upcoming,
            time_until_end=m.time_until_end,
            spread=m.spread,
        )
        for m in markets
    ]

    signals = [_signal_to_response(s, actionable=s.passes_threshold) for s in raw_signals]

    recent_trades = [
        TradeResponse(
            id=t.id,
            market_ticker=t.market_ticker,
            platform=t.platform,
            event_slug=t.event_slug,
            direction=t.direction,
            entry_price=t.entry_price,
            size=t.size,
            shares=getattr(t, 'shares', 0.0) or 0.0,
            timestamp=t.timestamp,
            settled=t.settled,
            result=t.result,
            pnl=t.pnl,
            is_live=getattr(t, 'is_live', False),
        )
        for t in trades
    ]

    # Equity curve
    equity_curve = []
    cumulative_pnl = 0
    for trade in equity_trades:
        if trade.pnl is not None:
            cumulative_pnl += trade.pnl
            equity_curve.append({
                "timestamp": trade.timestamp.isoformat(),
                "pnl": cumulative_pnl,
                "bankroll": settings.INITIAL_BANKROLL + cumulative_pnl
            })

    # Weather data (if enabled)
    weather_signals_data = []
    weather_forecasts_data = []
    if settings.WEATHER_ENABLED:
        try:
            from backend.core.weather_signals import scan_for_weather_signals
            from backend.data.weather import fetch_ensemble_forecast, CITY_CONFIG

            wx_signals = await scan_for_weather_signals()
            weather_signals_data = [_weather_signal_to_response(s) for s in wx_signals]

            city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
            forecast_tasks = [fetch_ensemble_forecast(k) for k in city_keys if k in CITY_CONFIG]
            forecast_results = await asyncio.gather(*forecast_tasks, return_exceptions=True)
            for forecast in forecast_results:
                if isinstance(forecast, Exception) or not forecast:
                    continue
                weather_forecasts_data.append(WeatherForecastResponse(
                    city_key=forecast.city_key,
                    city_name=forecast.city_name,
                    target_date=forecast.target_date.isoformat(),
                    mean_high=forecast.mean_high,
                    std_high=forecast.std_high,
                    mean_low=forecast.mean_low,
                    std_low=forecast.std_low,
                    num_members=forecast.num_members,
                    ensemble_agreement=forecast.ensemble_agreement,
                ))
        except Exception:
            pass

    return DashboardData(
        stats=sim_stats,
        live_stats=live_stats,
        live_enabled=live_enabled,
        btc_price=btc_price_data,
        microstructure=micro_data,
        windows=windows,
        active_signals=signals,
        recent_trades=recent_trades,
        equity_curve=equity_curve,
        calibration=calibration,
        weather_signals=weather_signals_data,
        weather_forecasts=weather_forecasts_data,
    )


async def _safe_compute_microstructure():
    """Helper: compute microstructure and return (micro_data, btc_price_data, micro)."""
    micro_data = None
    btc_price_data = None
    micro = None
    try:
        micro = await compute_btc_microstructure()
        if micro:
            micro_data = MicrostructureResponse(
                rsi=micro.rsi,
                momentum_1m=micro.momentum_1m,
                momentum_5m=micro.momentum_5m,
                momentum_15m=micro.momentum_15m,
                vwap_deviation=micro.vwap_deviation,
                sma_crossover=micro.sma_crossover,
                volatility=micro.volatility,
                price=micro.price,
                source=micro.source,
            )
            btc_price_data = BtcPriceResponse(
                price=micro.price,
                change_24h=micro.momentum_15m * 96,
                change_7d=0,
                market_cap=0,
                volume_24h=0,
                last_updated=datetime.utcnow(),
            )
    except Exception:
        pass
    if not btc_price_data:
        try:
            btc = await fetch_crypto_price("BTC")
            if btc:
                btc_price_data = BtcPriceResponse(
                    price=btc.current_price,
                    change_24h=btc.change_24h,
                    change_7d=btc.change_7d,
                    market_cap=btc.market_cap,
                    volume_24h=btc.volume_24h,
                    last_updated=btc.last_updated
                )
        except Exception:
            pass
    return micro_data, btc_price_data, micro


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await ws_manager.connect(websocket)

    try:
        await websocket.send_json({
            "timestamp": datetime.utcnow().isoformat(),
            "type": "success",
            "message": "Connected to BTC trading bot"
        })

        from backend.core.scheduler import get_recent_events
        for event in get_recent_events(20):
            await websocket.send_json(event)

        last_event_count = len(get_recent_events(200))
        while True:
            await asyncio.sleep(2)

            current_events = get_recent_events(200)
            if len(current_events) > last_event_count:
                new_events = current_events[last_event_count - len(current_events):]
                for event in new_events:
                    await websocket.send_json(event)
                last_event_count = len(current_events)

            await websocket.send_json({
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat()
            })

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# Serve frontend static files (built React app)
_frontend_dist = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "dist"
)
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
