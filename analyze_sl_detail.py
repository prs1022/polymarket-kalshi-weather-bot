"""Deep analysis of stop_loss trades PnL"""
import sqlite3

conn = sqlite3.connect('tradingbot.db')
c = conn.cursor()

# Recent stop_loss trades
c.execute('''SELECT id, direction, entry_price, stop_loss_price, grid_filled_shares, 
                    grid_filled_cost, settlement_value, result, pnl
             FROM trades 
             WHERE is_live = 0 AND result = 'stop_loss' 
             ORDER BY id DESC LIMIT 10''')
rows = c.fetchall()

print('=== 最近10笔 stop_loss 交易明细 ===')
fmt = "{:>4} {:>5} {:>8} {:>8} {:>6} {:>8} {:>6} {:>10} {:>8}"
print(fmt.format('ID', '方向', '入场价', '止损价', '层数', '成本', '结算值', '结果', 'PnL'))
for r in rows:
    print(fmt.format(r[0], r[1], f"{r[2]:.3f}", f"{r[3]:.3f}", f"{r[4]:.0f}", 
                     f"{r[5]:.2f}", f"{r[6]:.1f}", r[7], f"{r[8]:.2f}"))

# Grid orders for latest stop_loss trade
c.execute('SELECT id FROM trades WHERE is_live = 0 AND result = "stop_loss" ORDER BY id DESC LIMIT 1')
tid = c.fetchone()[0]
c.execute('SELECT level, limit_price, shares, cost, status, fill_price FROM grid_orders WHERE trade_id = ?', (tid,))
print(f'\n=== Trade #{tid} 网格订单 ===')
for r in c.fetchall():
    fill = f"{r[5]:.3f}" if r[5] else "N/A"
    print(f"  L{r[0]}: limit={r[1]:.3f}, shares={r[2]:.0f}, cost={r[3]:.2f}, status={r[4]}, fill={fill}")

# PnL calculation check
c.execute('''SELECT id, direction, entry_price, stop_loss_price, grid_filled_shares, 
                    grid_filled_cost, settlement_value, result, pnl,
                    CASE WHEN grid_filled_cost > 0 AND stop_loss_price > 0 
                         THEN grid_filled_shares * stop_loss_price - grid_filled_cost
                         ELSE 0 END as expected_pnl
             FROM trades 
             WHERE is_live = 0 AND result = 'stop_loss'
             ORDER BY id DESC LIMIT 15''')
rows2 = c.fetchall()
print(f'\n=== stop_loss PnL 实际 vs 理论 ===')
fmt2 = "{:>4} {:>5} {:>8} {:>8} {:>6} {:>8} {:>5} {:>10} {:>10}"
print(fmt2.format('ID', '方向', '入场', '止损', '层数', '成本', '结算', '实际PnL', '理论PnL'))
for r in rows2:
    print(fmt2.format(r[0], r[1], f"{r[2]:.3f}", f"{r[3]:.3f}", f"{r[4]:.0f}",
                      f"{r[5]:.2f}", f"{r[6]:.1f}", f"{r[7]:.2f}", f"{r[8]:.2f}"))

# Also check win trades (0 grid fills)
print(f'\n=== win 交易明细 (grid_filled_shares=0) ===')
c.execute('''SELECT id, direction, entry_price, stop_loss_price, grid_filled_shares, 
                    grid_filled_cost, settlement_value, result, pnl
             FROM trades 
             WHERE is_live = 0 AND result = 'win' 
             ORDER BY id DESC LIMIT 5''')
for r in c.fetchall():
    print(f"  #{r[0]}: {r[1]}, entry={r[2]:.3f}, sl={r[3]}, fills={r[4]:.0f}, cost={r[5]:.2f}, settle={r[6]:.1f}, pnl={r[7]:.2f}")

# Check settlement code to understand how stop_loss PnL is calculated
print(f'\n=== 关键发现 ===')
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND result = "stop_loss" AND pnl = 0')
zero_pnl = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND result = "stop_loss"')
total_sl = c.fetchone()[0]
print(f'  stop_loss交易中PnL=0: {zero_pnl}/{total_sl}')
print(f'  这意味着止损的PnL计算可能有问题')

conn.close()
