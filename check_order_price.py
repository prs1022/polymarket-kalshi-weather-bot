#!/usr/bin/env python3
"""检查订单价格问题"""
import sqlite3

conn = sqlite3.connect('tradingbot.db')
c = conn.cursor()

print('🔍 查询 btc-updown-5m-1784105400 的交易详情')
print('=' * 80)

# 查询交易记录
c.execute('''
    SELECT id, direction, entry_price, size, shares, 
           model_probability, market_price_at_entry, edge_at_entry,
           timestamp, settled
    FROM trades
    WHERE event_slug = 'btc-updown-5m-1784105400'
''')

trade = c.fetchone()
if trade:
    print(f'\n【交易信息】')
    print(f'  Trade ID: {trade[0]}')
    print(f'  方向: {trade[1].upper()}')
    print(f'  入场价格: {trade[2]:.2f} ({trade[2]*100:.0f}美分)')
    print(f'  交易额: ${trade[3]:.2f}')
    print(f'  份额: {trade[4]:.2f}')
    print(f'  模型概率: {trade[5]:.3f} ({trade[5]*100:.1f}%)')
    print(f'  市场价格: {trade[6]:.3f} ({trade[6]*100:.1f}%)')
    print(f'  Edge: {trade[7]:+.3f} ({trade[7]*100:+.1f}%)')
    print(f'  时间: {trade[8]}')
    print(f'  已结算: {trade[9]}')
    
    # 查询网格订单
    c.execute('''
        SELECT level, limit_price, shares, cost, status, filled_at
        FROM grid_orders
        WHERE trade_id = ?
        ORDER BY level
    ''', (trade[0],))
    
    orders = c.fetchall()
    print(f'\n【网格订单】')
    print(f'  Level | 限价   | 份额  | 成本    | 状态     | 成交时间')
    print(f'  ' + '-' * 65)
    for order in orders:
        status = order[4]
        filled = order[5] if order[5] else '-'
        print(f'  {order[0]:5} | {order[1]:.2f} ({order[1]*100:3.0f}¢) | {order[2]:5.2f} | ${order[3]:5.2f} | {status:8} | {filled}')
    
    print(f'\n【问题分析】')
    print(f'  当前市场价格（订单簿）: 买1=53¢, 卖1=54¢')
    print(f'  记录的市场价格: {trade[6]:.2f} ({trade[6]*100:.0f}美分)')
    print(f'  入场价格（网格起点）: {trade[2]:.2f} ({trade[2]*100:.0f}美分)')
    print(f'  最高网格价: {orders[0][1]:.2f} ({orders[0][1]*100:.0f}美分)')
    print(f'  最低网格价: {orders[-1][1]:.2f} ({orders[-1][1]*100:.0f}美分)')
    print(f'  ')
    print(f'  ⚠️  问题：入场价 {trade[2]*100:.0f}¢ 远低于市场价 53¢')
    print(f'  原因：可能是 DOWN 方向，记录的是 DOWN token 价格')
    
    if trade[1] == 'down':
        up_price = trade[6]
        down_price = 1 - up_price
        print(f'\n  ✓ 确认：方向是 DOWN')
        print(f'    - UP token 价格: {up_price:.2f} ({up_price*100:.0f}¢)')
        print(f'    - DOWN token 价格: {down_price:.2f} ({down_price*100:.0f}¢)')
        print(f'    - 网格订单是买 DOWN token @ {trade[2]*100:.0f}¢')
        print(f'    - 34¢ 的订单是合理的（低于当前价格，等待回调）')
else:
    print('❌ 未找到该市场的交易记录')

# 查询最近的信号
print(f'\n【最近的信号】')
c.execute('''
    SELECT market_ticker, direction, model_probability, market_price, edge, reasoning
    FROM signals
    ORDER BY timestamp DESC
    LIMIT 1
''')
signal = c.fetchone()
if signal:
    print(f'  Market: {signal[0]}')
    print(f'  方向: {signal[1].upper()}')
    print(f'  模型概率: {signal[2]:.3f}')
    print(f'  市场价格: {signal[3]:.3f}')
    print(f'  Edge: {signal[4]:+.3f}')
    print(f'  推理: {signal[5][:150]}...')

conn.close()
