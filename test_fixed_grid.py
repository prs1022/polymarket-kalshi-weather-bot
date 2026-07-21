#!/usr/bin/env python3
"""测试修复后的网格"""

current_price = 0.49
GRID_LOWER_BOUND = 0.20

# 旧逻辑：固定下限
old_extreme = GRID_LOWER_BOUND
old_range = current_price - old_extreme

# 新逻辑：动态下限
new_extreme = max(current_price * 0.85, GRID_LOWER_BOUND)
new_range = current_price - new_extreme

fib = [1, 1, 2]
fib_sum = 4

print("🔧 网格修复对比")
print("=" * 80)

print(f"\n【旧逻辑 - 固定下限】")
print(f"  当前价: {current_price:.2f} ({current_price*100:.0f}¢)")
print(f"  下限: {old_extreme:.2f} ({old_extreme*100:.0f}¢) - 固定值")
print(f"  范围: {old_range*100:.0f}¢ ({old_range/current_price*100:.0f}%)")
print(f"\n  生成的网格:")
for i in range(3):
    cumulative = sum(fib[:i+1])
    price = current_price - (cumulative / fib_sum) * old_range
    print(f"    Level {i}: {price:.2f} ({price*100:3.0f}¢) - 距当前 {(current_price-price)/current_price*100:4.0f}%")

print(f"\n【新逻辑 - 动态下限 (当前价×0.85)】")
print(f"  当前价: {current_price:.2f} ({current_price*100:.0f}¢)")
print(f"  下限: {new_extreme:.2f} ({new_extreme*100:.0f}¢) - 动态计算")
print(f"  范围: {new_range*100:.0f}¢ ({new_range/current_price*100:.0f}%)")
print(f"\n  生成的网格:")
for i in range(3):
    cumulative = sum(fib[:i+1])
    price = current_price - (cumulative / fib_sum) * new_range
    print(f"    Level {i}: {price:.2f} ({price*100:3.0f}¢) - 距当前 {(current_price-price)/current_price*100:4.0f}%")

print(f"\n【对比】")
print(f"  {'':15} | 旧逻辑 | 新逻辑 | 改进")
print(f"  " + "-" * 55)
old_0 = current_price - (1/4) * old_range
new_0 = current_price - (1/4) * new_range
print(f"  Level 0 价格  | {old_0*100:3.0f}¢   | {new_0*100:3.0f}¢   | +{(new_0-old_0)*100:.0f}¢")

old_1 = current_price - (2/4) * old_range
new_1 = current_price - (2/4) * new_range
print(f"  Level 1 价格  | {old_1*100:3.0f}¢   | {new_1*100:3.0f}¢   | +{(new_1-old_1)*100:.0f}¢")

print(f"\n  成交可能性:")
market_price = 0.47  # 实际市场价 (DOWN token)
print(f"    市场价: {market_price*100:.0f}¢")
print(f"    旧逻辑 Level 0 ({old_0*100:.0f}¢): {'❌ 太低' if old_0 < market_price * 0.9 else '✅ 可能成交'}")
print(f"    新逻辑 Level 0 ({new_0*100:.0f}¢): {'✅ 很可能成交' if new_0 >= market_price * 0.95 else '⚠️ 需要回调'}")

print(f"\n【✅ 修复效果】")
print(f"  1. 网格范围从 {old_range/current_price*100:.0f}% 缩小到 {new_range/current_price*100:.0f}%")
print(f"  2. Level 0 从 {old_0*100:.0f}¢ 提高到 {new_0*100:.0f}¢ (+{(new_0-old_0)*100:.0f}¢)")
print(f"  3. 更贴近市场价，成交概率大幅提高")
print(f"  4. 仍保留'下跌时分批买入'的策略，但范围更合理（15%）")
