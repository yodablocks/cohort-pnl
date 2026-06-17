"""positions.py -- per-wallet clearinghouseState, filtered to watchlist.

One POST per wallet per dex. At leaderboard scale (low thousands) this is
the dominant I/O cost. We batch with asyncio.gather + a semaphore -- do not
fire unbounded.

Two-dex architecture (verified against live API 2026-06-17):
- Native HL perps (BTC, ETH): clearinghouseState with no "dex" param.
  Coin field returned as plain ticker: "BTC", "ETH".
- HIP-3 perps (SPCX, NVDA, TSLA, GOLD, SILVER): separate dex "xyz".
  Must pass "dex": "xyz" in the request body.
  Coin field returned with prefix: "xyz:SPCX", "xyz:NVDA", etc.
  _normalize_coin() strips the "xyz:" prefix to match watchlist keys.

Two calls per wallet (native + xyz). Both go through the same semaphore so
total concurrency is still bounded.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Collection

import httpx

from cohort_pnl.errors import VenueUnavailable

log = logging.getLogger(__name__)

INFO_URL = "https://api.hyperliquid.xyz/info"
TIMEOUT = 15.0
# Max concurrent clearinghouseState calls. 20 is conservative; tune up if
# the endpoint proves tolerant, but do not remove the limit.
CONCURRENCY = 20

# HIP-3 dex name on Hyperliquid.
XYZ_DEX = "xyz"


@dataclass(frozen=True)
class PositionRecord:
    wallet: str
    coin: str          # normalized to plain ticker (e.g. "SPCX", not "xyz:SPCX")
    side: str          # "long" or "short"
    size: float        # position size in base asset
    entry_px: float
    mark_px: float
    unrealized_pnl: float
    margin_used: float  # isolated margin for this position
    liq_px: float | None  # None if not returned (e.g. cross-margin)
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def _normalize_coin(raw: str) -> str:
    """Strip the xyz: dex prefix to get the plain ticker.

    HIP-3 clearinghouseState (dex="xyz") returns coins as "xyz:SPCX", "xyz:TSLA", etc.
    Native perps return plain names like "BTC", "ETH".
    Both normalize to the plain ticker for watchlist matching.
    """
    if ":" in raw:
        return raw.split(":", 1)[1].strip().upper()
    return raw.strip().upper()


def _parse_positions(
    wallet: str,
    data: dict,
    watchlist: frozenset[str],
    fetched_at: datetime,
) -> list[PositionRecord]:
    """Extract and filter positions from a clearinghouseState response."""
    records: list[PositionRecord] = []

    asset_positions = data.get("assetPositions", [])
    for entry in asset_positions:
        pos = entry.get("position", {})
        raw_coin = pos.get("coin", "")
        coin = _normalize_coin(raw_coin)

        if coin not in watchlist:
            continue

        szi = pos.get("szi", "0")
        try:
            size = float(szi)
        except (TypeError, ValueError):
            continue

        if size == 0.0:
            continue  # closed position still in response

        side = "long" if size > 0 else "short"

        try:
            entry_px = float(pos.get("entryPx", 0))
            unrealized_pnl = float(pos.get("unrealizedPnl", 0))
            margin_used = float(pos.get("marginUsed", 0))
        except (TypeError, ValueError):
            continue

        # positionValue is notional; we use marginUsed as the denominator for
        # PNL% because it reflects actual capital at risk for this position.
        # mark_px comes from the position value / size, or fallback to entry.
        try:
            pos_value = float(pos.get("positionValue", 0))
            mark_px = pos_value / abs(size) if abs(size) > 0 else entry_px
        except (TypeError, ValueError, ZeroDivisionError):
            mark_px = entry_px

        raw_liq = pos.get("liquidationPx")
        try:
            liq_px = float(raw_liq) if raw_liq is not None else None
        except (TypeError, ValueError):
            liq_px = None

        records.append(
            PositionRecord(
                wallet=wallet,
                coin=coin,
                side=side,
                size=abs(size),
                entry_px=entry_px,
                mark_px=mark_px,
                unrealized_pnl=unrealized_pnl,
                margin_used=margin_used,
                liq_px=liq_px,
                fetched_at=fetched_at,
            )
        )

    return records


_RETRY_DELAY = 2.0  # seconds to wait before retrying a 429


async def _fetch_dex(
    client: httpx.AsyncClient,
    wallet: str,
    watchlist: frozenset[str],
    sem: asyncio.Semaphore,
    dex: str | None,
) -> list[PositionRecord]:
    """Fetch clearinghouseState for one wallet on one dex.

    Retries once after a short delay on 429. Any other failure is logged and
    returns an empty list so one bad wallet doesn't abort the run.
    """
    body: dict = {"type": "clearinghouseState", "user": wallet}
    if dex is not None:
        body["dex"] = dex

    for attempt in range(2):
        async with sem:
            try:
                resp = await client.post(INFO_URL, json=body, timeout=TIMEOUT)
                if resp.status_code == 429 and attempt == 0:
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                resp.raise_for_status()
                data = resp.json()
                fetched_at = datetime.now(timezone.utc)
                return _parse_positions(wallet, data, watchlist, fetched_at)
            except httpx.HTTPError as e:
                if attempt == 0 and "429" in str(e):
                    await asyncio.sleep(_RETRY_DELAY)
                    continue
                log.warning("clearinghouseState failed for %s dex=%s: %s", wallet, dex, e)
                return []

    return []


async def _fetch_one(
    client: httpx.AsyncClient,
    wallet: str,
    watchlist: frozenset[str],
    sem: asyncio.Semaphore,
) -> list[PositionRecord]:
    """Fetch native HL perps + xyz HIP-3 perps for one wallet."""
    native, xyz = await asyncio.gather(
        _fetch_dex(client, wallet, watchlist, sem, dex=None),
        _fetch_dex(client, wallet, watchlist, sem, dex=XYZ_DEX),
    )
    return native + xyz


async def fetch_positions(
    client: httpx.AsyncClient,
    wallets: list[str],
    watchlist: Collection[str],
    *,
    concurrency: int = CONCURRENCY,
) -> list[PositionRecord]:
    """Fetch clearinghouseState for every wallet, return watchlist positions.

    Makes two requests per wallet: one for native HL perps (BTC, ETH) and one
    for the xyz HIP-3 dex (SPCX, NVDA, TSLA, GOLD, SILVER). Both share the
    same semaphore so concurrency is bounded across all requests.

    Individual wallet failures are logged and skipped -- a single bad address
    should not abort the whole run.
    """
    wl = frozenset(c.upper() for c in watchlist)
    sem = asyncio.Semaphore(concurrency)

    tasks = [_fetch_one(client, w, wl, sem) for w in wallets]
    results = await asyncio.gather(*tasks)

    all_positions: list[PositionRecord] = []
    for batch in results:
        all_positions.extend(batch)

    log.info(
        "positions: %d wallets queried, %d watchlist positions found",
        len(wallets),
        len(all_positions),
    )
    return all_positions
