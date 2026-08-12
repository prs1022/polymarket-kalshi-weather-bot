"""Background scheduler for BTC 5-min autonomous trading."""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
import logging

from backend.config import settings
from backend.models.database import SessionLocal, Trade, BotState, Signal, GridOrder, get_bot_state
from backend.core.signals import scan_for_signals
from backend.core.grid import generate_fibonacci_grid, check_grid_fills, update_trade_from_grid
from backend.data.polymarket_executor import get_executor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
# Silence noisy third-party loggers
for _name in ("httpx", "apscheduler", "uvicorn.access"):
    logging.getLogger(_name).setLevel(logging.WARNING)
logger = logging.getLogger("trading_bot")

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None

# Event log for terminal display (in-memory, last 200 events)
event_log: List[dict] = []
MAX_LOG_SIZE = 200


def log_event(event_type: str, message: str, data: dict = None):
    """Log an event for terminal display."""
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": event_type,
        "message": message,
        "data": data or {}
    }
    event_log.append(event)

    while len(event_log) > MAX_LOG_SIZE:
        event_log.pop(0)

    log_func = {
        "error": logger.error,
        "warning": logger.warning,
        "success": logger.info,
        "info": logger.info,
        "data": logger.debug,
        "trade": logger.info
    }.get(event_type, logger.info)

    log_func(f"[{event_type.upper()}] {message}")


def get_recent_events(limit: int = 50) -> List[dict]:
    """Get recent events for terminal display."""
    return event_log[-limit:]


async def check_grid_fills_job():
    """
    Check pending grid orders against current market prices.
    Fill any orders where the market price has dropped to or below the limit price.
    Update parent Trade's entry_price and size based on filled orders.

    Also handles stop-loss logic:
    - When all grid levels are filled, set stop_loss_price = avg entry price.
    - For trades with stop_loss_price set but not filled, check if market price
      has bounced back to or above stop_loss_price → mark as stop_loss_filled.

    Handles both sim (is_live=False) and live (is_live=True) trades:
    - Sim: check market price vs limit price
    - Live: query CLOB API for real order status
    """
    db = SessionLocal()
    try:
        # --- Clean up stale grid orders (trade already settled but order still pending) ---
        stale = db.query(GridOrder).join(Trade, GridOrder.trade_id == Trade.id).filter(
            GridOrder.status == "pending",
            Trade.settled == True,
        ).all()
        for go in stale:
            go.status = "cancelled"
            go.filled_at = datetime.utcnow()
        if stale:
            db.commit()
            logger.info(f"Cleaned up {len(stale)} stale grid orders (trade already settled)")

        # Find all pending grid orders
        pending = db.query(GridOrder).filter(GridOrder.status == "pending").all()

        # Also find trades with pending stop-loss (grid fully filled, stop-loss not yet filled)
        stop_loss_pending = db.query(Trade).filter(
            Trade.settled == False,
            Trade.stop_loss_price != None,
            Trade.stop_loss_filled == False,
        ).all()

        if not pending and not stop_loss_pending:
            return

        # Fetch current market prices
        from backend.data.btc_markets import fetch_active_btc_markets
        markets = await fetch_active_btc_markets()
        market_map = {m.slug: m for m in markets}

        total_filled = 0
        total_stop_loss = 0
        total_cancelled = 0

        # Separate sim and live pending orders by trade.is_live (not clob_order_id)
        # 因为 LIVE 买单失败时 clob_order_id=None，会被误分类为 SIM
        trade_ids = set(o.trade_id for o in pending)
        trade_map = {t.id: t for t in db.query(Trade).filter(Trade.id.in_(trade_ids)).all()}
        sim_pending = [o for o in pending if not trade_map.get(o.trade_id, Trade()).is_live]
        live_pending = [o for o in pending if trade_map.get(o.trade_id, Trade()).is_live]

        # --- Phase 1a: Check SIM grid order fills (market price vs limit) ---
        if sim_pending:
            trade_ids = set(o.trade_id for o in sim_pending)
            trades = db.query(Trade).filter(Trade.id.in_(trade_ids)).all()

            for trade in trades:
                market = market_map.get(trade.event_slug)
                if not market:
                    continue

                current_price = market.up_price if trade.direction == "up" else market.down_price

                trade_grid = [o for o in sim_pending if o.trade_id == trade.id]
                newly_filled = check_grid_fills(trade_grid, current_price)

                if newly_filled:
                    all_grid = db.query(GridOrder).filter(GridOrder.trade_id == trade.id).all()
                    update_trade_from_grid(trade, all_grid)
                    total_filled += len(newly_filled)

                    # 止损仅在全部网格层成交后挂出
                    # 策略：全部层成交 = 市场大幅反向，此时挂止损保护
                    #        只有部分层成交 = 市场小幅波动，持有等待结算
                    all_grid_filled = all(o.status == "filled" for o in all_grid)
                    if settings.PROGRESSIVE_STOP_LOSS and all_grid_filled:
                        if settings.L1_STOPLOSS_MODE:
                            # 止损网格模式：L0成交即设止损价=L1价位，等价格跌到则触发
                            # 不买入L1，只把L1价格作为止损触发线
                            stop_loss_trigger = settings.GRID_LOWER_BOUND
                            if trade.stop_loss_price is None:
                                trade.stop_loss_price = stop_loss_trigger
                                log_event("trade",
                                    f"【模拟】L0止损网格设置: {trade.event_slug} {trade.direction.upper()} "
                                    f"买入 {trade.grid_filled_shares:.0f} 股 @ {trade.entry_price:.3f} | "
                                    f"止损触发价 {stop_loss_trigger:.3f} (市场跌到此价即卖出)"
                                )
                        else:
                            # 加仓网格模式：93秒规则 + patience 机制
                            # 93秒规则：L1成交距收盘时间 ≤阈值 则不挂止损，等结算
                            # 尾盘临时下跌方向正确率高，止损反而砍掉盈利
                            try:
                                slug_ts = int(trade.event_slug.rsplit("-", 1)[-1])
                                settlement_ts = slug_ts + 300
                                secs_to_close = settlement_ts - int(datetime.utcnow().timestamp())
                            except Exception:
                                secs_to_close = 999  # 解析失败则默认挂止损
                            
                            if secs_to_close <= settings.STOP_LOSS_LATE_FILL_THRESHOLD:
                                log_event("trade",
                                    f"【模拟】L1尾盘成交不挂止损: {trade.event_slug} {trade.direction.upper()} "
                                    f"距收盘{secs_to_close}s ≤{settings.STOP_LOSS_LATE_FILL_THRESHOLD}s, 持有等结算"
                                )
                            else:
                                # 动态止损：从 BotState 读取 patience 值（美分）
                                live_state = get_bot_state(db, is_live=True)
                                patience = getattr(live_state, 'stop_loss_patience', None)
                                if patience is None:
                                    patience = settings.STOP_LOSS_PATIENCE_INITIAL
                                patience = max(settings.STOP_LOSS_PATIENCE_MIN, min(settings.STOP_LOSS_PATIENCE_MAX, patience))
                                stop_loss_offset = patience / 100.0
                                new_stop_loss = round(trade.entry_price + stop_loss_offset, 2)
                                old_stop_loss = trade.stop_loss_price
                                
                                # 更新止损价（如果新价格更优，即更高）
                                if old_stop_loss is None or new_stop_loss > old_stop_loss:
                                    trade.stop_loss_price = new_stop_loss
                                    
                                    if old_stop_loss is None:
                                        log_event("data",
                                            f"【模拟】全部网格成交 - 挂止损: {trade.event_slug} {trade.direction.upper()} "
                                            f"成本 {trade.entry_price:.3f} → 止损 {trade.stop_loss_price:.3f} "
                                            f"(+{patience}¢ patience, {secs_to_close}s to close)"
                                        )
                                    else:
                                        log_event("data",
                                            f"【模拟】止损更新: {trade.event_slug} {trade.direction.upper()} "
                                            f"成本 {trade.entry_price:.3f} → 止损 {old_stop_loss:.3f}→{trade.stop_loss_price:.3f}"
                                        )

                    log_event("data",
                        f"【模拟】Grid fill: {trade.event_slug} {trade.direction.upper()} "
                        f"{len(newly_filled)} orders filled @ {current_price:.0%} | "
                        f"avg entry {trade.entry_price:.3f}, {trade.grid_filled_shares:.0f} shares, ${trade.grid_filled_cost:.2f}"
                    )

        # --- Phase 1b: Check LIVE grid order fills (CLOB API trades) ---
        if live_pending:
            executor = get_executor()
            trade_ids = set(o.trade_id for o in live_pending)
            trades = db.query(Trade).filter(Trade.id.in_(trade_ids)).all()

            logger.debug(
                f"[LIVE-DEBUG] Phase 1b: 检查 {len(live_pending)} 个挂单, "
                f"涉及 {len(trades)} 笔交易, "
                f"executor_stub={executor.is_stub}, "
                f"trade_ids={list(trade_ids)}"
            )

            # Get recent trades (fills) from CLOB API
            # This is more reliable than checking each order individually
            recent_trades = executor.get_recent_trades(limit=200)
            
            # Build a map: order_id -> trade_info
            fills_map = {}
            for rt in recent_trades:
                order_id = rt.get("taker_order_id")
                if order_id and rt.get("status") == "TRADE_STATUS_CONFIRMED":
                    fills_map[order_id] = {
                        "price": float(rt.get("price", 0)),
                        "size": float(rt.get("size", 0)) / 1e6,  # Convert from token units
                        "match_time": rt.get("match_time"),
                    }

            for trade in trades:
                trade_grid = [o for o in live_pending if o.trade_id == trade.id]
                newly_resolved = []  # Orders that changed state (filled or cancelled)

                for go in trade_grid:
                    if not go.clob_order_id:
                        # LIVE 买单未成功下到 CLOB（余额不足等），标记为 cancelled
                        logger.warning(
                            f"[LIVE] 网格L{go.level}买单未成交(无CLOB订单): "
                            f"trade_id={trade.id}, slug={trade.event_slug}, "
                            f"limit={go.limit_price}, status={go.status}"
                        )
                        go.status = "cancelled"
                        go.filled_at = datetime.utcnow()
                        newly_resolved.append(go)
                    
                    # Check if this order appears in recent fills
                    fill_info = fills_map.get(go.clob_order_id)
                    if fill_info:
                        go.status = "filled"
                        go.fill_price = round(fill_info["price"], 2)
                        go.filled_at = datetime.utcnow()
                        newly_resolved.append(go)
                        logger.info(f"[LIVE] Order {go.clob_order_id[:16]}... filled @ ${go.fill_price:.3f}")
                    else:
                        # Fallback: try individual order status check
                        # (in case trade is too recent to appear in trades list)
                        status_info = executor.get_order_status(go.clob_order_id)
                        clob_status = status_info.get("status", "")
                        logger.debug(
                            f"[LIVE-DEBUG] 网格L{go.level}状态查询: "
                            f"trade_id={trade.id}, order={go.clob_order_id[:16]}..., "
                            f"limit={go.limit_price}, clob_status={clob_status}"
                        )
                        if clob_status.lower() in ("matched", "filled"):
                            go.status = "filled"
                            go.fill_price = round(status_info["filled_price"], 2) if status_info["filled_price"] else go.limit_price
                            go.filled_at = datetime.utcnow()
                            newly_resolved.append(go)
                        elif clob_status == "not_found":
                            # Order not found = market expired and Polymarket cancelled it
                            go.status = "cancelled"
                            go.filled_at = datetime.utcnow()
                            newly_resolved.append(go)
                            logger.warning(
                                f"[LIVE] Order {go.clob_order_id[:16]}... not found → marked cancelled "
                                f"(market likely expired), trade_id={trade.id}, L{go.level}"
                            )

                if newly_resolved:
                    all_grid = db.query(GridOrder).filter(GridOrder.trade_id == trade.id).all()
                    update_trade_from_grid(trade, all_grid)
                    filled_count = len([o for o in newly_resolved if o.status == "filled"])
                    cancelled_count = len([o for o in newly_resolved if o.status == "cancelled"])
                    total_filled += filled_count
                    total_cancelled += cancelled_count

                    # 止损触发条件：全部网格层都 filled（L0+L1都成交）
                    # 策略逻辑：
                    # - 只有 L0 成交 = 模型方向正确，安静等盘尾结算
                    # - L0+L1 都成交 = 模型方向错误，市场大幅反向，挂保本止损单退出
                    # - L0 成交 + L1 cancelled（市场到期未成交）= 不需要止损，等结算
                    all_grid_filled = all(o.status == "filled" for o in all_grid)
                    grid_statuses = [(o.level, o.status) for o in all_grid]
                    logger.info(
                        f"[LIVE-DEBUG] 网格成交检查: trade_id={trade.id}, "
                        f"slug={trade.event_slug}, "
                        f"all_filled={all_grid_filled}, "
                        f"grid_statuses={grid_statuses}, "
                        f"filled_shares={trade.grid_filled_shares}, "
                        f"filled_cost=${trade.grid_filled_cost:.2f}"
                    )
                    if settings.PROGRESSIVE_STOP_LOSS and all_grid_filled:
                        if settings.L1_STOPLOSS_MODE:
                            # 止损网格模式：L0成交即设止损触发价=L1价位
                            # 不买入L1，只把L1价格作为止损触发线
                            # Phase 2 会监控市场价格，跌到触发价则卖出
                            stop_loss_trigger = settings.GRID_LOWER_BOUND
                            if trade.stop_loss_price is None:
                                trade.stop_loss_price = stop_loss_trigger
                                logger.info(
                                    f"[LIVE-DEBUG] L0止损网格设置: "
                                    f"trade_id={trade.id}, slug={trade.event_slug}, "
                                    f"stop_loss_trigger={stop_loss_trigger:.3f}, "
                                    f"shares={trade.grid_filled_shares}, "
                                    f"token_id={'OK' if trade.token_id else 'MISSING'}"
                                )
                                log_event("trade",
                                    f"【实盘】L0止损网格设置: {trade.event_slug} {trade.direction.upper()} "
                                    f"买入 {trade.grid_filled_shares:.0f} 股 @ {trade.entry_price:.3f} | "
                                    f"止损触发价 {stop_loss_trigger:.3f} (市场跌到此价则卖出)"
                                )
                        else:
                            # 加仓网格模式：93秒规则 + patience 机制
                            # 93秒规则：L1成交距收盘时间 ≤阈值 则不挂止损，等结算
                            # 尾盘临时下跌方向正确率高，止损反而砍掉盈利
                            try:
                                slug_ts = int(trade.event_slug.rsplit("-", 1)[-1])
                                settlement_ts = slug_ts + 300
                                secs_to_close = settlement_ts - int(datetime.utcnow().timestamp())
                            except Exception:
                                secs_to_close = 999  # 解析失败则默认挂止损
                            
                            if secs_to_close <= settings.STOP_LOSS_LATE_FILL_THRESHOLD:
                                log_event("trade",
                                    f"【实盘】L1尾盘成交不挂止损: {trade.event_slug} {trade.direction.upper()} "
                                    f"距收盘{secs_to_close}s ≤{settings.STOP_LOSS_LATE_FILL_THRESHOLD}s, 持有等结算"
                                )
                            else:
                                # 动态止损：从 BotState 读取 patience 值（美分）
                                live_state = get_bot_state(db, is_live=True)
                                patience = getattr(live_state, 'stop_loss_patience', None)
                                if patience is None:
                                    patience = settings.STOP_LOSS_PATIENCE_INITIAL
                                patience = max(settings.STOP_LOSS_PATIENCE_MIN, min(settings.STOP_LOSS_PATIENCE_MAX, patience))
                                stop_loss_offset = patience / 100.0
                                new_stop_loss = round(trade.entry_price + stop_loss_offset, 2)
                                old_stop_loss = trade.stop_loss_price
                                
                                # 更新止损价（如果新价格更优，即更高）
                                if old_stop_loss is None or new_stop_loss > old_stop_loss:
                                    trade.stop_loss_price = new_stop_loss
                                    
                                    # For live trades, place or update real sell order
                                    logger.info(
                                        f"[LIVE-DEBUG] 准备挂止损卖单: "
                                        f"trade_id={trade.id}, slug={trade.event_slug}, "
                                        f"executor_stub={executor.is_stub}, "
                                        f"token_id={'OK' if trade.token_id else 'MISSING'}, "
                                        f"stop_loss_price={trade.stop_loss_price:.3f} "
                                        f"(avg={trade.entry_price:.3f}+{patience}¢ patience, {secs_to_close}s to close), "
                                        f"shares={trade.grid_filled_shares}"
                                    )
                                    if not executor.is_stub:
                                        # Use stored token_id (persisted at trade creation)
                                        sell_token_id = trade.token_id
                                        
                                        if sell_token_id:
                                            # Cancel old sell order if exists
                                            if trade.stop_loss_order_id:
                                                executor.cancel_order(trade.stop_loss_order_id)
                                                
                                            # Place new sell order at updated stop-loss price
                                            sell_order_id = executor.place_limit_sell(
                                                token_id=sell_token_id,
                                                price=trade.stop_loss_price,
                                                shares=trade.grid_filled_shares,
                                            )
                                            logger.info(
                                                f"[LIVE-DEBUG] 止损卖单结果: "
                                                f"trade_id={trade.id}, "
                                                f"sell_order_id={sell_order_id or 'FAILED'}, "
                                                f"price={trade.stop_loss_price:.3f}, "
                                                f"shares={trade.grid_filled_shares}"
                                            )
                                            if sell_order_id:
                                                trade.stop_loss_order_id = sell_order_id
                                                
                                            if old_stop_loss is None:
                                                log_event("trade",
                                                    f"【实盘】全部网格成交 - 挂止损: {trade.event_slug} "
                                                    f"sell {trade.grid_filled_shares:.0f} @ {trade.stop_loss_price:.3f} "
                                                    f"order={sell_order_id[:16] if sell_order_id else 'N/A'}..."
                                                )
                                            else:
                                                log_event("trade",
                                                    f"【实盘】止损更新: {trade.event_slug} "
                                                    f"{old_stop_loss:.3f}→{trade.stop_loss_price:.3f} "
                                                    f"order={sell_order_id[:16] if sell_order_id else 'N/A'}..."
                                                )
                                        else:
                                            log_event("warning",
                                                f"【实盘】止损单未挂出: trade无token_id for {trade.event_slug}"
                                            )
                                    else:
                                        log_event("data",
                                            f"【实盘-STUB】全部网格成交止损: {trade.event_slug} "
                                            f"成本 {trade.entry_price:.3f} → 止损 {trade.stop_loss_price:.3f}"
                                        )

                    log_event("data",
                        f"【实盘】Grid update: {trade.event_slug} {trade.direction.upper()} "
                        f"{filled_count} filled, {len(newly_resolved) - filled_count} cancelled | "
                        f"avg entry {trade.entry_price:.3f}, {trade.grid_filled_shares:.0f} shares, ${trade.grid_filled_cost:.2f}"
                    )

        # --- Phase 2: Check stop-loss fills ---
        # 加仓网格模式: sim=价格涨回止损价则成交, live=CLOB卖单状态查询
        # 止损网格模式: sim=价格跌到止损价则成交, live=价格跌到止损价则挂卖单
        executor = get_executor()
        for trade in stop_loss_pending:
            market = market_map.get(trade.event_slug)
            if not market:
                # For LIVE trades without market data, fall back to CLOB status check
                if trade.is_live and trade.stop_loss_order_id:
                    status_info = executor.get_order_status(trade.stop_loss_order_id)
                    if status_info["status"].lower() in ("matched", "filled"):
                        trade.stop_loss_filled = True
                        trade.stop_loss_filled_at = datetime.utcnow()
                        total_stop_loss += 1
                        log_event("trade",
                            f"【实盘】Stop-loss FILLED: {trade.event_slug} {trade.direction.upper()} "
                            f"sell @ {trade.stop_loss_price:.3f} | "
                            f"{trade.grid_filled_shares:.0f} shares"
                        )
                continue

            current_price = market.up_price if trade.direction == "up" else market.down_price

            if settings.L1_STOPLOSS_MODE:
                # 止损网格模式：价格跌到止损价 → 触发市价卖出
                # 挂 $0.01 市价卖单，确保以最优买单价立即成交
                if current_price <= trade.stop_loss_price:
                    if trade.is_live:
                        # LIVE：挂市价卖单（如果还没挂或上次挂失败）
                        if not trade.stop_loss_order_id and not executor.is_stub and trade.token_id:
                            # 市价卖出：挂 $0.01，会以最优买单价成交
                            market_sell_price = 0.01
                            sell_order_id = executor.place_limit_sell(
                                token_id=trade.token_id,
                                price=market_sell_price,
                                shares=trade.grid_filled_shares,
                            )
                            if sell_order_id:
                                trade.stop_loss_order_id = sell_order_id
                            # 挂单后不立即标记成交，等下个 tick 确认
                            log_event("trade",
                                f"【实盘】L0止损触发-市价卖出: {trade.event_slug} {trade.direction.upper()} "
                                f"市场价 {current_price:.3f} ≤ 触发价 {trade.stop_loss_price:.3f} | "
                                f"sell {trade.grid_filled_shares:.0f} @ market (挂$0.01) "
                                f"order={sell_order_id[:16] if sell_order_id else 'N/A'}..."
                            )
                        elif trade.stop_loss_order_id:
                            # 已挂卖单，检查状态
                            status_info = executor.get_order_status(trade.stop_loss_order_id)
                            actual_fill_price = None
                            if status_info["status"].lower() in ("matched", "filled"):
                                # 市价卖单挂$0.01，order.price=$0.01 不是真实成交价
                                # 必须从 trades 接口拿真实成交价
                                try:
                                    recent_trades = executor.get_recent_trades(limit=50)
                                    for rt in recent_trades:
                                        if rt.get("taker_order_id") == trade.stop_loss_order_id:
                                            rt_price = float(rt.get("price", 0))
                                            if rt_price > 0:
                                                actual_fill_price = rt_price
                                            break
                                except Exception:
                                    pass
                                # 回退：如果 trades 接口没找到，用当前市场价估算
                                if actual_fill_price is None:
                                    actual_fill_price = current_price
                                    log_event("warning", f"止损成交价未找到，用市场价估算: {current_price:.3f}")
                                trade.stop_loss_filled = True
                                trade.stop_loss_filled_at = datetime.utcnow()
                                trade.stop_loss_price = actual_fill_price
                                total_stop_loss += 1
                                log_event("trade",
                                    f"【实盘】L0止损 FILLED: {trade.event_slug} {trade.direction.upper()} "
                                    f"sell @ {actual_fill_price:.3f} | "
                                    f"{trade.grid_filled_shares:.0f} shares, P&L ${actual_fill_price * trade.grid_filled_shares - trade.grid_filled_cost:+.2f}"
                                )
                            elif status_info["status"].lower() == "not_found":
                                # 订单可能已过期但已成交，查 trades 接口
                                try:
                                    recent_trades = executor.get_recent_trades(limit=50)
                                    for rt in recent_trades:
                                        if rt.get("taker_order_id") == trade.stop_loss_order_id:
                                            rt_price = float(rt.get("price", 0))
                                            actual_fill_price = rt_price if rt_price > 0 else current_price
                                            trade.stop_loss_filled = True
                                            trade.stop_loss_filled_at = datetime.utcnow()
                                            trade.stop_loss_price = actual_fill_price
                                            total_stop_loss += 1
                                            log_event("trade",
                                                f"【实盘】L0止损 FILLED (via trades): {trade.event_slug} {trade.direction.upper()} "
                                                f"sell @ {actual_fill_price:.3f} | "
                                                f"{trade.grid_filled_shares:.0f} shares, P&L ${actual_fill_price * trade.grid_filled_shares - trade.grid_filled_cost:+.2f}"
                                            )
                                            break
                                except Exception:
                                    pass
                        elif executor.is_stub or not trade.token_id:
                            # STUB模式：直接标记成交
                            trade.stop_loss_filled = True
                            trade.stop_loss_filled_at = datetime.utcnow()
                            total_stop_loss += 1
                            log_event("trade",
                                f"【实盘-STUB】L0止损 FILLED: {trade.event_slug} {trade.direction.upper()} "
                                f"sell @ {trade.stop_loss_price:.3f} (market {current_price:.3f})"
                            )
                    else:
                        # SIM：直接标记成交
                        trade.stop_loss_filled = True
                        trade.stop_loss_filled_at = datetime.utcnow()
                        total_stop_loss += 1
                        log_event("trade",
                            f"【模拟】L0止损 FILLED: {trade.event_slug} {trade.direction.upper()} "
                            f"sell @ {trade.stop_loss_price:.3f} (market {current_price:.3f}) | "
                            f"{trade.grid_filled_shares:.0f} shares, P&L ${trade.stop_loss_price * trade.grid_filled_shares - trade.grid_filled_cost:+.2f}"
                        )
            else:
                # 加仓网格模式：价格涨回止损价 → 止损成交
                if trade.is_live:
                    # LIVE：检查 CLOB 卖单状态
                    if not trade.stop_loss_order_id:
                        continue
                    status_info = executor.get_order_status(trade.stop_loss_order_id)
                    if status_info["status"].lower() in ("matched", "filled"):
                        trade.stop_loss_filled = True
                        trade.stop_loss_filled_at = datetime.utcnow()
                        total_stop_loss += 1
                        log_event("trade",
                            f"【实盘】Stop-loss FILLED: {trade.event_slug} {trade.direction.upper()} "
                            f"sell @ {trade.stop_loss_price:.3f} | "
                            f"{trade.grid_filled_shares:.0f} shares"
                        )
                    elif status_info["status"] == "not_found":
                        recent_trades = executor.get_recent_trades(limit=50)
                        for rt in recent_trades:
                            if rt.get("taker_order_id") == trade.stop_loss_order_id:
                                trade.stop_loss_filled = True
                                trade.stop_loss_filled_at = datetime.utcnow()
                                total_stop_loss += 1
                                log_event("trade",
                                    f"【实盘】Stop-loss FILLED (via trades): {trade.event_slug} "
                                    f"sell @ {trade.stop_loss_price:.3f} | "
                                    f"{trade.grid_filled_shares:.0f} shares"
                                )
                                break
                else:
                    # SIM：价格涨回止损价则成交
                    if current_price >= trade.stop_loss_price:
                        trade.stop_loss_filled = True
                        trade.stop_loss_filled_at = datetime.utcnow()
                        total_stop_loss += 1
                        log_event("trade",
                            f"【模拟】Stop-loss FILLED: {trade.event_slug} {trade.direction.upper()} "
                            f"sell @ {trade.stop_loss_price:.3f} (market {current_price:.3f}) | "
                            f"{trade.grid_filled_shares:.0f} shares"
                        )

        # 始終提交：即使止損賣單只是掛出未成交，也需要保存 order_id
        db.commit()
        if total_filled > 0:
            logger.info(f"Grid fills: {total_filled} orders filled")
        if total_cancelled > 0:
            logger.info(f"Grid cancelled: {total_cancelled} orders expired (market closed)")
        if total_stop_loss > 0:
            logger.info(f"Stop-loss fills: {total_stop_loss} trades exited")

    except Exception as e:
        logger.warning(f"Grid fill check error: {e}")
    finally:
        db.close()


async def scan_and_trade_job():
    """
    Background job: Scan BTC 5-min markets, generate signals, execute trades.
    Runs every minute.
    Also checks pending grid orders for fills on each scan.
    """
    logger.debug("Scanning BTC 5-min markets...")

    try:
        # --- Check pending grid orders for fills ---
        await check_grid_fills_job()

        signals = await scan_for_signals()
        actionable = [s for s in signals if s.passes_threshold]

        log_event("data", f"Found {len(signals)} signals, {len(actionable)} actionable", {
            "total_signals": len(signals),
            "actionable": len(actionable),
        })

        if not actionable:
            logger.debug("No actionable BTC signals")
            return

        db = SessionLocal()
        try:
            sim_state = get_bot_state(db, is_live=False)
            live_state = get_bot_state(db, is_live=True) if settings.LIVE_TRADING_ENABLED else None

            if not sim_state.is_running:
                logger.debug("Bot is paused, skipping trades")
                return

            MAX_TRADES_PER_SCAN = 2
            MIN_TRADE_SIZE = 1  # Lowered from 10 to support small bankrolls ($10-20)
            MAX_TRADE_FRACTION = 0.15  # Increased from 3% to 15% per trade (was too conservative)
            MAX_TOTAL_PENDING = min(settings.MAX_TOTAL_PENDING_TRADES, 5)  # Cap at 5 for small bankrolls

            # --- Daily loss circuit breaker (sim) ---
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            settled_pnl = db.query(func.coalesce(func.sum(Trade.pnl), 0.0)).filter(
                Trade.settled == True,
                Trade.is_live == False,
                Trade.settlement_time >= today_start
            ).scalar()
            # 未结算交易的最大潜在亏损（假设全部输掉）
            pending_at_risk = db.query(func.coalesce(func.sum(Trade.grid_filled_cost), 0.0)).filter(
                Trade.settled == False,
                Trade.is_live == False,
                Trade.timestamp >= today_start
            ).scalar()
            effective_pnl = settled_pnl - pending_at_risk

            if effective_pnl <= -settings.DAILY_LOSS_LIMIT:
                log_event("warning", f"SIM daily loss limit: settled=${settled_pnl:.2f}, pending_at_risk=${pending_at_risk:.2f}, effective=${effective_pnl:.2f} (limit: -${settings.DAILY_LOSS_LIMIT:.0f}). Stopping trades.")
                return

            # Count pending sim trades
            total_pending = db.query(Trade).filter(
                Trade.settled == False,
                Trade.is_live == False
            ).count()
            if total_pending >= MAX_TOTAL_PENDING:
                logger.debug(f"Max pending trades reached ({total_pending}/{MAX_TOTAL_PENDING})")
                return

            trades_executed = 0
            for signal in actionable[:MAX_TRADES_PER_SCAN]:
                # Check if we already have a SIM trade for this market window
                existing_sim = db.query(Trade).filter(
                    Trade.event_slug == signal.market.slug,
                    Trade.settled == False,
                    Trade.is_live == False
                ).first()

                if existing_sim:
                    continue

                trade_size = min(signal.suggested_size, sim_state.bankroll * MAX_TRADE_FRACTION)
                trade_size = max(trade_size, MIN_TRADE_SIZE)

                if sim_state.bankroll < MIN_TRADE_SIZE:
                    log_event("warning", f"Bankroll too low: ${sim_state.bankroll:.2f}")
                    break

                if trades_executed >= MAX_TRADES_PER_SCAN:
                    break

                # Map up/down to yes/no for storage
                entry_price = round(signal.market.up_price if signal.direction == "up" else signal.market.down_price, 2)

                # --- Fibonacci grid execution ---
                grid_levels = generate_fibonacci_grid(
                    current_price=entry_price,
                    budget=trade_size,
                )

                # --- Create SIM trade ---
                sim_trade = Trade(
                    market_ticker=signal.market.market_id,
                    platform="polymarket",
                    event_slug=signal.market.slug,
                    direction=signal.direction,
                    entry_price=entry_price,
                    size=round(trade_size, 2),
                    shares=round(trade_size / entry_price, 2) if entry_price > 0 else 0,
                    model_probability=signal.model_probability,
                    market_price_at_entry=signal.market_probability,
                    edge_at_entry=signal.edge,
                    grid_total_budget=round(trade_size, 2),
                    grid_filled_cost=0.0,
                    grid_filled_shares=0.0,
                    is_live=False,
                )

                db.add(sim_trade)
                db.flush()

                # Create grid orders for sim (L1_STOPLOSS_MODE: only L0, skip L1 buy)
                for gl in grid_levels:
                    if settings.L1_STOPLOSS_MODE and gl.level >= 1:
                        continue  # 止损网格模式：不创建L1买单
                    go = GridOrder(
                        trade_id=sim_trade.id,
                        level=gl.level,
                        limit_price=gl.limit_price,
                        shares=gl.shares,
                        cost=gl.cost,
                        status="pending",
                    )
                    db.add(go)

                # Immediately fill orders at or above current market price (sim only)
                db.flush()
                grid_orders = db.query(GridOrder).filter(GridOrder.trade_id == sim_trade.id).all()
                newly_filled = check_grid_fills(grid_orders, entry_price)
                if newly_filled:
                    update_trade_from_grid(sim_trade, grid_orders)

                # Link trade to the most recent matching Signal
                matching_signal = db.query(Signal).filter(
                    Signal.market_ticker == signal.market.market_id,
                    Signal.executed == False,
                ).order_by(Signal.timestamp.desc()).first()
                if matching_signal:
                    matching_signal.executed = True
                    sim_trade.signal_id = matching_signal.id

                sim_state.total_trades += 1
                trades_executed += 1

                log_event("trade",
                    f"【模拟】BTC {signal.direction.upper()} grid ${trade_size:.0f} | "
                    f"{len(grid_levels)} levels @ {entry_price:.0%}→{grid_levels[-1].limit_price:.0%} | {signal.market.slug}",
                    {
                        "slug": signal.market.slug,
                        "direction": signal.direction,
                        "size": trade_size,
                        "edge": signal.edge,
                        "entry_price": entry_price,
                        "btc_price": signal.btc_price,
                        "grid_levels": len(grid_levels),
                        "grid_avg_price": sum(l.cost for l in grid_levels) / sum(l.shares for l in grid_levels) if grid_levels else 0,
                    }
                )

                # --- Create LIVE trade (if enabled) ---
                if settings.LIVE_TRADING_ENABLED and live_state and live_state.is_running:
                    # --- LIVE Daily loss circuit breaker ---
                    live_settled_pnl = db.query(func.coalesce(func.sum(Trade.pnl), 0.0)).filter(
                        Trade.settled == True,
                        Trade.is_live == True,
                        Trade.settlement_time >= today_start
                    ).scalar()
                    live_pending_at_risk = db.query(func.coalesce(func.sum(Trade.grid_filled_cost), 0.0)).filter(
                        Trade.settled == False,
                        Trade.is_live == True,
                        Trade.timestamp >= today_start
                    ).scalar()
                    live_effective_pnl = live_settled_pnl - live_pending_at_risk

                    if live_effective_pnl <= -settings.DAILY_LOSS_LIMIT:
                        log_event("warning", f"LIVE daily loss limit: settled=${live_settled_pnl:.2f}, pending_at_risk=${live_pending_at_risk:.2f}, effective=${live_effective_pnl:.2f} (limit: -${settings.DAILY_LOSS_LIMIT:.0f}). Skipping LIVE trade.")
                    else:
                        # Check if we already have a LIVE trade for this market
                        existing_live = db.query(Trade).filter(
                            Trade.event_slug == signal.market.slug,
                            Trade.settled == False,
                            Trade.is_live == True
                        ).first()

                        if not existing_live:
                            # Resolve token_id before creating trade (needed for buy orders and sell orders)
                            executor = get_executor()
                            token_id = signal.market.up_token_id if signal.direction == "up" else signal.market.down_token_id

                            logger.info(
                                f"[LIVE-DEBUG] 创建实盘交易: "
                                f"slug={signal.market.slug}, dir={signal.direction}, "
                                f"executor_stub={executor.is_stub}, "
                                f"token_id={'OK' if token_id else 'MISSING'}, "
                                f"entry={entry_price:.3f}, trade_size=${trade_size:.2f}"
                            )

                            live_trade = Trade(
                                market_ticker=signal.market.market_id,
                                platform="polymarket",
                                event_slug=signal.market.slug,
                                direction=signal.direction,
                                entry_price=entry_price,
                                size=round(trade_size, 2),
                                shares=round(trade_size / entry_price, 2) if entry_price > 0 else 0,
                                model_probability=signal.model_probability,
                                market_price_at_entry=signal.market_probability,
                                edge_at_entry=signal.edge,
                                grid_total_budget=round(trade_size, 2),
                                grid_filled_cost=0.0,
                                grid_filled_shares=0.0,
                                is_live=True,
                                token_id=token_id,
                            )
                            db.add(live_trade)
                            db.flush()

                            # Create grid orders with real CLOB orders (L1_STOPLOSS_MODE: only L0, skip L1 buy)

                            for gl in grid_levels:
                                if settings.L1_STOPLOSS_MODE and gl.level >= 1:
                                    continue  # 止损网格模式：不创建L1买单
                                clob_order_id = None
                                if token_id:
                                    clob_order_id = executor.place_limit_buy(
                                        token_id=token_id,
                                        price=gl.limit_price,
                                        size=gl.cost,
                                    )
                                else:
                                    logger.warning(
                                        f"[LIVE-DEBUG] 网格买单跳过: token_id为空! "
                                        f"slug={signal.market.slug}, L{gl.level} @ {gl.limit_price}"
                                    )
                                logger.info(
                                    f"[LIVE-DEBUG] 网格L{gl.level}买单: "
                                    f"limit={gl.limit_price:.3f}, shares={gl.shares}, cost=${gl.cost:.2f}, "
                                    f"clob_order_id={clob_order_id or 'NONE'}"
                                )
                                go = GridOrder(
                                    trade_id=live_trade.id,
                                    level=gl.level,
                                    limit_price=gl.limit_price,
                                    shares=gl.shares,
                                    cost=gl.cost,
                                    status="pending",
                                    clob_order_id=clob_order_id,
                                )
                                db.add(go)

                            live_state.total_trades += 1
                            log_event("trade",
                                f"【实盘】BTC {signal.direction.upper()} grid ${trade_size:.0f} | "
                                f"{len(grid_levels)} levels @ {entry_price:.0%}→{grid_levels[-1].limit_price:.0%} | {signal.market.slug}"
                            )

            sim_state.last_run = datetime.utcnow()
            if live_state:
                live_state.last_run = datetime.utcnow()
            db.commit()

            if trades_executed > 0:
                log_event("success", f"Executed {trades_executed} BTC trade(s)")
            else:
                logger.debug("No new trades executed")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Scan error: {str(e)}")
        logger.exception("Error in scan_and_trade_job")


async def weather_scan_and_trade_job():
    """
    Background job: Scan weather temperature markets, generate signals, execute trades.
    Runs every 5 minutes when WEATHER_ENABLED.
    """
    logger.debug("Scanning weather temperature markets...")

    try:
        from backend.core.weather_signals import scan_for_weather_signals

        signals = await scan_for_weather_signals()
        actionable = [s for s in signals if s.passes_threshold]

        logger.debug(f"Weather: {len(signals)} signals, {len(actionable)} actionable")

        if not actionable:
            logger.debug("No actionable weather signals")
            return

        db = SessionLocal()
        try:
            state = get_bot_state(db, is_live=False)

            if not state.is_running:
                logger.debug("Bot is paused, skipping weather trades")
                return

            MAX_TRADES_PER_SCAN = 3
            MIN_TRADE_SIZE = 10
            MAX_WEATHER_ALLOCATION = 500.0  # Max total exposure to weather markets

            # Check weather allocation limit (sim only)
            weather_pending = db.query(func.coalesce(func.sum(Trade.size), 0.0)).filter(
                Trade.settled == False,
                Trade.market_type == "weather",
                Trade.is_live == False,
            ).scalar()

            if weather_pending >= MAX_WEATHER_ALLOCATION:
                logger.info(f"Weather allocation limit reached: ${weather_pending:.0f}/${MAX_WEATHER_ALLOCATION:.0f}")
                return

            trades_executed = 0
            for signal in actionable[:MAX_TRADES_PER_SCAN]:
                # Check if we already have a trade for this market (sim only)
                existing = db.query(Trade).filter(
                    Trade.market_ticker == signal.market.market_id,
                    Trade.settled == False,
                    Trade.is_live == False,
                ).first()

                if existing:
                    continue

                trade_size = min(signal.suggested_size, settings.WEATHER_MAX_TRADE_SIZE)
                trade_size = max(trade_size, MIN_TRADE_SIZE)

                if state.bankroll < MIN_TRADE_SIZE:
                    log_event("warning", f"Bankroll too low: ${state.bankroll:.2f}")
                    break

                if trades_executed >= MAX_TRADES_PER_SCAN:
                    break

                entry_price = round(signal.market.yes_price if signal.direction == "yes" else signal.market.no_price, 2)

                trade = Trade(
                    market_ticker=signal.market.market_id,
                    platform="polymarket",
                    event_slug=signal.market.slug,
                    market_type="weather",
                    direction=signal.direction,
                    entry_price=entry_price,
                    size=round(trade_size, 2),
                    shares=round(trade_size / entry_price, 2) if entry_price > 0 else 0,
                    model_probability=signal.model_probability,
                    market_price_at_entry=signal.market_probability,
                    edge_at_entry=signal.edge,
                    is_live=False,
                )

                db.add(trade)
                db.flush()

                # Link to signal record
                matching_signal = db.query(Signal).filter(
                    Signal.market_ticker == signal.market.market_id,
                    Signal.market_type == "weather",
                    Signal.executed == False,
                ).order_by(Signal.timestamp.desc()).first()
                if matching_signal:
                    matching_signal.executed = True
                    trade.signal_id = matching_signal.id

                state.total_trades += 1
                trades_executed += 1

                log_event("trade",
                    f"WX {signal.market.city_name}: {signal.direction.upper()} "
                    f"${trade_size:.0f} @ {entry_price:.0%} | "
                    f"{signal.market.metric} {signal.market.direction} {signal.market.threshold_c:.0f}C",
                    {
                        "slug": signal.market.slug,
                        "direction": signal.direction,
                        "size": trade_size,
                        "edge": signal.edge,
                        "entry_price": entry_price,
                        "city": signal.market.city_name,
                    }
                )

            state.last_run = datetime.utcnow()
            db.commit()

            if trades_executed > 0:
                log_event("success", f"Executed {trades_executed} weather trade(s)")
            else:
                logger.debug("No new weather trades executed")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Weather scan error: {str(e)}")
        logger.exception("Error in weather_scan_and_trade_job")


async def settlement_job():
    """
    Background job: Check and settle pending trades.
    Runs every 2 minutes (BTC 5-min markets resolve fast).
    """
    logger.debug("Checking BTC trade settlements...")

    try:
        from backend.core.settlement import settle_pending_trades, update_bot_state_with_settlements

        db = SessionLocal()
        try:
            pending_count = db.query(Trade).filter(Trade.settled == False).count()

            if pending_count == 0:
                logger.debug("No pending trades to settle")
                return

            log_event("data", f"Processing {pending_count} pending trades")

            settled = await settle_pending_trades(db)

            if settled:
                await update_bot_state_with_settlements(db, settled)

                wins = sum(1 for t in settled if t.result == "win")
                losses = sum(1 for t in settled if t.result == "loss")
                total_pnl = sum(t.pnl for t in settled if t.pnl is not None)

                log_event("success", f"Settled {len(settled)} trades: {wins}W/{losses}L, P&L: ${total_pnl:.2f}", {
                    "settled_count": len(settled),
                    "wins": wins,
                    "losses": losses,
                    "pnl": total_pnl
                })

                for trade in settled:
                    result_prefix = "+" if trade.pnl and trade.pnl > 0 else ""
                    log_event("data", f"  {trade.event_slug}: {trade.result.upper()} {result_prefix}${trade.pnl:.2f}")
            else:
                logger.debug("No trades ready for settlement")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Settlement error: {str(e)}")
        logger.exception("Error in settlement_job")


async def heartbeat_job():
    """Periodic heartbeat. Runs every minute."""
    db = None
    try:
        db = SessionLocal()
        sim_state = get_bot_state(db, is_live=False)
        live_state = get_bot_state(db, is_live=True)
        sim_pending = db.query(Trade).filter(Trade.settled == False, Trade.is_live == False).count()
        live_pending = db.query(Trade).filter(Trade.settled == False, Trade.is_live == True).count()

        live_info = f" | LIVE: {live_pending} pending, ${live_state.bankroll:.2f}" if settings.LIVE_TRADING_ENABLED else ""
        log_event("data", f"Heartbeat: SIM {sim_pending} pending, ${sim_state.bankroll:.2f}{live_info}", {
            "sim_pending": sim_pending,
            "sim_bankroll": sim_state.bankroll,
            "live_pending": live_pending,
            "live_bankroll": live_state.bankroll,
            "is_running": sim_state.is_running,
            "live_enabled": settings.LIVE_TRADING_ENABLED,
        })
    except Exception as e:
        log_event("warning", f"Heartbeat failed: {str(e)}")
    finally:
        if db:
            db.close()


def start_scheduler():
    """Start the background scheduler for BTC 5-min trading."""
    global scheduler

    if scheduler is not None and scheduler.running:
        log_event("warning", "Scheduler already running")
        return

    scheduler = AsyncIOScheduler()

    scan_seconds = settings.SCAN_INTERVAL_SECONDS
    settle_seconds = settings.SETTLEMENT_INTERVAL_SECONDS

    # Scan BTC markets every minute
    scheduler.add_job(
        scan_and_trade_job,
        IntervalTrigger(seconds=scan_seconds),
        id="market_scan",
        replace_existing=True,
        max_instances=1
    )

    # Check settlements every 2 minutes
    scheduler.add_job(
        settlement_job,
        IntervalTrigger(seconds=settle_seconds),
        id="settlement_check",
        replace_existing=True,
        max_instances=1
    )

    # Heartbeat every minute
    scheduler.add_job(
        heartbeat_job,
        IntervalTrigger(minutes=1),
        id="heartbeat",
        replace_existing=True,
        max_instances=1
    )

    # Weather trading jobs (gated by WEATHER_ENABLED)
    if settings.WEATHER_ENABLED:
        weather_scan_seconds = settings.WEATHER_SCAN_INTERVAL_SECONDS
        weather_settle_seconds = settings.WEATHER_SETTLEMENT_INTERVAL_SECONDS

        scheduler.add_job(
            weather_scan_and_trade_job,
            IntervalTrigger(seconds=weather_scan_seconds),
            id="weather_scan",
            replace_existing=True,
            max_instances=1,
        )

    scheduler.start()
    log_event("success", "BTC 5-min trading scheduler started", {
        "scan_interval": f"{scan_seconds}s",
        "settlement_interval": f"{settle_seconds}s",
        "min_edge": f"{settings.MIN_EDGE_THRESHOLD:.0%}",
        "weather_enabled": settings.WEATHER_ENABLED,
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "executor_stub": get_executor().is_stub,
    })

    asyncio.create_task(scan_and_trade_job())

    if settings.WEATHER_ENABLED:
        asyncio.create_task(weather_scan_and_trade_job())


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler

    if scheduler is None or not scheduler.running:
        log_event("info", "Scheduler not running")
        return

    scheduler.shutdown(wait=False)
    scheduler = None
    log_event("info", "Scheduler stopped")


def is_scheduler_running() -> bool:
    """Check if scheduler is currently running."""
    return scheduler is not None and scheduler.running


async def run_manual_scan():
    """Trigger a manual market scan."""
    log_event("info", "Manual scan triggered")
    await scan_and_trade_job()


async def run_manual_settlement():
    """Trigger a manual settlement check."""
    log_event("info", "Manual settlement triggered")
    await settlement_job()
