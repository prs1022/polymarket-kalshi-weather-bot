# 止损单缺失问题报告

## 🔴 问题描述

**市场:** btc-updown-5m-1784106900  
**类型:** 实盘交易  
**问题:** 网格订单已成交，但未挂出止损单  
**结果:** 亏损 $3

## 🔍 根本原因

### ❌ 程序未重启，仍在运行旧代码！

#### 证据1: 日志分析
```
日志文件: .run/logs/app.log
最近的网格成交日志: "Grid fills: 2 orders filled"
缺失: "渐进式止损" 相关日志 ❌
```

**说明:** 新代码有明确的"渐进式止损"日志输出，但日志中没有，证明程序还在用旧代码。

#### 证据2: 数据库状态
```
实盘 Trade ID: 11
  网格成本: $0.00  ← 应该有成本
  网格份额: 0.00   ← 应该有份额
  止损价: 未设置   ← 应该有止损

网格订单状态:
  Level 0: pending ← 实际可能已成交
  Level 1: pending ← 实际可能已成交
```

**说明:** 数据库状态未同步，说明程序没有正确检测到实盘成交。

#### 证据3: 旧代码逻辑
```python
# 旧代码 (你遇到的情况)
# 只有网格全部成交才设置止损
pending_count = sum(1 for o in all_grid if o.status == "pending")
if pending_count == 0 and trade.stop_loss_price is None:
    trade.stop_loss_price = round(trade.entry_price, 2)
```

**问题:** 
1. 如果网格部分成交 → 不设置止损
2. 如果网格成交检查失败 (status一直pending) → 不设置止损
3. 导致亏损时没有保护

## 📊 时间线重建

```
T+0  (09:10): 开仓 btc-updown-5m-1784106900
              挂实盘网格单:
              - Level 0: 34¢
              - Level 1: 20¢
              CLOB订单ID已记录 ✅

T+X  (09:10-09:15): 实盘订单在Polymarket成交
                     但程序未检测到 ❌
                     原因: 旧代码的问题或API查询失败

T+300 (09:15): 市场结算
               方向: DOWN
               结果: UP (价格上涨)
               P&L: -$1.00 × 3笔 = -$3.00
```

## 🐛 旧代码的多个问题

### 问题1: 实盘网格成交检查不可靠

```python
# scheduler.py 旧代码
for go in trade_grid:
    if not go.clob_order_id:
        continue  # 跳过
    
    status_info = executor.get_order_status(go.clob_order_id)
    # 如果API调用失败或返回错误，订单status保持pending
    # 导致永远检测不到成交
```

**问题:**
- 依赖 API 查询成功
- 如果 API 失败/超时，status不更新
- 没有重试机制
- 没有错误日志

### 问题2: 止损设置条件太严格

```python
# 旧代码：只有全部成交才设置止损
pending_count = sum(1 for o in all_grid if o.status == "pending")
if pending_count == 0 and trade.stop_loss_price is None:
    trade.stop_loss_price = ...
```

**问题:**
- 如果只成交了部分 → 没有止损
- 如果检测失败 (status=pending) → 没有止损
- 导致持仓无保护

### 问题3: 没有降级保护

**缺失:**
- 如果网格成交检查失败，没有备用方案
- 没有基于时间的强制止损
- 没有告警机制

## ✅ 新代码的修复

### 修复1: 渐进式止损

```python
# 新代码：每成交一层就设置止损
if settings.PROGRESSIVE_STOP_LOSS and trade.grid_filled_shares > 0:
    new_stop_loss = round(trade.entry_price + settings.STOP_LOSS_OFFSET, 2)
    
    if old_stop_loss is None or new_stop_loss > old_stop_loss:
        trade.stop_loss_price = new_stop_loss
        # 立即挂止损单
```

**优势:**
- 第1层成交 → 立即保护 ✅
- 不需要等全部成交
- 实时更新止损价

### 修复2: 覆盖手续费

```python
STOP_LOSS_OFFSET = 0.05  # 止损价 = 成本 + 5¢
```

**优势:**
- 覆盖 Gas 费 (2-3¢)
- 覆盖滑点 (1-2¢)
- 确保小盈不小亏

### 修复3: 动态更新

```python
# 每次网格成交都更新
if newly_filled:
    update_trade_from_grid(trade, all_grid)  # 更新平均成本
    # 更新止损价
    trade.stop_loss_price = trade.entry_price + 0.05
```

## 🚨 立即行动

### 1. 重启程序 ⚠️⚠️⚠️

```bash
# 停止当前进程
kill $(cat .run/trading-bot.pid)

# 重启
python backend/api/main.py
```

**必须重启！** 代码已修改但程序还在用旧版本。

### 2. 验证新代码生效

重启后查看日志应该有：
```
✅ "【模拟】渐进式止损 - 第1层成交"
✅ "【实盘】渐进式止损 - 第1层"
✅ "成本 xxx → 止损 yyy"
```

### 3. 监控下一笔交易

下一笔实盘交易应该：
- 网格第1层成交 → 立即挂止损 @ 成本+5¢
- 网格第2层成交 → 更新止损价
- 数据库 `stop_loss_price` 字段有值
- 日志有"渐进式止损"输出

## 📋 预防措施

### 短期 (立即)
1. ✅ 重启程序（使用新代码）
2. ✅ 验证日志输出
3. ✅ 监控下一笔交易

### 中期 (本周)
1. 添加监控告警
   - 实盘交易无止损 → 告警
   - 网格成交检查失败 → 告警
   - API 查询超时 → 告警

2. 添加降级保护
   - 如果API查询连续失败 → 使用模拟检查
   - 开仓后固定时间 (2分钟) 强制设置止损

3. 改进错误处理
   - 重试机制
   - 详细错误日志
   - 失败通知

### 长期 (本月)
1. 实盘交易仪表板
   - 实时显示订单状态
   - 止损单状态
   - 成交通知

2. 回测系统
   - 测试新代码
   - 验证止损逻辑
   - 避免生产问题

## 💡 经验教训

1. **代码修改后必须重启** ⚠️
   - Python不会自动reload
   - 进程一直用旧代码

2. **实盘API不可靠** ⚠️
   - 需要重试机制
   - 需要降级方案
   - 需要告警

3. **渐进式止损很重要** ✅
   - 早期保护
   - 降低风险
   - 覆盖成本

4. **监控和日志关键** ✅
   - 快速发现问题
   - 追踪执行情况
   - 优化策略

## 📞 如何避免再次发生

### 检查清单

每次代码修改后：
- [ ] 重启程序
- [ ] 查看启动日志
- [ ] 验证新功能日志
- [ ] 监控第1笔交易
- [ ] 确认数据库更新

### 监控指标

- 实盘交易数 vs 止损单数 (应该相等)
- 网格成交数 vs 数据库记录 (应该同步)
- API 查询成功率 (应该 >95%)
- 止损单挂单延迟 (应该 <10秒)

---

## 🎯 结论

**问题根源:** 程序未重启，仍在使用旧代码  
**直接原因:** 旧代码止损逻辑有缺陷  
**解决方案:** 重启程序，使用新的渐进式止损代码  
**预防措施:** 监控、告警、降级保护

**立即行动:** ⚠️ 重启程序！⚠️
