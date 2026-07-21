# 实盘订单追踪问题分析

## 问题描述

用户报告：市场 `btc-updown-5m-1784170200` 在Polymarket网页上显示3层网格已成交，但是：
1. 数据库中订单状态仍显示为 `pending`  
2. 没有挂出止损单
3. 程序没有检测到订单成交

## 根本原因

**CLOB API `/data/order/{order_id}` 端点返回 `None`**

从日志可以看到：
```
INFO:httpx:HTTP Request: GET https://clob.polymarket.com/data/order/0x... "HTTP/2 200 OK"
ERROR:backend.data.polymarket_executor:[LIVE] get_order_status failed: 'NoneType' object has no attribute 'get'
```

HTTP状态码是200（成功），但响应体是 `null`，这导致：
- `client.get_order(order_id)` 返回 `None`
- 代码尝试调用 `None.get()` 时崩溃
- 订单永远不会被标记为成交

## 为什么API返回None

### 可能原因：

1. **订单数据过期清理**（最可能）
   - CLOB API通常只保留**活跃订单**的数据
   - 订单成交后，数据在5-10分钟内从API清除
   - 这解释了为什么旧订单全部返回None

2. **API权限问题**
   - 可能需要特定权限才能查询历史订单
   - 但这通常会返回403/401，不是200+null

3. **订单ID格式或钱包不匹配**
   - 订单ID错误会导致查不到数据
   - 但从日志看订单ID是正确格式的

## 数据库证据

### Trade #19 (实盘, 市场 btc-updown-5m-1784170200):
```sql
id: 19
is_live: 1
entry_price: 0.5
shares: 2.0
stop_loss_price: NULL  ← 没有设置止损！
grid_filled_shares: 0.0  ← 数据库认为没有成交
grid_filled_cost: 0.0
```

### Grid Orders for Trade #19:
```
Order #42: Level 0, Price $0.40, 5 shares, Status: pending, CLOB ID: 0x0fffb62d...
Order #43: Level 1, Price $0.30, 5 shares, Status: pending, CLOB ID: 0x58054ad7...
Order #44: Level 2, Price $0.20, 5 shares, Status: pending, CLOB ID: 0x56af0067...
```

所有订单都有有效的 `clob_order_id`，但数据库状态是 `pending`（未成交）。

**然而用户在Polymarket网页看到它们已经成交**，这说明：
- 订单确实成交了
- 但程序无法从API获取成交信息
- 数据库没有同步实际状态

## 已实施的修复

### 1. 处理None响应 ✅
修改了 `polymarket_executor.py` 的 `get_order_status()`:
```python
if order is None:
    logger.warning(f"[LIVE] Order {order_id[:16]}... not found in CLOB API (returned None)")
    return {"status": "not_found", "filled_size": 0, "filled_price": 0}
```

这防止了崩溃，但**不能解决检测成交的问题**。

## 需要的解决方案

### 方案A: 使用不同的API端点（推荐）

CLOB API应该有其他端点可以查询：
1. **Get Fills/Trades** - 查询用户的成交记录（而不是订单状态）
2. **Get Orders by Market** - 按市场查询所有订单
3. **WebSocket订单更新** - 实时监听订单状态变化

需要查阅 `py-clob-client-v2` 文档找到正确的方法。

### 方案B: 增加查询频率

当前每10秒检查一次，可能订单在两次检查之间成交并被清理。
- 改为每2-3秒检查一次
- 但这只是缓解，不是根本解决

### 方案C: 混合追踪（最可靠）

1. 实时查询CLOB订单状态（现有方法）
2. 同时查询市场价格
3. 如果订单长时间pending且市场价格已到达limit_price，推定为成交
4. 查询余额变化作为确认

### 方案D: 保存订单响应

在下单后立即保存完整的订单信息到数据库：
```python
order_response = executor.place_limit_buy(...)
# 保存 order_response 的完整JSON到数据库
```

这样即使API清理了数据，我们也有备份。

## 临时workaround

用户可以手动检查成交并在数据库中更新：

```sql
-- 检查实盘网格订单
SELECT * FROM grid_orders WHERE clob_order_id IS NOT NULL AND status = 'pending';

-- 如果确认已成交，手动更新：
UPDATE grid_orders SET status = 'filled', filled_at = datetime('now'), fill_price = limit_price
WHERE id = 42;  -- 对每个成交的订单执行

-- 然后触发止损逻辑（需要重启程序或手动设置）
```

## 下一步行动

1. ✅ 修复None崩溃问题（已完成）
2. ⏳ 研究py-clob-client-v2文档，找到查询成交记录的API
3. ⏳ 实现替代的订单追踪机制
4. ⏳ 添加余额同步作为成交确认
5. ⏳ 测试新的追踪机制是否能正确检测成交

## 相关文件

- `backend/data/polymarket_executor.py` - CLOB API接口
- `backend/core/scheduler.py` - 订单成交检查逻辑（`check_grid_fills_job`）
- Database: `tradingbot.db` - trades和grid_orders表

## 日志关键词

- `[LIVE] get_order_status failed` - 订单查询失败
- `【实盘】渐进式止损` - 应该出现但没有出现
- `Grid fill` - 订单成交记录
