#!/usr/bin/env python3
"""排查止损单问题 - btc-updown-5m-1784106900"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('tradingbot.db')
c = conn.cursor()

market_slug = 'btc-updown-5m-1784106900'

print("🔍 止损单问题排查")
print("=" * 80)
print(f"市场: {market_slug}")
print()

# 查询交易记录
c.execute('''
    SELECT id, is_live, direction, entry_price, size, shares,
           grid_total_budget, grid_filled_cost, grid_filled_shares,
           stop_loss_price, stop_loss_filled, stop_loss_filled_at,
           settled, settlement_value, result, pnl, timestamp
    FROM trades
    WHERE event_slug = ?
    ORDER BY is_live, timestamp
''', (market_slug,))

trades = c.fetchall()

if not trades:
    print(f"❌ 未找到该市场的交易记录")
    conn.close()
    exit(1)

for trade in trades:
    trade_id = trade[0]
    is_live = trade[1]
    direction = trade[2]
    entry_price = trade[3]
    size = trade[4]
    shares = trade[5]
    grid_budget = trade[6]
    grid_cost = trade[7]
    grid_shares = trade[8]
    stop_loss = trade[9]
    stop_filled = trade[10]
    stop_filled_at = trade[11]
    settled = trade[12]
    settlement_value = trade[13]
    result = trade[14]
    pnl = trade[15]
    timestamp = trade[16]
    
    trade_type = "实盘" if is_live else "模拟"
    
    print(f"【{trade_type}交易 - ID: {trade_id}】")
    print(f"  开仓时间: {timestamp}")
    print(f"  方向: {direction.upper()}")
    print(f"  入场价: {entry_price:.3f} ({entry_price*100:.0f}¢)")
    print(f"  交易额: ${size:.2f}")
    print(f"  份额: {shares:.2f}")
    print()
    print(f"  网格预算: ${grid_budget:.2f}")
    print(f"  网格成本: ${grid_cost:.2f}")
    print(f"  网格份额: {grid_shares:.2f}")
    print()
    print(f"  ⚠️  止损价: {stop_loss if stop_loss else '未设置 ❌'}")
    if stop_loss:
        print(f"  止损成交: {'是' if stop_filled else '否'}")
        if stop_filled:
            print(f"  止损时间: {stop_filled_at}")
    print()
    print(f"  已结算: {'是' if settled else '否'}")
    if settled:
        outcome = "UP" if settlement_value == 1.0 else "DOWN"
        print(f"  结算结果: {outcome}")
        print(f"  交易结果: {result}")
        print(f"  盈亏: ${pnl:.2f}")
        
        if pnl < 0:
            print(f"  ❌ 亏损 ${abs(pnl):.2f}")
            if not stop_loss:
                print(f"  原因: 未设置止损单！")
    print()
    
    # 查询网格订单
    c.execute('''
        SELECT level, limit_price, shares, cost, status, filled_at, clob_order_id
        FROM grid_orders
        WHERE trade_id = ?
        ORDER BY level
    ''', (trade_id,))
    
    orders = c.fetchall()
    
    print(f"  网格订单 ({len(orders)}层):")
    print(f"    Level | 限价   | 份额  | 成本   | 状态    | 成交时间")
    print(f"    " + "-" * 70)
    
    filled_count = 0
    for order in orders:
        level, limit_price, order_shares, cost, status, filled_at, clob_id = order
        filled_str = filled_at if filled_at else "-"
        clob_str = f"CLOB:{clob_id[:8]}..." if clob_id else "-"
        print(f"    {level:5} | {limit_price:.2f} ({limit_price*100:3.0f}¢) | {order_shares:5.2f} | ${cost:6.2f} | {status:8} | {filled_str}")
        if status == "filled":
            filled_count += 1
    
    print()
    print(f"  成交统计: {filled_count}/{len(orders)} 层")
    
    if filled_count == len(orders):
        print(f"  ✅ 网格全部成交")
        if not stop_loss:
            print(f"  ❌ 但未设置止损单！这是问题所在！")
    elif filled_count > 0:
        print(f"  ⚠️  部分成交 ({filled_count}/{len(orders)})")
        if not stop_loss:
            print(f"  ❌ 且未设置止损单（应该第1层成交就挂）")
    
    print()
    print("=" * 80)
    print()

# 查询最近的日志（如果有）
print("\n【可能的原因分析】")
print("-" * 80)

# 检查配置
print("\n1. 配置检查:")
print("   当前配置中 PROGRESSIVE_STOP_LOSS 应该是 True")
print("   但可能:")
print("   - 程序未重启，仍在使用旧代码")
print("   - 代码有 bug")
print("   - 实盘路径未正确执行")

print("\n2. 实盘特殊性:")
print("   实盘需要调用 CLOB API 挂止损卖单")
print("   可能:")
print("   - executor.is_stub = True (没有真正挂单)")
print("   - CLOB API 调用失败")
print("   - 网格成交检查没有正确触发")

print("\n3. 时间线问题:")
c.execute('''
    SELECT timestamp FROM trades WHERE event_slug = ? ORDER BY timestamp DESC LIMIT 1
''', (market_slug,))
trade_time = c.fetchone()[0]
print(f"   开仓时间: {trade_time}")
print(f"   这笔交易是在代码修改前还是修改后？")

print("\n4. 建议:")
print("   ✅ 立即检查程序是否重启")
print("   ✅ 检查运行日志中是否有'渐进式止损'相关输出")
print("   ✅ 如果是修改前的交易，需要重启程序")
print("   ✅ 如果是修改后的交易，需要查看代码是否有 bug")

conn.close()
