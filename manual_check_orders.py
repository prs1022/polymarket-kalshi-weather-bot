#!/usr/bin/env python3
"""手动查询实盘订单状态"""
import sys
sys.path.insert(0, '/Users/upuphone/project_ai/polymarket-kalshi-weather-bot')

import sqlite3
from backend.data.polymarket_executor import get_executor

conn = sqlite3.connect('tradingbot.db')
c = conn.cursor()

print("=" * 80)
print("🔍 手动查询实盘订单状态")
print("=" * 80)

# 获取executor
executor = get_executor()
print(f"\nExecutor状态: {'STUB模式 (模拟)' if executor.is_stub else 'LIVE模式 (实盘)'}")

# 查询实盘订单
c.execute('''
    SELECT go.trade_id, go.level, go.limit_price, go.shares, go.cost,
           go.status, go.clob_order_id,
           t.event_slug, t.direction
    FROM grid_orders go
    JOIN trades t ON go.trade_id = t.id
    WHERE t.event_slug = 'btc-updown-5m-1784106900' AND t.is_live = 1
    ORDER BY go.level
''')

orders = c.fetchall()

if not orders:
    print("\n❌ 未找到实盘订单")
    conn.close()
    exit(1)

print(f"\n找到 {len(orders)} 个实盘网格订单:")
print()

for o in orders:
    trade_id, level, limit_price, shares, cost, db_status, clob_id, slug, direction = o
    
    print(f"Level {level}: {limit_price:.2f} ({limit_price*100:.0f}¢)")
    print(f"  数据库状态: {db_status}")
    print(f"  CLOB订单ID: {clob_id}")
    
    if not executor.is_stub and clob_id:
        try:
            print(f"  查询实盘状态...")
            status_info = executor.get_order_status(clob_id)
            
            api_status = status_info.get("status", "unknown")
            filled_size = status_info.get("filled_size", 0)
            filled_price = status_info.get("filled_price", 0)
            
            print(f"  ✅ CLOB API状态: {api_status}")
            print(f"     成交份额: {filled_size:.2f}")
            print(f"     成交价格: {filled_price:.3f}")
            
            if api_status in ("matched", "filled"):
                print(f"  ⚠️  订单已成交，但数据库状态是 {db_status}！")
                print(f"     问题: 程序未同步实盘订单状态")
            elif db_status == "filled":
                print(f"  ⚠️  数据库显示已成交，但API显示 {api_status}")
        except Exception as e:
            print(f"  ❌ 查询失败: {e}")
    elif executor.is_stub:
        print(f"  ⚠️  Executor在STUB模式，无法查询真实状态")
    
    print()

print("=" * 80)
print("\n【诊断结果】")

if executor.is_stub:
    print("\n❌ 根本问题: Executor 在 STUB 模式！")
    print("   原因可能:")
    print("   1. 环境变量未配置 POLYMARKET_PRIVATE_KEY")
    print("   2. py-clob-client-v2 未安装")
    print("   3. API初始化失败")
    print()
    print("   在STUB模式下:")
    print("   - 挂单会创建假的订单ID (STUB_xxxxx)")
    print("   - get_order_status() 永远返回 pending")
    print("   - 无法检测真实成交")
    print("   - 但你在Polymarket网页手动挂的单会成交")
    print("   - 程序完全不知道这些成交")
else:
    print("\n✅ Executor 在 LIVE 模式")
    print("   需要检查:")
    print("   1. check_grid_fills_job() 是否定期运行")
    print("   2. 查询到的订单状态是什么")
    print("   3. 是否有错误日志")

conn.close()
