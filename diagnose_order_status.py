"""
诊断工具：检查为什么CLOB API返回None

这个脚本会：
1. 从数据库获取最近的实盘订单
2. 尝试通过CLOB API查询订单状态
3. 显示详细的响应信息
"""
import sqlite3
import json
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 尝试导入CLOB客户端
try:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import ApiCreds
    from py_clob_client_v2.constants import POLYGON
    from py_clob_client_v2.order_utils import SignatureTypeV2
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("❌ py-clob-client-v2 未安装")

def main():
    if not CLOB_AVAILABLE:
        print("无法运行诊断：请先安装 py-clob-client-v2")
        return
    
    # 连接数据库
    conn = sqlite3.connect("tradingbot.db")
    cursor = conn.cursor()
    
    # 获取最近的实盘网格订单（有clob_order_id的）
    cursor.execute("""
        SELECT 
            id, market, price, shares, clob_order_id, status, created_at
        FROM grid_orders
        WHERE trade_type = 'live'
        AND clob_order_id IS NOT NULL
        AND clob_order_id != ''
        ORDER BY created_at DESC
        LIMIT 5
    """)
    
    orders = cursor.fetchall()
    
    if not orders:
        print("❌ 数据库中没有找到实盘网格订单")
        conn.close()
        return
    
    print(f"\n找到 {len(orders)} 个最近的实盘网格订单")
    print("=" * 80)
    
    # 初始化CLOB客户端
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    address = os.getenv("POLYMARKET_ADDRESS")
    
    if not private_key:
        print("❌ 环境变量POLYMARKET_PRIVATE_KEY未设置")
        conn.close()
        return
    
    try:
        # 创建临时客户端来获取API密钥
        temp_client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=POLYGON,
        )
        creds = temp_client.derive_api_key()
        
        # 创建真实客户端
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=POLYGON,
            creds=creds,
            signature_type=SignatureTypeV2.POLY_1271,
            funder=address,
        )
        print("✅ CLOB客户端初始化成功\n")
    except Exception as e:
        print(f"❌ CLOB客户端初始化失败: {e}")
        conn.close()
        return
    
    for order in orders:
        order_id, market, price, shares, clob_order_id, status, created_at = order
        
        print(f"\n订单 #{order_id}")
        print(f"  市场: {market}")
        print(f"  价格: ${price:.2f}, 份额: {shares}")
        print(f"  CLOB订单ID: {clob_order_id}")
        print(f"  数据库状态: {status}")
        print(f"  创建时间: {created_at}")
        
        # 尝试查询订单状态
        print(f"  正在查询CLOB API...")
        
        try:
            raw_response = client.get_order(clob_order_id)
            
            if raw_response is None:
                print(f"  ❌ CLOB API返回None (订单不存在、已过期或无权限查看)")
            else:
                print(f"  ✅ CLOB API返回:")
                print(f"     状态: {raw_response.get('status', 'N/A')}")
                print(f"     已成交数量: {raw_response.get('size_matched', 'N/A')}")
                print(f"     价格: {raw_response.get('price', 'N/A')}")
                print(f"     原始订单: {raw_response.get('original_size', 'N/A')}")
                
        except Exception as e:
            print(f"  ⚠️  查询失败: {e}")
        
        print("-" * 80)
    
    conn.close()
    
    print("\n💡 可能的原因:")
    print("  1. 订单太旧，CLOB API已清理（通常5-10分钟后清理）")
    print("  2. 订单ID格式错误")
    print("  3. API密钥权限不足")
    print("  4. 订单属于不同的钱包地址")
    print("\n诊断完成")

if __name__ == "__main__":
    main()
