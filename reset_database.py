#!/usr/bin/env python3
"""重置数据库 - 清空所有交易数据，保留表结构"""
import sqlite3
from datetime import datetime

print("=" * 80)
print("🔄 数据库重置工具")
print("=" * 80)

# 连接数据库
conn = sqlite3.connect('tradingbot.db')
cursor = conn.cursor()

# 1. 统计当前数据
print("\n【重置前数据统计】")
cursor.execute('SELECT COUNT(*) FROM trades')
trades_count = cursor.fetchone()[0]
print(f"  交易记录: {trades_count} 条")

cursor.execute('SELECT COUNT(*) FROM grid_orders')
grid_count = cursor.fetchone()[0]
print(f"  网格订单: {grid_count} 条")

cursor.execute('SELECT COUNT(*) FROM signals')
signals_count = cursor.fetchone()[0]
print(f"  信号记录: {signals_count} 条")

cursor.execute('SELECT COUNT(*) FROM ai_logs')
ai_logs_count = cursor.fetchone()[0]
print(f"  AI日志: {ai_logs_count} 条")

cursor.execute('SELECT COUNT(*) FROM scan_logs')
scan_logs_count = cursor.fetchone()[0]
print(f"  扫描日志: {scan_logs_count} 条")

cursor.execute('SELECT COUNT(*) FROM btc_price_snapshots')
btc_snapshots_count = cursor.fetchone()[0]
print(f"  BTC价格快照: {btc_snapshots_count} 条")

cursor.execute('SELECT COUNT(*) FROM bot_state')
bot_state_count = cursor.fetchone()[0]
print(f"  机器人状态: {bot_state_count} 条")

# 2. 查看当前 bot_state
print("\n【当前机器人状态】")
cursor.execute('SELECT id, is_live, bankroll, total_trades, winning_trades, total_pnl FROM bot_state')
states = cursor.fetchall()
for state in states:
    state_type = "实盘" if state[1] else "模拟"
    print(f"  {state_type}: 资金${state[2]:.2f}, {state[3]}笔交易, {state[4]}笔盈利, 总P&L ${state[5]:.2f}")

# 3. 用户确认
print("\n" + "=" * 80)
print("⚠️  警告：此操作将清空所有交易数据！")
print("=" * 80)
print("\n即将执行的操作：")
print("  ✓ 删除所有交易记录")
print("  ✓ 删除所有网格订单")
print("  ✓ 删除所有信号记录")
print("  ✓ 删除所有AI调用日志")
print("  ✓ 删除所有扫描日志")
print("  ✓ 删除所有BTC价格快照")
print("  ✓ 重置机器人状态（模拟盘$10，实盘$0）")
print("\n  ✓ 保留：数据库备份已创建")

response = input("\n确认重置？输入 'YES' 继续: ")

if response != 'YES':
    print("\n❌ 已取消操作")
    conn.close()
    exit(0)

print("\n开始重置...")

# 4. 清空数据表
try:
    print("\n【清空数据】")
    
    cursor.execute('DELETE FROM trades')
    print(f"  ✓ 已清空 trades 表 ({trades_count} 条)")
    
    cursor.execute('DELETE FROM grid_orders')
    print(f"  ✓ 已清空 grid_orders 表 ({grid_count} 条)")
    
    cursor.execute('DELETE FROM signals')
    print(f"  ✓ 已清空 signals 表 ({signals_count} 条)")
    
    cursor.execute('DELETE FROM ai_logs')
    print(f"  ✓ 已清空 ai_logs 表 ({ai_logs_count} 条)")
    
    cursor.execute('DELETE FROM scan_logs')
    print(f"  ✓ 已清空 scan_logs 表 ({scan_logs_count} 条)")
    
    cursor.execute('DELETE FROM btc_price_snapshots')
    print(f"  ✓ 已清空 btc_price_snapshots 表 ({btc_snapshots_count} 条)")
    
    # 5. 重置 bot_state
    print("\n【重置机器人状态】")
    
    # 模拟盘：重置为 $10
    cursor.execute('''
        UPDATE bot_state 
        SET bankroll = 10.0,
            total_trades = 0,
            winning_trades = 0,
            total_pnl = 0.0,
            last_run = NULL,
            is_running = 0
        WHERE is_live = 0
    ''')
    print("  ✓ 模拟盘状态已重置: 资金$10, 0笔交易, $0 P&L")
    
    # 实盘：重置为 $0（等待同步实际余额）
    cursor.execute('''
        UPDATE bot_state 
        SET bankroll = 0.0,
            total_trades = 0,
            winning_trades = 0,
            total_pnl = 0.0,
            last_run = NULL,
            is_running = 0
        WHERE is_live = 1
    ''')
    print("  ✓ 实盘状态已重置: 资金$0, 0笔交易, $0 P&L")
    
    # 6. 提交事务
    conn.commit()
    print("\n" + "=" * 80)
    print("✅ 数据库重置完成！")
    print("=" * 80)
    
    # 7. 验证
    print("\n【重置后数据统计】")
    cursor.execute('SELECT COUNT(*) FROM trades')
    print(f"  交易记录: {cursor.fetchone()[0]} 条")
    cursor.execute('SELECT COUNT(*) FROM grid_orders')
    print(f"  网格订单: {cursor.fetchone()[0]} 条")
    cursor.execute('SELECT COUNT(*) FROM signals')
    print(f"  信号记录: {cursor.fetchone()[0]} 条")
    
    print("\n【新的机器人状态】")
    cursor.execute('SELECT id, is_live, bankroll, total_trades, winning_trades, total_pnl FROM bot_state')
    states = cursor.fetchall()
    for state in states:
        state_type = "实盘" if state[1] else "模拟"
        print(f"  {state_type}: 资金${state[2]:.2f}, {state[3]}笔交易, {state[4]}笔盈利, 总P&L ${state[5]:.2f}")
    
    print("\n📝 提示：")
    print("  1. 数据库备份文件: tradingbot.db.backup.* ")
    print("  2. 重启程序后将从新的初始状态开始")
    print("  3. 实盘资金将在下次启动时从USDC余额同步")
    print("  4. 模拟盘从 $10 开始（新配置）")
    
except Exception as e:
    print(f"\n❌ 重置失败: {e}")
    conn.rollback()
finally:
    conn.close()

print("\n" + "=" * 80)
