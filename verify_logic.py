#!/usr/bin/env python3
"""验证开单逻辑."""
import sqlite3

conn = sqlite3.connect('tradingbot.db')
cursor = conn.cursor()

print("\n=== 开单条件验证 ===\n")
print("配置: MIN_EDGE_THRESHOLD = 0.07 (7%)")
print("配置: INVERT_SIGNAL = True (反转信号)\n")

print("开单逻辑: abs(edge) >= 0.07\n")

# 查询所有交易的 edge
cursor.execute('''
    SELECT id, market_ticker, is_live, direction, edge_at_entry, 
           timestamp, event_slug
    FROM trades 
    ORDER BY timestamp DESC
    LIMIT 20
''')

rows = cursor.fetchall()
print("=== 最近20笔交易的 edge 分布 ===\n")
print(f"{'ID':<5} {'类型':<8} {'方向':<6} {'Edge':<10} {'是否>=7%':<12} {'Slug':<40}")
print("-" * 100)

for row in rows:
    trade_id = row[0]
    is_live = "实盘" if row[2] else "模拟"
    direction = row[3]
    edge = row[4]
    slug = row[6]
    
    passes = "YES" if abs(edge) >= 0.07 else "NO"
    
    print(f"{trade_id:<5} {is_live:<8} {direction:<6} {edge:>+7.3%}   {passes:<12} {slug[:40]}")

print("\n=== 统计 ===\n")
cursor.execute('SELECT COUNT(*), AVG(edge_at_entry), MIN(edge_at_entry), MAX(edge_at_entry) FROM trades')
stats = cursor.fetchone()
print(f"总交易数: {stats[0]}")
print(f"平均 Edge: {stats[1]:.3%}")
print(f"最小 Edge: {stats[2]:.3%}")
print(f"最大 Edge: {stats[3]:.3%}")

cursor.execute('SELECT COUNT(*) FROM trades WHERE is_live=0')
sim_count = cursor.fetchone()[0]
cursor.execute('SELECT COUNT(*) FROM trades WHERE is_live=1')
live_count = cursor.fetchone()[0]

print(f"\n模拟交易: {sim_count}")
print(f"实盘交易: {live_count}")

print("\n=== 为什么 edge 都是负数？===")
print("原因: INVERT_SIGNAL=True 反转了信号方向")
print("当模型说 UP 但被反转为 DOWN 时，edge 会变成负数")
print("但开单条件用的是 abs(edge)，所以负数 edge 也能开单")
print("\n示例: 如果模型算出 edge=+10%，反转后变成 edge=-10%")
print("      但 abs(-10%) = 10% >= 7%，所以仍然会开单")

conn.close()
