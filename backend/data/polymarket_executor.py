"""
Polymarket CLOB V2 executor for live order placement.

Wraps py-clob-client-v2 to place real limit orders on Polymarket.
Gracefully degrades to simulation if py-clob-client-v2 is not installed
or credentials are not configured.
"""
import logging
from typing import Optional, List, Dict, Any

from backend.config import settings

logger = logging.getLogger(__name__)

# Try importing py-clob-client-v2
try:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import (
        OrderArgs,
        OrderType,
        ApiCreds,
        BalanceAllowanceParams,
        OrderPayload,
        AssetType,
    )
    from py_clob_client_v2.constants import POLYGON
    from py_clob_client_v2.order_utils import SignatureTypeV2
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    ClobClient = None
    OrderArgs = None
    OrderType = None
    ApiCreds = None
    BalanceAllowanceParams = None
    OrderPayload = None
    AssetType = None
    SignatureTypeV2 = None
    POLYGON = 137
    logger.info("py-clob-client-v2 not installed — live trading will use stub mode")


class PolymarketExecutor:
    """
    Execute real orders on Polymarket CLOB V2 API.

    Falls back to stub mode (logs only, no real orders) when:
    - py-clob-client-v2 is not installed
    - API credentials are not configured
    """

    def __init__(self):
        self._client = None
        self._stub_mode = not CLOB_AVAILABLE

        if CLOB_AVAILABLE and settings.POLYMARKET_PRIVATE_KEY:
            try:
                # Step 1: temp client to derive API key (avoid create_or_derive which fails)
                temp_client = ClobClient(
                    host="https://clob.polymarket.com",
                    key=settings.POLYMARKET_PRIVATE_KEY,
                    chain_id=POLYGON,
                )
                creds = temp_client.derive_api_key()

                # Step 2: real client with POLY_1271 (EIP-7702 deposit wallet flow)
                # MetaMask accounts on Polymarket require signature_type=3 (POLY_1271)
                self._client = ClobClient(
                    host="https://clob.polymarket.com",
                    key=settings.POLYMARKET_PRIVATE_KEY,
                    chain_id=POLYGON,  # Polygon mainnet (137)
                    creds=creds,
                    signature_type=SignatureTypeV2.POLY_1271,  # 3 — EIP-7702 deposit wallet
                    funder=settings.POLYMARKET_ADDRESS,
                )

                logger.info("PolymarketExecutor initialized with live CLOB V2 client (POLY_1271)")
            except Exception as e:
                logger.warning(f"Failed to init CLOB client: {e}, falling back to stub mode")
                self._stub_mode = True
                self._client = None
        else:
            self._stub_mode = True

    @property
    def is_stub(self) -> bool:
        """Whether executor is in stub mode (no real orders)."""
        return self._stub_mode

    def place_limit_buy(
        self,
        token_id: str,
        price: float,
        size: float,
    ) -> Optional[str]:
        """
        Place a limit buy order on Polymarket CLOB.

        Args:
            token_id: CLOB token ID for the outcome
            price: Limit price (0-1)
            size: Dollar amount to spend

        Returns:
            CLOB order ID, or None if failed/stub mode
        """
        price = round(price, 2)
        size = round(size, 2)

        if self._stub_mode:
            logger.info(f"[STUB] place_limit_buy: token={token_id[:8]}..., price={price}, size=${size}")
            return f"STUB_{token_id[:8]}_{price}_{size}"

        try:
            # Calculate shares = size / price
            shares = round(size / price, 2)

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=shares,
                side="BUY",
            )
            signed_order = self._client.create_order(order_args)
            resp = self._client.post_order(signed_order, OrderType.GTC)

            order_id = resp.get("orderID") or resp.get("id") or resp.get("order_id")
            logger.info(f"[LIVE] limit buy placed: token={token_id[:8]}..., price={price}, size=${size}, order_id={order_id}")
            return str(order_id) if order_id else None

        except Exception as e:
            logger.error(f"[LIVE] place_limit_buy failed: {e}")
            return None

    def place_limit_sell(
        self,
        token_id: str,
        price: float,
        shares: float,
    ) -> Optional[str]:
        """
        Place a limit sell order (for stop-loss exit).

        Args:
            token_id: CLOB token ID for the outcome
            price: Limit price (0-1)
            shares: Number of shares to sell

        Returns:
            CLOB order ID, or None if failed/stub mode
        """
        price = round(price, 2)
        shares = round(shares, 2)

        if self._stub_mode:
            logger.info(f"[STUB] place_limit_sell: token={token_id[:8]}..., price={price}, shares={shares}")
            return f"STUB_SELL_{token_id[:8]}_{price}_{shares}"

        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=shares,
                side="SELL",
            )
            signed_order = self._client.create_order(order_args)
            resp = self._client.post_order(signed_order, OrderType.GTC)

            order_id = resp.get("orderID") or resp.get("id") or resp.get("order_id")
            logger.info(f"[LIVE] limit sell placed: token={token_id[:8]}..., price={price}, shares={shares}, order_id={order_id}")
            return str(order_id) if order_id else None

        except Exception as e:
            logger.error(f"[LIVE] place_limit_sell failed: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        if self._stub_mode:
            logger.info(f"[STUB] cancel_order: {order_id}")
            return True

        try:
            payload = OrderPayload(orderID=order_id)
            self._client.cancel_order(payload)
            logger.info(f"[LIVE] order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"[LIVE] cancel_order failed: {e}")
            return False

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Get order status from CLOB API.

        Returns:
            Dict with keys: status (matched/pending/cancelled),
                           filled_size (shares filled),
                           filled_price (avg fill price)
        """
        if self._stub_mode:
            return {"status": "pending", "filled_size": 0, "filled_price": 0}

        try:
            order = self._client.get_order(order_id)
            
            # Handle None response (order not found or API returned empty)
            if order is None:
                logger.warning(f"[LIVE] Order {order_id[:16]}... not found in CLOB API (returned None)")
                return {"status": "not_found", "filled_size": 0, "filled_price": 0}
            
            status = order.get("status", "unknown")
            filled_size = float(order.get("size_matched", 0))
            filled_price = float(order.get("price", 0))

            return {
                "status": status,
                "filled_size": filled_size,
                "filled_price": filled_price,
            }
        except Exception as e:
            logger.error(f"[LIVE] get_order_status failed: {e}")
            return {"status": "error", "filled_size": 0, "filled_price": 0}
    
    def get_recent_trades(self, asset_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent trades (fills) for the authenticated user.
        
        This is more reliable than get_order() for detecting fills,
        as trade data persists longer than order data.
        
        Args:
            asset_id: Optional token ID to filter trades
            limit: Max number of trades to return (default 100)
            
        Returns:
            List of trade dicts with keys:
                - taker_order_id: Order ID that created this fill
                - price: Fill price
                - size: Fill size (in token units, need to divide by 1e6)
                - match_time: Unix timestamp
                - status: TRADE_STATUS_CONFIRMED, etc.
                - side: BUY or SELL
        """
        if self._stub_mode:
            return []
        
        try:
            # Use py-clob-client's get_trades method
            trades = self._client.get_trades()
            
            if not trades:
                return []
            
            # trades might be paginated response with 'data' key
            if isinstance(trades, dict) and 'data' in trades:
                trades = trades['data']
            
            # Filter by asset_id if provided
            if asset_id:
                trades = [t for t in trades if t.get('asset_id') == asset_id]
            
            return trades[:limit]
            
        except Exception as e:
            logger.error(f"[LIVE] get_recent_trades failed: {e}")
            return []

    def get_usdc_balance(self) -> float:
        """Get actual USDC balance for live trading."""
        if self._stub_mode:
            return 0.0

        try:
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=2,
            )
            result = self._client.get_balance_allowance(params)
            balance = float(result.get("balance", 0)) / 1e6  # USDC has 6 decimals
            logger.info(f"[LIVE] USDC balance: ${balance:.2f}")
            return balance
        except Exception as e:
            logger.error(f"Failed to get USDC balance: {e}")
            return 0.0


# Singleton instance
_executor: Optional[PolymarketExecutor] = None


def get_executor() -> PolymarketExecutor:
    """Get the singleton executor instance."""
    global _executor
    if _executor is None:
        _executor = PolymarketExecutor()
    return _executor
