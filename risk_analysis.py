#!/usr/bin/env python3
"""风险分析：10美元本金能否持续运行"""
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('tradingbot.db')
cursor = conn.cursor()

print("=" * 80)
print("💰 资金风险分析报告 - $10 本金")
print("=" * 80)

# 1. 查看当前配置
print("\n【当前配置】")
print("  初始本金: $10")
print("  每笔最大交易: $5")
print("  每日亏损限制: $30")
print("  最大待结算单数: 20")

# 2. 历史交易统计
cursor.execute('''
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN is_live=1 THEN 1 ELSE 0 END) as live_count,
        SUM(CASE WHEN is_live=0 THEN 1 ELSE 0 END) as sim_count,
        SUM(CASE WHEN settled=1 THEN 1 ELSE 0 END) as settled_count,
        AVG(size) as avg_size,
        MIN(size) as min_size,
        MAX(size) as max_size,
        SUM(CASE WHEN settled=0 THEN size ELSE 0 END) as pending_exposure
    FROM trades
''')
stats = cursor.fetchone()

print(f"\n【交易统计】")
print(f"  总交易数: {stats[0]}")
print(f"  实盘交易: {stats[1]}")
print(f"  模拟交易: {stats[2]}")
print(f"  已结算: {stats[3]}")
print(f"  平均交易额: ${stats[4]:.2f}")
print(f"  最小交易额: ${stats[5]:.2f}")
print(f"  最大交易额: ${stats[6]:.2f}")
print(f"  当前待结算敞口: ${stats[7]:.2f}")

# 3. 实盘交易详情
cursor.execute('''
    SELECT id, event_slug, direction, size, edge_at_entry, timestamp, settled
    FROM trades
    WHERE is_live=1
    ORDER BY timestamp DESC
    LIMIT 10
''')
live_trades = cursor.fetchall()

print(f"\n【实盘交易记录】（最近10笔）")
if live_trades:
    for trade in live_trades:
        status = "✅已结算" if trade[6] else "⏳待结算"
        print(f"  {status} | ${trade[3]:.2f} | Edge:{trade[4]:+.1%} | {trade[2].upper()} | {trade[1][-10:]}")
else:
    print("  ❌ 无实盘交易记录")

# 4. 盈亏统计（仅已结算）
cursor.execute('''
    SELECT 
        COUNT(*) as settled,
        SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses,
        SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as total_pnl,
        AVG(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as avg_pnl,
        MAX(pnl) as max_win,
        MIN(pnl) as max_loss
    FROM trades
    WHERE settled=1 AND is_live=0
''')
pnl_stats = cursor.fetchone()

print(f"\n【盈亏统计】（模拟盘已结算）")
print(f"  已结算单数: {pnl_stats[0]}")
print(f"  胜: {pnl_stats[1]} | 负: {pnl_stats[2]}")
if pnl_stats[0] > 0:
    win_rate = pnl_stats[1] / pnl_stats[0] * 100
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  累计盈亏: ${pnl_stats[3]:.2f}")
    print(f"  平均每单: ${pnl_stats[4]:.2f}")
    print(f"  最大单笔盈利: ${pnl_stats[5]:.2f}")
    print(f"  最大单笔亏损: ${pnl_stats[6]:.2f}")

# 5. 待结算风险
cursor.execute('''
    SELECT COUNT(*), SUM(size)
    FROM trades
    WHERE settled=0 AND is_live=1
''')
pending = cursor.fetchone()

print(f"\n【实盘待结算】")
print(f"  待结算单数: {pending[0]}")
if pending[1]:
    print(f"  占用资金: ${pending[1]:.2f}")
    print(f"  占比: {pending[1]/10*100:.1f}% (本金$10)")

# 6. 风险评估
print(f"\n【风险评估】")

# 当前待结算敞口
live_pending_exposure = pending[1] if pending[1] else 0

# 假设最坏情况：所有待结算单全亏
worst_case_loss = live_pending_exposure
remaining_after_worst = 10 - worst_case_loss

print(f"  ⚠️  最坏情况（所有待结算单全亏）: -${worst_case_loss:.2f}")
print(f"  💰 剩余本金: ${remaining_after_worst:.2f}")

if remaining_after_worst < 0:
    print(f"  ❌ 警告：可能归零！")
elif remaining_after_worst < 5:
    print(f"  ⚠️  警告：本金不足50%，风险较高")
elif remaining_after_worst < 8:
    print(f"  ⚡ 注意：本金下降，需谨慎")
else:
    print(f"  ✅ 相对安全，但需持续监控")

# 7. 配置风险分析
print(f"\n【配置风险分析】")
max_trade_size = 5.0
daily_loss_limit = 30.0
max_pending = 20

print(f"  每笔最大交易: ${max_trade_size}")
print(f"  最大单次损失占比: {max_trade_size/10*100:.0f}%")

if max_trade_size >= 10:
    print(f"  ❌ 危险！单笔可能归零")
elif max_trade_size >= 5:
    print(f"  ⚠️  风险高：单笔亏损50%本金")
elif max_trade_size >= 2:
    print(f"  ⚡ 风险中等：单笔亏损20%本金")
else:
    print(f"  ✅ 风险较低：单笔亏损<20%本金")

# 计算理论最大并发敞口
theoretical_max_exposure = max_trade_size * max_pending
print(f"\n  理论最大敞口: ${theoretical_max_exposure:.0f} (${max_trade_size} × {max_pending}单)")
print(f"  本金杠杆: {theoretical_max_exposure/10:.0f}x")

if theoretical_max_exposure > 50:
    print(f"  ❌ 危险！理论最大敞口远超本金")
elif theoretical_max_exposure > 20:
    print(f"  ⚠️  注意：理论最大敞口是本金的{theoretical_max_exposure/10:.0f}倍")
else:
    print(f"  ✅ 敞口控制在合理范围")

# 8. 建议
print(f"\n【💡 优化建议】")

if max_trade_size >= 5:
    print(f"  1. ⚠️  降低 MAX_TRADE_SIZE: 当前$5对$10本金来说太高")
    print(f"     建议: $1-2 (10-20%本金)")

if max_pending >= 10:
    print(f"  2. ⚠️  降低 MAX_TOTAL_PENDING_TRADES: 当前{max_pending}太多")
    print(f"     建议: 5-8 (限制总敞口)")

if pnl_stats[0] > 0 and pnl_stats[1] / pnl_stats[0] < 0.5:
    print(f"  3. ⚠️  胜率<50%: 需要优化信号质量")
    print(f"     考虑: 提高 MIN_EDGE_THRESHOLD")

print(f"\n【💰 资金管理建议】")
print(f"  保守型 ($10本金):")
print(f"    - MAX_TRADE_SIZE = $1 (10%本金)")
print(f"    - MAX_TOTAL_PENDING_TRADES = 5")
print(f"    - 理论最大敞口 = $5 (50%本金)")
print(f"")
print(f"  平衡型 ($10本金):")
print(f"    - MAX_TRADE_SIZE = $2 (20%本金)")
print(f"    - MAX_TOTAL_PENDING_TRADES = 3")
print(f"    - 理论最大敞口 = $6 (60%本金)")
print(f"")
print(f"  激进型 ($10本金) - 当前配置:")
print(f"    - MAX_TRADE_SIZE = $5 (50%本金)")
print(f"    - MAX_TOTAL_PENDING_TRADES = 20")
print(f"    - 理论最大敞口 = $100 (1000%本金) ❌")

print("\n" + "=" * 80)

conn.close()
