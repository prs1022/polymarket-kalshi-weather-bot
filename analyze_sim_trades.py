"""Analyze SIM trades from tradingbot.db"""
import sqlite3

conn = sqlite3.connect('tradingbot.db')
c = conn.cursor()

# 1. Total SIM trades
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0')
total = c.fetchone()[0]

c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND settled = 1')
settled = c.fetchone()[0]

c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND settled = 0')
pending = c.fetchone()[0]

print('=' * 60)
print('              SIM 模拟盘交易分析报告')
print('=' * 60)

# 2. Wins/Losses breakdown
c.execute("""
    SELECT result, COUNT(*), SUM(pnl) 
    FROM trades WHERE is_live = 0 AND settled = 1
    GROUP BY result
""")
results = c.fetchall()

print(f'\n【基本统计】')
print(f'  总交易数: {total}')
print(f'  已结算:   {settled}')
print(f'  待结算:   {pending}')
for r in results:
    print(f'  {r[0]}: {r[1]}笔, PnL={r[2]:.2f}')

# 3. Win rate
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND settled = 1 AND result = "win"')
wins = c.fetchone()[0]
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND settled = 1 AND result = "loss"')
losses = c.fetchone()[0]
win_rate = wins / settled * 100 if settled > 0 else 0

print(f'\n【胜率】')
print(f'  胜率: {wins}/{settled} = {win_rate:.1f}%')

# 4. Profit/loss ratio
c.execute('SELECT AVG(pnl), SUM(pnl), MIN(pnl), MAX(pnl) FROM trades WHERE is_live = 0 AND settled = 1 AND result = "win"')
win_stats = c.fetchone()
c.execute('SELECT AVG(pnl), SUM(pnl), MIN(pnl), MAX(pnl) FROM trades WHERE is_live = 0 AND settled = 1 AND result = "loss"')
loss_stats = c.fetchone()

print(f'\n【盈亏比】')
if win_stats[0]:
    print(f'  盈利单: 平均+${win_stats[0]:.4f}, 总+${win_stats[1]:.2f}')
    print(f'           最小+${win_stats[2]:.4f}, 最大+${win_stats[3]:.4f}')
if loss_stats[0]:
    print(f'  亏损单: 平均${loss_stats[0]:.4f}, 总${loss_stats[1]:.2f}')
    print(f'           最小${loss_stats[2]:.4f}, 最大${loss_stats[3]:.4f}')
if win_stats[0] and loss_stats[0] and loss_stats[0] != 0:
    ratio = abs(win_stats[0] / loss_stats[0])
    print(f'  盈亏比: {ratio:.2f}')

c.execute('SELECT SUM(pnl) FROM trades WHERE is_live = 0 AND settled = 1')
total_pnl = c.fetchone()[0]
print(f'  总PnL: ${total_pnl:.2f}')

# 5. Stop-loss analysis
c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND stop_loss_price IS NOT NULL')
sl_count = c.fetchone()[0]
sl_pct = sl_count / total * 100 if total > 0 else 0

c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND stop_loss_filled = 1')
sl_filled = c.fetchone()[0]

c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND stop_loss_filled = 0')
sl_pending = c.fetchone()[0]

print(f'\n【止损单分析】')
print(f'  触发止损的交易: {sl_count}/{total} = {sl_pct:.1f}%')
print(f'    止损已成交: {sl_filled}')
print(f'    止损挂单中: {sl_pending}')
print(f'    无止损(未成交/0层): {total - sl_count}')

# 6. Stop-loss filled trades - detailed breakdown
print(f'\n【止损单方向正确性分析】')
c.execute("""
    SELECT 
        direction,
        settlement_value,
        result,
        COUNT(*),
        SUM(pnl),
        AVG(stop_loss_price),
        AVG(entry_price)
    FROM trades 
    WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND settled = 1
    GROUP BY direction, settlement_value, result
    ORDER BY direction, settlement_value
""")
rows = c.fetchall()

header = f"{'方向':>6} {'结算':>6} {'结果':>6} {'笔数':>6} {'总PnL':>10} {'平均止损价':>10} {'平均入场价':>10}"
print(f'  {header}')
print(f'  {"-" * 70}')
for r in rows:
    line = f"{r[0]:>6} {r[1]:>6.0f} {r[2]:>6} {r[3]:>6} {r[4]:>10.2f} {r[5]:>10.3f} {r[6]:>10.3f}"
    print(f'  {line}')

# Direction correctness for stop-loss settled trades
# "Correct" = market went against position, stop-loss was warranted
c.execute("""
    SELECT COUNT(*) FROM trades 
    WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND settled = 1
    AND (
        (direction = 'up' AND settlement_value = 0.0) 
        OR (direction = 'down' AND settlement_value = 1.0)
    )
""")
sl_correct = c.fetchone()[0]

c.execute('SELECT COUNT(*) FROM trades WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND settled = 1')
sl_settled = c.fetchone()[0]

c.execute("""
    SELECT SUM(pnl) FROM trades 
    WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND settled = 1
    AND (
        (direction = 'up' AND settlement_value = 0.0) 
        OR (direction = 'down' AND settlement_value = 1.0)
    )
""")
sl_correct_pnl = c.fetchone()[0]

c.execute("""
    SELECT SUM(pnl) FROM trades 
    WHERE is_live = 0 AND stop_loss_price IS NOT NULL AND settled = 1
    AND NOT (
        (direction = 'up' AND settlement_value = 0.0) 
        OR (direction = 'down' AND settlement_value = 1.0)
    )
""")
sl_wrong_pnl = c.fetchone()[0]

if sl_settled > 0:
    print(f'\n  方向正确（市场反向，止损保护生效）: {sl_correct}/{sl_settled} = {sl_correct/sl_settled*100:.1f}%')
    if sl_correct_pnl:
        print(f'    这些交易的PnL: {sl_correct_pnl:.2f}')
    print(f'  方向错误（市场同向，本可盈利）: {sl_settled - sl_correct}/{sl_settled} = {(sl_settled-sl_correct)/sl_settled*100:.1f}%')
    if sl_wrong_pnl:
        print(f'    这些交易的PnL: {sl_wrong_pnl:.2f}')

# 7. Additional: entry price distribution
c.execute("""
    SELECT 
        CASE 
            WHEN entry_price < 0.50 THEN '<0.50'
            WHEN entry_price < 0.55 THEN '0.50-0.55'
            WHEN entry_price < 0.60 THEN '0.55-0.60'
            ELSE '>=0.60'
        END as price_range,
        COUNT(*),
        SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END),
        AVG(pnl)
    FROM trades 
    WHERE is_live = 0 AND settled = 1
    GROUP BY price_range
    ORDER BY price_range
""")
price_rows = c.fetchall()
print(f'\n【入场价格分布】')
header2 = f"{'价格区间':>10} {'笔数':>6} {'胜场':>6} {'胜率':>8} {'平均PnL':>10}"
print(f'  {header2}')
for r in price_rows:
    wr = r[2] / r[1] * 100 if r[1] > 0 else 0
    line2 = f"{r[0]:>10} {r[1]:>6} {r[2]:>6} {wr:>7.1f}% {r[3]:>10.4f}"
    print(f'  {line2}')

# 8. Grid fill depth analysis
c.execute("""
    SELECT 
        grid_filled_shares,
        COUNT(*),
        SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END),
        AVG(pnl)
    FROM trades 
    WHERE is_live = 0 AND settled = 1
    GROUP BY grid_filled_shares
    ORDER BY grid_filled_shares
""")
fill_rows = c.fetchall()
print(f'\n【网格成交层数分析】')
header3 = f"{'成交层数':>8} {'笔数':>6} {'胜场':>6} {'胜率':>8} {'平均PnL':>10}"
print(f'  {header3}')
for r in fill_rows:
    wr = r[2] / r[1] * 100 if r[1] > 0 else 0
    line3 = f"{r[0]:>8.0f} {r[1]:>6} {r[2]:>6} {wr:>7.1f}% {r[3]:>10.4f}"
    print(f'  {line3}')

print(f'\n{"=" * 60}')
conn.close()
