#!/usr/bin/env python3
"""测试网格生成逻辑"""
import sys
sys.path.insert(0, '/Users/upuphone/project_ai/polymarket-kalshi-weather-bot')

from backend.core.grid import generate_fibonacci_grid
from backend.config import settings

print("🔍 网格生成逻辑测试")
print("=" * 80)

# 模拟实际情况
current_price = 0.49  # DOWN token 当前价格 49¢
budget = 1.0  # $1 预算

print(f"\n【输入参数】")
print(f"  当前价格: {current_price:.2f} ({current_price*100:.0f}美分)")
print(f"  预算: ${budget:.2f}")
print(f"  网格层数: {settings.GRID_LEVELS}")
print(f"  网格模式: {settings.GRID_MODE}")
print(f"  网格下限: {settings.GRID_LOWER_BOUND:.2f} ({settings.GRID_LOWER_BOUND*100:.0f}美分)")

# 生成网格
grid = generate_fibonacci_grid(
    current_price=current_price,
    budget=budget,
)

print(f"\n【生成的网格订单】")
print(f"  Level | 限价 | 份额 | 成本")
print(f"  " + "-" * 40)
for level in grid:
    print(f"  {level.level:5} | {level.limit_price:.2f} ({level.limit_price*100:3.0f}¢) | {level.shares:5.2f} | ${level.cost:5.2f}")

total_cost = sum(l.cost for l in grid)
total_shares = sum(l.shares for l in grid)
avg_price = total_cost / total_shares if total_shares > 0 else 0

print(f"\n【汇总】")
print(f"  总成本: ${total_cost:.2f}")
print(f"  总份额: {total_shares:.2f}")
print(f"  平均价格: {avg_price:.2f} ({avg_price*100:.0f}美分)")

print(f"\n【问题分析】")
print(f"  当前市场价: {current_price*100:.0f}美分")
print(f"  网格最高价: {grid[0].limit_price*100:.0f}美分")
print(f"  价格差距: {(current_price - grid[0].limit_price)*100:.0f}美分")
print(f"  ")
print(f"  ⚠️  问题：网格从 {current_price*100:.0f}¢ 向下到 {settings.GRID_LOWER_BOUND*100:.0f}¢")
print(f"  范围: {(current_price - settings.GRID_LOWER_BOUND)*100:.0f}美分 ({(current_price - settings.GRID_LOWER_BOUND)/current_price*100:.0f}%)")
print(f"  ")
print(f"  第0层: {current_price*100:.0f}¢ - {(1/3 * (current_price - settings.GRID_LOWER_BOUND))*100:.0f}¢ = {grid[0].limit_price*100:.0f}¢")
print(f"  第1层: {current_price*100:.0f}¢ - {(2/3 * (current_price - settings.GRID_LOWER_BOUND))*100:.0f}¢ = {grid[1].limit_price*100:.0f}¢")

print(f"\n【斐波那契分布】")
fib = [1, 1, 2]
fib_sum = sum(fib)
for i in range(3):
    cumulative = sum(fib[:i+1])
    ratio = cumulative / fib_sum
    price = current_price - ratio * (current_price - settings.GRID_LOWER_BOUND)
    print(f"  Level {i}: 累计 Fib {cumulative}/{fib_sum} = {ratio:.3f} → 价格 {price:.2f} ({price*100:.0f}¢)")

print(f"\n【根本原因】")
print(f"  1. 网格下限 GRID_LOWER_BOUND = {settings.GRID_LOWER_BOUND:.2f} (20美分) 太低")
print(f"  2. 当前价格 49¢ - 20¢ = 29¢ 的跨度太大")
print(f"  3. 斐波那契分布把订单往下推太多")
print(f"  4. 第0层就已经在 34¢，远低于当前 49¢")
print(f"  ")
print(f"  ✅ 解决方案：")
print(f"  - 提高 GRID_LOWER_BOUND: 0.20 → 0.40 (当前价-10%)")
print(f"  - 或使用动态下限: current_price * 0.90")
print(f"  - 网格应该在 49¢ → 44¢ 范围内，而不是 49¢ → 20¢")
