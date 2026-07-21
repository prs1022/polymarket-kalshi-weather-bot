# 实盘订单追踪修复方案

## 问题回顾

用户报告市场 `btc-updown-5m-1784170200` 的实盘订单已在Polymarket网页上成交，但：
- 程序数据库显示订单仍为 `pending`
- 没有挂出止损单
- 日志显示大量 `get_order_status failed: 'NoneType' object has no attribute 'get'` 错误

**根本原因**: CLOB API的 `/data/order/{order_id}` 端点在订单成交后很快清理数据，返回 `null`，导致程序无法检测订单成交。

## 解决方案

### 方案：使用 `/data/trades` 端点

根据[Polymarket API文档](https://docs.polymarket.com/api-reference/trade/get-trades)，有一个**专门用于查询成交记录的端点**：

```
GET https://clob.polymarket.com/data/trades
```

这个端点返回用户的**实际成交记录**（fills），比订单状态数据保留时间更长，更可靠。

### 实施的修改

#### 1. 新增 `get_recent_trades()` 方法

在 `backend/data/polymarket_executor.py` 中添加：

```python
def get_recent_trades(self, asset_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get recent trades (fills) for the authenticated user.
    
    Returns:
        List of trade dicts with keys:
            - taker_order_id: Order ID that created this fill
            - price: Fill price
            - size: Fill size  
            - match_time: Unix timestamp
            - status: TRADE_STATUS_CONFIRMED, etc.
    """
```

这个方法调用 `self._client.get_trades()` 获取最近的成交记录。

#### 2. 更新订单检测逻辑

在 `backend/core/scheduler.py` 的 `check_grid_fills_job()` 中：

**旧逻辑**（有问题）：
```python
for go in trade_grid:
    status_info = executor.get_order_status(go.clob_order_id)  # 返回None
    if status_info["status"] in ("matched", "filled"):
        go.status = "filled"
```

**新逻辑**（已修复）：
```python
# 1. 先获取所有最近的成交记录
recent_trades = executor.get_recent_trades(limit=200)

# 2. 构建订单ID -> 成交信息的映射
fills_map = {}
for rt in recent_trades:
    order_id = rt.get("taker_order_id")
    if order_id and rt.get("status") == "TRADE_STATUS_CONFIRMED":
        fills_map[order_id] = {
            "price": float(rt.get("price", 0)),
            "size": float(rt.get("size", 0)) / 1e6,
            "match_time": rt.get("match_time"),
        }

# 3. 检查每个pending订单是否在成交记录中
for go in trade_grid:
    fill_info = fills_map.get(go.clob_order_id)
    if fill_info:
        go.status = "filled"
        go.fill_price = round(fill_info["price"], 2)
        go.filled_at = datetime.utcnow()
    else:
        # 备用：仍然尝试查询单个订单状态（应对极新的订单）
        status_info = executor.get_order_status(go.clob_order_id)
        # ...
```

### 优势

1. **更可靠**: 成交记录保留时间比订单状态长
2. **更高效**: 一次API调用获取所有成交，而不是每个订单单独查询
3. **双重保险**: 先查成交记录，查不到再fallback到订单状态
4. **避免崩溃**: 即使返回None也有妥善处理

## 测试方法

### 方法1：观察新订单

1. 重启程序使新代码生效
2. 等待程序开新的实盘订单
3. 在Polymarket网页监控订单成交
4. 观察程序日志：

```bash
# 应该看到这些日志
[LIVE] Order 0x0fffb62d... filled @ $0.400
【实盘】渐进式止损 - 第1层: btc-updown-5m-XXX sell 5 @ 0.450
【实盘】Grid fill: btc-updown-5m-XXX UP 1 orders filled
```

5. 检查数据库：

```sql
SELECT id, trade_id, level, limit_price, status, filled_at, clob_order_id 
FROM grid_orders 
WHERE trade_id = (SELECT MAX(id) FROM trades WHERE is_live = 1)
ORDER BY level;
```

应该看到 `status = 'filled'` 和 `filled_at` 有值。

### 方法2：手动调用API测试

创建测试脚本验证 `get_recent_trades()` 能否工作：

```python
from backend.data.polymarket_executor import get_executor

executor = get_executor()
trades = executor.get_recent_trades(limit=10)

for t in trades:
    print(f"Order: {t.get('taker_order_id')[:16]}...")
    print(f"  Price: {t.get('price')}")
    print(f"  Size: {float(t.get('size', 0)) / 1e6}")
    print(f"  Status: {t.get('status')}")
    print()
```

## 已知限制

1. **API调用限制**: 如果`get_trades()`方法在py-clob-client-v2中不存在或名称不同，需要查阅文档调整
2. **极新的订单**: 刚成交的订单可能还未出现在trades列表中（延迟几秒），这就是为什么保留fallback逻辑
3. **分页**: 如果用户有大量成交记录（>200），可能需要实现分页逻辑

## 下一步

1. ✅ 代码已更新
2. ⏳ 需要重启程序使新代码生效
3. ⏳ 观察下一批实盘订单是否能正确检测成交
4. ⏳ 验证止损单是否正确挂出

## 回滚方案

如果新方案有问题，可以回滚到旧逻辑：

```bash
git diff backend/data/polymarket_executor.py
git diff backend/core/scheduler.py
git checkout backend/data/polymarket_executor.py backend/core/scheduler.py
```

## 相关文件

- `backend/data/polymarket_executor.py` - 新增 `get_recent_trades()` 方法
- `backend/core/scheduler.py` - 更新实盘订单检测逻辑
- `LIVE_ORDER_TRACKING_ISSUE.md` - 问题分析文档
