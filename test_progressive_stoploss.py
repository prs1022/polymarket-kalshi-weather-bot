#!/usr/bin/env python3
"""测试渐进式止损逻辑"""

STOP_LOSS_OFFSET = 0.05  # 5美分

print("🎯 渐进式止损逻辑测试")
print("=" * 80)

print("\n【配置】")
print(f"  止损加价: {STOP_LOSS_OFFSET:.2f} (5美分，覆盖手续费)")
print(f"  策略: 每成交一层，更新止损价 = 平均成本 + 5¢")

print("\n【场景: 3层网格 - 49¢, 34¢, 20¢】")
print("\n时间线：")
print("-" * 80)

# 初始状态
print("\nT+0: 开仓，挂网格单")
print("  Level 0: 49¢ (pending)")
print("  Level 1: 34¢ (pending)")
print("  Level 2: 20¢ (pending)")
print("  止损单: 无")

# 第1层成交
print("\nT+60s: Level 0 成交 @ 49¢")
filled_prices = [0.49]
filled_shares = [5.0]
avg_cost = sum(p * s for p, s in zip(filled_prices, filled_shares)) / sum(filled_shares)
stop_loss = avg_cost + STOP_LOSS_OFFSET

print(f"  成交: 49¢ × 5份 = $2.45")
print(f"  平均成本: {avg_cost:.3f} ({avg_cost*100:.0f}¢)")
print(f"  ✅ 挂止损单: {stop_loss:.3f} ({stop_loss*100:.0f}¢) = 成本 + 5¢")
print(f"  状态: Level 0 (filled), Level 1 (pending), Level 2 (pending)")

# 第2层成交
print("\nT+120s: Level 1 成交 @ 34¢")
filled_prices.append(0.34)
filled_shares.append(5.0)
old_avg = avg_cost
old_stop = stop_loss
avg_cost = sum(p * s for p, s in zip(filled_prices, filled_shares)) / sum(filled_shares)
stop_loss = avg_cost + STOP_LOSS_OFFSET

print(f"  成交: 34¢ × 5份 = $1.70")
print(f"  平均成本: {old_avg:.3f} → {avg_cost:.3f} ({avg_cost*100:.0f}¢)")
print(f"  计算: (49×5 + 34×5) / 10 = {avg_cost:.3f}")
print(f"  ✅ 更新止损: {old_stop:.3f} → {stop_loss:.3f} ({stop_loss*100:.0f}¢)")
print(f"  状态: Level 0 (filled), Level 1 (filled), Level 2 (pending)")

# 第3层成交
print("\nT+180s: Level 2 成交 @ 20¢")
filled_prices.append(0.20)
filled_shares.append(5.0)
old_avg = avg_cost
old_stop = stop_loss
avg_cost = sum(p * s for p, s in zip(filled_prices, filled_shares)) / sum(filled_shares)
stop_loss = avg_cost + STOP_LOSS_OFFSET

print(f"  成交: 20¢ × 5份 = $1.00")
print(f"  平均成本: {old_avg:.3f} → {avg_cost:.3f} ({avg_cost*100:.0f}¢)")
print(f"  计算: (49×5 + 34×5 + 20×5) / 15 = {avg_cost:.3f}")
print(f"  ✅ 更新止损: {old_stop:.3f} → {stop_loss:.3f} ({stop_loss*100:.0f}¢)")
print(f"  状态: 全部成交")

print("\n" + "=" * 80)
print("\n【对比：旧逻辑 vs 新逻辑】")
print("-" * 80)

print("\n旧逻辑（全部成交才挂止损）:")
print("  T+0   - T+180s: 无止损保护 ❌")
print("  T+180s: 挂止损 @ 34¢ (平均成本，无加价) ⚠️")
print("  风险: 前180秒无保护，且保本止损不覆盖手续费")

print("\n新逻辑（渐进式止损）:")
print("  T+60s:  挂止损 @ 54¢ ✅ (第1层成交)")
print("  T+120s: 更新 @ 47¢ ✅ (第2层成交)")
print("  T+180s: 更新 @ 39¢ ✅ (第3层成交)")
print("  优势: 每层成交立即保护，且覆盖手续费 (+5¢)")

print("\n" + "=" * 80)
print("\n【止损单成交场景】")
print("-" * 80)

print("\n场景1: 价格反弹 (部分成交后)")
print("  T+60s:  Level 0 成交 @ 49¢, 挂止损 @ 54¢")
print("  T+90s:  价格反弹到 54¢")
print("  结果:   ✅ 止损单成交，盈利 +$0.25 (5¢×5份)")
print("  说明:   快速获利，避免回吐")

print("\n场景2: 价格继续下跌")
print("  T+60s:  Level 0 成交 @ 49¢, 挂止损 @ 54¢")
print("  T+90s:  价格跌到 45¢ (止损未触发)")
print("  T+120s: Level 1 成交 @ 34¢, 更新止损 @ 47¢")
print("  T+150s: 价格反弹到 47¢")
print("  结果:   ✅ 止损单成交，盈利 +$0.65")
print("  说明:   摊低成本后的反弹也能获利")

print("\n场景3: 价格暴跌")
print("  T+60s:  Level 0 成交 @ 49¢, 挂止损 @ 54¢")
print("  T+120s: Level 1 成交 @ 34¢, 更新止损 @ 47¢")
print("  T+180s: Level 2 成交 @ 20¢, 更新止损 @ 39¢")
print("  T+240s: 价格在 25¢ 震荡 (止损未触发)")
print("  T+300s: 市场结算")
print("  结果:   按实际结果结算（UP=1 或 DOWN=0）")
print("  说明:   价格未反弹，持有到结算")

print("\n" + "=" * 80)
print("\n【手续费覆盖说明】")
print("-" * 80)

print("\nPolymarket 手续费:")
print("  Maker (挂单): 0%")
print("  Taker (吃单): 0%")
print("  但有 Gas 费和滑点")

print("\n为什么加 5¢？")
print("  1. 覆盖 Gas 费 (~2-3¢)")
print("  2. 覆盖滑点 (~1-2¢)")
print("  3. 保证小幅盈利 (~1-2¢)")
print("  总计: 5¢ 缓冲较为安全")

print("\n不加 5¢ 的风险:")
print("  止损价 = 成本价")
print("  卖出后: 收入 - Gas - 滑点 < 成本")
print("  结果: 名义保本，实际小亏 ❌")

print("\n加 5¢ 的好处:")
print("  止损价 = 成本 + 5¢")
print("  卖出后: 收入 - 成本 - 费用 ≈ 1-2¢")
print("  结果: 真正小盈 ✅")

print("\n" + "=" * 80)
print("\n【总结】")
print("-" * 80)

print("\n✅ 新逻辑优势:")
print("  1. 渐进式保护: 每层成交立即挂止损")
print("  2. 覆盖成本: +5¢ 确保盈利覆盖手续费")
print("  3. 动态调整: 随着成本降低，止损也降低")
print("  4. 灵活退出: 价格反弹时能快速获利")

print("\n⚠️  注意事项:")
print("  1. 止损价会随成本下降而下降")
print("  2. 如果价格持续下跌，止损可能不触发")
print("  3. 最后还是按市场实际结果结算")
print("  4. 这是风控工具，不是盈利保证")

print("\n💡 最佳场景:")
print("  价格下跌 → 网格分批买入 → 摊低成本")
print("  价格反弹 → 触发止损 → 小幅获利退出")
print("  避免: 买在高位后价格持续下跌的亏损")

print("\n" + "=" * 80)
