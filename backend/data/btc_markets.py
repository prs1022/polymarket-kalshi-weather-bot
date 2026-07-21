"""BTC 5-minute market fetcher for Polymarket."""
import asyncio
import httpx
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger("trading_bot")

GAMMA_API = "https://gamma-api.polymarket.com"
SERIES_SLUG = "btc-up-or-down-5m"

# Strict regex: only match real BTC 5-min window slugs (e.g. btc-updown-5m-1708531200)
_BTC_SLUG_RE = re.compile(r"^btc-updown-5m-\d{10}$")

# Short-lived cache (5s) for active markets to deduplicate calls within
# a single dashboard request (fetch_active_btc_markets + scan_for_signals)
# while still allowing fresh prices on each frontend poll (5s interval)
_markets_cache: dict = {"data": None, "ts": 0.0}
_markets_lock = asyncio.Lock()
_MARKETS_CACHE_TTL = 5.0


def is_valid_btc_slug(slug: str) -> bool:
    """Return True only if slug matches the exact BTC 5-min pattern."""
    return bool(_BTC_SLUG_RE.match(slug))


@dataclass
class BtcMarket:
    """A single BTC 5-minute Up/Down market."""
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    closed: bool
    up_token_id: str = ""    # CLOB token ID for UP outcome
    down_token_id: str = ""  # CLOB token ID for DOWN outcome

    @property
    def event_slug(self) -> str:
        return self.slug

    @property
    def spread(self) -> float:
        return abs(1.0 - self.up_price - self.down_price)

    @property
    def time_until_end(self) -> float:
        """Seconds until this window ends."""
        now = datetime.now(timezone.utc)
        return (self.window_end - now).total_seconds()

    @property
    def is_active(self) -> bool:
        """Window is currently in progress."""
        now = datetime.now(timezone.utc)
        return self.window_start <= now <= self.window_end and not self.closed

    @property
    def is_upcoming(self) -> bool:
        """Window hasn't started yet."""
        now = datetime.now(timezone.utc)
        return now < self.window_start and not self.closed


def _round_to_5min(ts: float) -> int:
    """Round a unix timestamp down to the nearest 5-minute boundary."""
    return int(ts) // 300 * 300


def _compute_window_slugs(count: int = 5) -> List[str]:
    """
    Compute event slugs for the current and upcoming 5-min windows.

    Slug pattern: btc-updown-5m-{unix_timestamp}
    where timestamp is the START of the 5-min window.
    """
    now = time.time()
    current_boundary = _round_to_5min(now)

    slugs = []
    for i in range(count):
        start_ts = current_boundary + (i * 300)
        slugs.append(f"btc-updown-5m-{start_ts}")

    return slugs


def _parse_event_to_btc_market(event: dict) -> Optional[BtcMarket]:
    """Parse a Polymarket event into a BtcMarket.

    Price priority: outcomePrices (most accurate Gamma field) > lastTradePrice > bestBid/bestAsk > 50/50
    """
    markets = event.get("markets", [])
    if not markets:
        return None

    market = markets[0]

    # Parse prices — outcomePrices is the most accurate field from Gamma API
    up_price = 0.5
    down_price = 0.5

    outcome_prices = market.get("outcomePrices", "")
    if outcome_prices:
        try:
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            if isinstance(prices, list) and len(prices) >= 2:
                up_price = float(prices[0])
                down_price = float(prices[1])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Fallback to lastTradePrice if outcomePrices not available or looks stale (both near 0.5)
    if abs(up_price - 0.5) < 0.01:
        last_trade = market.get("lastTradePrice")
        if last_trade is not None and abs(float(last_trade) - 0.5) > 0.01:
            up_price = float(last_trade)
            down_price = 1.0 - up_price

    # Parse timestamps
    slug = event.get("slug", "")
    start_str = event.get("startDate") or market.get("startDate")
    end_str = event.get("endDate") or market.get("endDate")

    window_start = datetime.now(timezone.utc)
    window_end = datetime.now(timezone.utc)

    if start_str:
        try:
            window_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    if end_str:
        try:
            window_end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    return BtcMarket(
        slug=slug,
        market_id=str(market.get("id", "")),
        up_price=up_price,
        down_price=down_price,
        window_start=window_start,
        window_end=window_end,
        volume=float(market.get("volume", 0) or 0),
        closed=bool(market.get("closed", False) or event.get("closed", False)),
    )


async def fetch_btc_market_by_slug(slug: str) -> Optional[BtcMarket]:
    """Fetch a single BTC 5-min market by its event slug."""
    if not is_valid_btc_slug(slug):
        logger.debug(f"Rejected invalid BTC slug: {slug}")
        return None

    url = f"{GAMMA_API}/events"
    params = {"slug": slug}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            events = response.json()

            if not events:
                return None

            event = events[0] if isinstance(events, list) else events
            market = _parse_event_to_btc_market(event)
            if market:
                # Enrich with real-time CLOB prices (most accurate)
                await _enrich_with_clob_prices(event, market)
            return market

        except Exception as e:
            logger.debug(f"Failed to fetch BTC market {slug}: {e}")
            return None


async def _enrich_with_clob_prices(event: dict, market: BtcMarket):
    """Fetch real-time prices from Polymarket CLOB API and update the market."""
    try:
        markets_list = event.get("markets", [])
        if not markets_list:
            return
        raw_market = markets_list[0]
        token_ids_raw = raw_market.get("clobTokenIds")
        if not token_ids_raw:
            return

        token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
        if not isinstance(token_ids, list) or len(token_ids) < 2:
            return

        market.up_token_id = token_ids[0]
        market.down_token_id = token_ids[1]

        async with httpx.AsyncClient(timeout=5.0) as client:
            up_resp = await client.get(
                "https://clob.polymarket.com/price",
                params={"token_id": token_ids[0], "side": "buy"}
            )
            down_resp = await client.get(
                "https://clob.polymarket.com/price",
                params={"token_id": token_ids[1], "side": "buy"}
            )

            if up_resp.status_code == 200 and down_resp.status_code == 200:
                up_price = float(up_resp.json().get("price", 0))
                down_price = float(down_resp.json().get("price", 0))
                # Sanity check: prices should sum to roughly 1.0
                if up_price > 0 and down_price > 0 and 0.8 < (up_price + down_price) < 1.2:
                    market.up_price = up_price
                    market.down_price = down_price
                elif up_price > 0.5:
                    # CLOB sometimes returns extreme values near settlement
                    market.up_price = up_price
                    market.down_price = 1.0 - up_price
    except Exception as e:
        logger.debug(f"CLOB price enrichment failed: {e}")


async def fetch_active_btc_markets() -> List[BtcMarket]:
    """
    Fetch current and upcoming BTC 5-min markets from Polymarket.

    Uses a 5-second cache with a lock to deduplicate concurrent calls
    (dashboard calls this + scan_for_signals which also calls it).
    """
    # Fast path: check cache without lock
    now = time.time()
    if _markets_cache["data"] is not None and (now - _markets_cache["ts"]) < _MARKETS_CACHE_TTL:
        return _markets_cache["data"]

    # Acquire lock to prevent duplicate API calls from concurrent coroutines
    async with _markets_lock:
        # Re-check cache after acquiring lock (another caller may have populated it)
        now = time.time()
        if _markets_cache["data"] is not None and (now - _markets_cache["ts"]) < _MARKETS_CACHE_TTL:
            return _markets_cache["data"]

        markets: List[BtcMarket] = []
        seen_slugs = set()

        # Method 1: Compute expected slugs and fetch in parallel
        expected_slugs = _compute_window_slugs(count=2)  # current + next window only
        tasks = [fetch_btc_market_by_slug(slug) for slug in expected_slugs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BtcMarket) and result.slug not in seen_slugs:
                seen_slugs.add(result.slug)
                markets.append(result)

        # Method 2: Search by series as fallback/supplement
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{GAMMA_API}/events",
                    params={
                        "active": "true",
                        "closed": "false",
                        "slug_contains": "btc-updown-5m",
                        "limit": 20,
                    }
                )
                response.raise_for_status()
                events = response.json()

                for event in events:
                    market = _parse_event_to_btc_market(event)
                    if market and market.slug not in seen_slugs and is_valid_btc_slug(market.slug):
                        seen_slugs.add(market.slug)
                        markets.append(market)

        except Exception as e:
            logger.debug(f"BTC series search fallback failed: {e}")

        # Sort by window end time (soonest first)
        markets.sort(key=lambda m: m.window_end)

        # Filter out already-closed markets
        markets = [m for m in markets if not m.closed]

        logger.info(f"Fetched {len(markets)} active BTC 5-min markets")

        # Update cache
        _markets_cache["data"] = markets
        _markets_cache["ts"] = now

        return markets


async def fetch_btc_market_for_settlement(slug: str) -> Optional[BtcMarket]:
    """
    Fetch a BTC market for settlement purposes (includes closed markets).
    """
    url = f"{GAMMA_API}/events"
    params = {"slug": slug}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            events = response.json()

            if not events:
                return None

            event = events[0] if isinstance(events, list) else events
            return _parse_event_to_btc_market(event)

        except Exception as e:
            logger.warning(f"Failed to fetch BTC market for settlement {slug}: {e}")
            return None


if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching active BTC 5-min markets...")
        markets = await fetch_active_btc_markets()
        print(f"Found {len(markets)} markets")

        for m in markets:
            print(f"\n  {m.slug}")
            print(f"  Up: {m.up_price:.2%} | Down: {m.down_price:.2%}")
            print(f"  Window: {m.window_start} -> {m.window_end}")
            print(f"  Volume: ${m.volume:,.0f}")
            print(f"  Active: {m.is_active} | Upcoming: {m.is_upcoming}")

    asyncio.run(test())
