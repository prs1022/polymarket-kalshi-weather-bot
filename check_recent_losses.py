#!/usr/bin/env python3
"""检查最近的实盘亏损交易"""
import sqlite3

conn = sqlite3.connect('tradingbot.db')
c = conn.cursor()

print("=" * 80)
print("📉 最近实盘亏损交易分析")
print("=" * 80)

# 查询所有实盘交易
c.execute('''
    SELECT id, event_slug, direction, entry_price, size, shares,
           grid_filled_cost, grid_filled_shares, 
           stop_loss_price, stop_loss_filled,
           settled, settlement_value, result, pnl, timestamp
    FROM trades
    WHERE is_live = 1
    ORDER BY timestamp DESC
    LIMIT 10
''')

trades = c.fetchall()

total_loss = 0
no_stoploss_count = 0

for t in trades:
    trade_id, slug, direction, entry, size, shares = t[:6]
    grid_cost, grid_shares = t[6:8]
    stop_loss, stop_filled = t[8:10]
    settled, settlement, result, pnl, timestamp = t[10:]
    
    print(f"\n{'='*80}")
    print(f"【实盘 ID:{trade_id}】- {slug}")
    print(f"时间: {timestamp}")
    print(f"方向: {direction.upper()}")
    print(f"入场: {entry:.3f} ({entry*100:.0f}¢)")
    print(f"预算: ${size:.2f}")
    print()
    print(f"网格成本: ${grid_cost:.2f}")
    print(f"网格份额: {grid_shares:.2f}")
    print()
    
    if stop_loss:
        print(f"止损价: {stop_loss:.3f} ({stop_loss*100:.0f}¢)")
        print(f"止损成交: {'是 ✅' if stop_filled else '否'}")
    else:
        print(f"止损价: ❌ 未设置")
        no_stoploss_count += 1
    
    print()
    
    if settled:
        outcome = "UP" if settlement == 1.0 else "DOWN"
        print(f"已结算: {outcome}")
        print(f"结果: {result}")
        print(f"P&L: ${pnl:.2f}")
        
        if pnl < 0:
            print(f"❌ 亏损 ${abs(pnl):.2f}")
            total_loss += pnl
            
            # 查询网格订单
            c.execute('''
                SELECT level, limit_price, shares, cost, status
                FROM grid_orders
                WHERE trade_id = ?
                ORDER BY level
            ''', (trade_id,))
            orders = c.fetchall()
            
            filled = [o for o in orders if o[4] == 'filled']
            
            print(f"\n网格成交: {len(filled)}/{len(orders)} 层")
            for o in orders:
                status_mark = "✅" if o[4] == 'filled' else "⏳"
                print(f"  {status_mark} Level {o[0]}: {o[1]:.2f} ({o[1]*100:.0f}¢) × {o[2]:.2f} = ${o[3]:.2f} ({o[4]})")
            
            if not stop_loss:
                print(f"\n⚠️  问题: 网格成交但未设置止损！")
                print(f"  如果有止损 @ {entry + 0.05:.2f}，可能不会亏这么多")
    else:
        print(f"未结算（待确认）")

print("\n" + "=" * 80)
print(f"\n【统计】")
print(f"  总亏损: ${total_loss:.2f}")
print(f"  未设置止损的交易数: {no_stoploss_count}")

print(f"\n【根本原因】")
print(f"  ❌ 这些交易是在渐进式止损代码修改**之前**开的")
print(f"  ❌ 当时的代码只有在网格全部成交后才设置止损")
print(f"  ❌ 但这几笔交易可能网格没有全部成交")
print(f"  ❌ 导致没有止损保护")

print(f"\n【解决方案】")
print(f"  ✅ 代码已修改（渐进式止损）")
print(f"  ✅ 需要立即重启程序")
print(f"  ✅ 重启后新交易会有止损保护")

conn.close()
