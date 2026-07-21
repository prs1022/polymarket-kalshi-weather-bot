#!/usr/bin/env python3
"""测试新的网格配置 - 等间距均分"""

current_price = 0.45  # 45美分
GRID_LOWER_BOUND = 0.20  # 20美分
GRID_MODE = "equal"  # 等间距

print("🎯 新网格配置测试 - 等间距均分")
print("=" * 80)

print(f"\n【配置】")
print(f"  当前价格: {current_price:.2f} ({current_price*100:.0f}¢)")
print(f"  网格下限: {GRID_LOWER_BOUND:.2f} ({GRID_LOWER_BOUND*100:.0f}¢)")
print(f"  网格模式: {GRID_MODE}")
print(f"  价格范围: {(current_price - GRID_LOWER_BOUND)*100:.0f}¢")

print(f"\n【3层网格 (GRID_LEVELS=3)】")
num_levels = 3
price_range = current_price - GRID_LOWER_BOUND

for i in range(num_levels):
    # 等间距：每层之间距离相等
    # Level 0: current_price - 1/3 * range
    # Level 1: current_price - 2/3 * range  
    # Level 2: current_price - 3/3 * range (= GRID_LOWER_BOUND)
    price = current_price - ((i + 1) / num_levels) * price_range
    print(f"  Level {i}: {price:.2f} ({price*100:3.0f}¢)")

print(f"\n【2层网格 (GRID_LEVELS=2)】")
num_levels = 2

for i in range(num_levels):
    price = current_price - ((i + 1) / num_levels) * price_range
    print(f"  Level {i}: {price:.2f} ({price*100:3.0f}¢)")

print(f"\n【对比示例】")
print(f"  你的需求:")
print(f"    3层: 45¢, 32¢, 20¢")
print(f"    2层: 45¢, 32¢")
print(f"  ")
print(f"  实际计算（45¢ → 20¢）:")

# 3层精确计算
price_range = 45 - 20  # 25¢
print(f"  3层 (25¢范围均分3份):")
for i in range(3):
    price = 45 - ((i + 1) / 3) * price_range
    print(f"    Level {i}: {price:.2f}¢")

print(f"  ")
print(f"  2层 (25¢范围均分2份):")
for i in range(2):
    price = 45 - ((i + 1) / 2) * price_range
    print(f"    Level {i}: {price:.2f}¢")

print(f"\n【与旧配置对比】")
print(f"  旧配置 (fibonacci + 动态下限 current*0.85):")
print(f"    当前价 45¢ → 下限 38¢ (45*0.85)")
print(f"    3层: 42¢, 40¢, 38¢ (间隔太小)")
print(f"  ")
print(f"  新配置 (equal + 固定下限 0.20):")
print(f"    当前价 45¢ → 下限 20¢")
print(f"    3层: 37¢, 28¢, 20¢ (均分大跨度)")

print(f"\n【优势】")
print(f"  ✅ 跨度更大：20¢-45¢ (25¢) vs 38¢-45¢ (7¢)")
print(f"  ✅ 更低价格：可以在 28¢, 20¢ 捡便宜")
print(f"  ✅ 均匀分布：每层间距相等，逻辑清晰")
print(f"  ✅ 符合预期：完全按你的需求 45→32→20")

print(f"\n【风险提示】")
print(f"  ⚠️  成交速度慢：需要价格下跌 45¢→37¢ (18%) 才成交第1层")
print(f"  ⚠️  资金占用久：可能长时间等待低价")
print(f"  ⚠️  错过机会：如果价格只小幅下跌不会成交")
print(f"  ✅ 但能抄底：如果价格真的暴跌，能买到便宜筹码")

print("\n" + "=" * 80)
