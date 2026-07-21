#!/usr/bin/env python3
"""简单测试网格生成逻辑"""

# 模拟网格生成
current_price = 0.49  # 49¢
GRID_LOWER_BOUND = 0.20  # 20¢
GRID_LEVELS = 3

print("🔍 网格生成逻辑分析")
print("=" * 80)

print(f"\n【配置】")
print(f"  当前价格: {current_price:.2f} ({current_price*100:.0f}美分)")
print(f"  网格下限: {GRID_LOWER_BOUND:.2f} ({GRID_LOWER_BOUND*100:.0f}美分)")
print(f"  网格层数: {GRID_LEVELS}")
print(f"  价格范围: {(current_price - GRID_LOWER_BOUND)*100:.0f}美分")

# 斐波那契序列
fib = [1, 1, 2]
fib_sum = sum(fib)  # 4

print(f"\n【斐波那契分布计算】")
for i in range(GRID_LEVELS):
    cumulative = sum(fib[:i+1])
    ratio = cumulative / fib_sum
    price = current_price - ratio * (current_price - GRID_LOWER_BOUND)
    print(f"  Level {i}: Fib累计={cumulative}/{fib_sum}={ratio:.3f} → 价格={price:.2f} ({price*100:.0f}¢)")

print(f"\n【问题】")
print(f"  市场当前价格: 53¢ (订单簿买1)")
print(f"  交易方向: DOWN")
print(f"  DOWN token 价格: 47¢ (1 - 0.53)")
print(f"  记录的入场价: 49¢")
print(f"  生成的网格:")
print(f"    Level 0: 34¢")
print(f"    Level 1: 20¢")
print(f"  ")
print(f"  ❌ 34¢ 远低于当前价 47¢，很难成交！")

print(f"\n【根本原因】")
print(f"  1. GRID_LOWER_BOUND = 20¢ (固定值) 太低")
print(f"  2. 49¢ - 20¢ = 29¢ 跨度太大")
print(f"  3. 斐波那契把第0层推到 49¢ - 25% * 29¢ = 34¢")
print(f"  4. 网格设计初衷是'在下跌时分批买入'")
print(f"     但 49¢ → 34¢ 需要下跌 {(49-34)/49*100:.0f}%！")

print(f"\n【合理的网格应该是】")
# 使用动态下限
better_lower = current_price * 0.85  # 当前价的85%
print(f"  动态下限: {current_price:.2f} * 0.85 = {better_lower:.2f} ({better_lower*100:.0f}¢)")
print(f"  价格范围: {(current_price - better_lower)*100:.0f}美分 (仅{(current_price - better_lower)/current_price*100:.0f}%)")

print(f"\n  重新计算网格:")
for i in range(GRID_LEVELS):
    cumulative = sum(fib[:i+1])
    ratio = cumulative / fib_sum
    price = current_price - ratio * (current_price - better_lower)
    print(f"    Level {i}: {price:.2f} ({price*100:.0f}¢)")

print(f"\n【✅ 解决方案】")
print(f"  方案1: 提高固定下限")
print(f"    GRID_LOWER_BOUND: 0.20 → 0.40 (40¢)")
print(f"  ")
print(f"  方案2: 使用动态下限（推荐）")
print(f"    extreme_price = current_price * 0.85  # 下跌15%范围")
print(f"    这样网格会跟随市场价格调整")
print(f"  ")
print(f"  方案3: 缩小网格层数")
print(f"    GRID_LEVELS: 3 → 2 (减少层数，收紧价格)")
