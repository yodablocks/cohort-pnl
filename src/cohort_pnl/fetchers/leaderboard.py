"""leaderboard.py -- pull the full HL leaderboard (unfiltered).

Pull pattern mirrors hl-midfreq/scripts/refresh_cohort.py but drops all
filters (no PNL/volume/account-value cutoffs). The full wallet list is the
universe for clearinghouseState queries in positions.py.

Coverage gap: wallets that have never cracked the leaderboard are not
captured. Small or dormant positions will be absent. Document in README,
do not hide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from cohort_pnl.errors import VenueUnavailable

log = logging.getLogger(__name__)

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
TIMEOUT = 30.0


@dataclass(frozen=True)
class LeaderboardEntry:
    eth_address: str
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


async def fetch_leaderboard(client: httpx.AsyncClient) -> list[LeaderboardEntry]:
    """Fetch the full HL leaderboard and return every wallet address.

    No PNL or account-value filter is applied. This build wants all wallets
    that appear on the leaderboard, not just profitable ones.

    Raises:
        VenueUnavailable: if the request fails or the response is malformed.
    """
    try:
        resp = await client.get(LEADERBOARD_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise VenueUnavailable(f"leaderboard request failed: {e}") from e

    rows = data.get("leaderboardRows", [])
    if not isinstance(rows, list):
        raise VenueUnavailable(
            f"unexpected leaderboard response shape: {type(rows)}"
        )

    now = datetime.now(timezone.utc)
    entries: list[LeaderboardEntry] = []
    for row in rows:
        addr = row.get("ethAddress", "").strip()
        if not addr:
            continue
        entries.append(LeaderboardEntry(eth_address=addr, fetched_at=now))

    log.info("leaderboard: %d wallets", len(entries))
    return entries
