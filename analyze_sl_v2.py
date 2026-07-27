"""Analyze stop-loss fill and direction correctness"""
import sqlite3

conn = sqlite3.connect('tradingbot.db')
c = conn.cursor()

print('=' * 60)
print('          SIM 止损单详细分析')
print('=' * 60)

# Total trades with stop_loss_price set
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND stop_loss_price IS NOT NULL')
sl_total = c.fetchone()[0]

# Successfully filled stop-loss
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND stop_loss_filled = 1')
sl_filled = c.fetchone()[0]

# Stop-loss not filled (pending or expired)
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND stop_loss_filled = 0')
sl_not_filled = c.fetchone()[0]

# Total SIM trades
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0')
total = c.fetchone()[0]

print()
print("[1] 止损单概况")
print("    有止损价的交易: {} / {} = {:.1f}%".format(sl_total, total, sl_total/total*100))
print("    成功止损: {} / {} = {:.1f}%".format(sl_filled, sl_total, sl_filled/sl_total*100 if sl_total else 0))
print("    未触发止损: {} / {} = {:.1f}%".format(sl_not_filled, sl_total, sl_not_filled/sl_total*100 if sl_total else 0))

# Among filled stop-loss trades, direction correctness
print()
print("[2] 成功止损的方向分析")
print("    '方向正确' = 市场反向走(止损保护了你)")
print("    '方向错误' = 市场同向走(本可盈利但被止损踢出)")

# Direction correct: market went against position
# UP trade + settlement_value=0 (DOWN won) -> correct stop-loss
# DOWN trade + settlement_value=1 (UP won) -> correct stop-loss
c.execute("""
    SELECT COUNT(*) FROM trades 
    WHERE is_live = 0 AND stop_loss_filled = 1 AND settled = 1
    AND (
        (direction = 'up' AND settlement_value = 0.0) 
        OR (direction = 'down' AND settlement_value = 1.0)
    )
""")
sl_correct = c.fetchone()[0]

c.execute("""
    SELECT COUNT(*) FROM trades 
    WHERE is_live = 0 AND stop_loss_filled = 1 AND settled = 1
""")
sl_settled = c.fetchone()[0]

# Direction wrong: market went same direction (would have won)
c.execute("""
    SELECT COUNT(*) FROM trades 
    WHERE is_live = 0 AND stop_loss_filled = 1 AND settled = 1
    AND (
        (direction = 'up' AND settlement_value = 1.0) 
        OR (direction = 'down' AND settlement_value = 0.0)
    )
""")
sl_wrong = c.fetchone()[0]

# Not settled yet
sl_unsettled = sl_filled - sl_settled

print()
print("    成功止损且已结算: {}".format(sl_settled))
print("    成功止损但未结算: {}".format(sl_unsettled))
print()

if sl_settled > 0:
    print("    [2a] 方向正确 (市场反向, 止损保护生效):")
    print("         {} / {} = {:.1f}%".format(sl_correct, sl_settled, sl_correct/sl_settled*100))
    print()
    print("    [2b] 方向错误 (市场同向, 本可盈利):")
    print("         {} / {} = {:.1f}%".format(sl_wrong, sl_settled, sl_wrong/sl_settled*100))

# Detailed breakdown
print()
print("[3] 成功止损交易明细")
c.execute("""
    SELECT 
        direction,
        settlement_value,
        result,
        COUNT(*),
        AVG(entry_price),
        AVG(stop_loss_price),
        AVG(grid_filled_shares),
        AVG(grid_filled_cost),
        SUM(pnl)
    FROM trades 
    WHERE is_live = 0 AND stop_loss_filled = 1
    GROUP BY direction, settlement_value, result
    ORDER BY direction, settlement_value
""")
rows = c.fetchall()

fmt = "    {:>5} {:>6} {:>10} {:>6} {:>10} {:>10} {:>8} {:>8} {:>8}"
print(fmt.format('dir', 'settle', 'result', 'cnt', 'avg_entry', 'avg_sl', 'avg_shr', 'avg_cost', 'sum_pnl'))
print("    " + "-" * 80)
for r in rows:
    sv = "{:.0f}".format(r[1]) if r[1] is not None else "N/A"
    print(fmt.format(r[0], sv, r[2], r[3], 
                     "{:.3f}".format(r[4]), "{:.3f}".format(r[5]),
                     "{:.0f}".format(r[6]), "{:.2f}".format(r[7]),
                     "{:.2f}".format(r[8])))

# Among NOT-filled stop-loss trades
print()
print("[4] 未触发止损的交易 (有止损价但价格没回到止损位)")
c.execute("""
    SELECT 
        direction,
        settlement_value,
        result,
        COUNT(*),
        AVG(entry_price),
        AVG(stop_loss_price),
        AVG(grid_filled_shares),
        SUM(pnl)
    FROM trades 
    WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND stop_loss_filled = 0 AND settled = 1
    GROUP BY direction, settlement_value, result
    ORDER BY direction, settlement_value
""")
rows2 = c.fetchall()
fmt2 = "    {:>5} {:>6} {:>10} {:>6} {:>10} {:>10} {:>8} {:>8}"
print(fmt2.format('dir', 'settle', 'result', 'cnt', 'avg_entry', 'avg_sl', 'avg_shr', 'sum_pnl'))
print("    " + "-" * 70)
for r in rows2:
    sv = "{:.0f}".format(r[1]) if r[1] is not None else "N/A"
    print(fmt2.format(r[0], sv, r[2], r[3],
                      "{:.3f}".format(r[4]), "{:.3f}".format(r[5]),
                      "{:.0f}".format(r[6]), "{:.2f}".format(r[7])))

# Summary table
print()
print("=" * 60)
print("                    总结")
print("=" * 60)
print()
print("  止损触发率:     {}/{} = {:.1f}%".format(sl_filled, sl_total, sl_filled/sl_total*100 if sl_total else 0))
if sl_settled > 0:
    print("  方向正确率:     {}/{} = {:.1f}%".format(sl_correct, sl_settled, sl_correct/sl_settled*100))
    print("  方向错误率:     {}/{} = {:.1f}%".format(sl_wrong, sl_settled, sl_wrong/sl_settled*100))
print()

# What would PnL look like if stop-loss PnL was calculated correctly?
print("  [修正后PnL估算]")
c.execute("""
    SELECT 
        SUM(grid_filled_shares * stop_loss_price - grid_filled_cost)
    FROM trades 
    WHERE is_live = 0 AND stop_loss_filled = 1
""")
real_sl_pnl = c.fetchone()[0] or 0

c.execute("""
    SELECT SUM(pnl) FROM trades 
    WHERE is_live = 0 AND settled = 1 AND result != 'stop_loss'
""")
non_sl_pnl = c.fetchone()[0] or 0

c.execute("SELECT SUM(pnl) FROM trades WHERE is_live = 0 AND settled = 1")
current_total = c.fetchone()[0] or 0

print("  当前总PnL:  ${:.2f}".format(current_total))
print("  止损交易修正后PnL: +${:.2f}".format(real_sl_pnl))
print("  非止损交易PnL: ${:.2f}".format(non_sl_pnl))
print("  修正后总PnL:  ${:.2f}".format(non_sl_pnl + real_sl_pnl))

conn.close()
