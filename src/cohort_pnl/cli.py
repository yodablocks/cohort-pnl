"""cli.py -- entry point.

Usage:
    cohort-pnl                  # print rich tables to terminal (top 1000 wallets)
    cohort-pnl --top 500        # smaller wallet universe
    cohort-pnl --top 0          # full leaderboard (slow, expect 429s)
    cohort-pnl --json           # print JSON to stdout
    cohort-pnl --save           # also write daily snapshot to SQLite
    cohort-pnl --concurrency 40 # raise wallet fetch concurrency
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timezone
from pathlib import Path

import httpx
import yaml

from cohort_pnl.fetchers.leaderboard import fetch_leaderboard
from cohort_pnl.fetchers.positions import fetch_positions
from cohort_pnl.tiers import load_tier_rules
from cohort_pnl.aggregate import aggregate_cohort
from cohort_pnl.output import print_all, to_json
import cohort_pnl.snapshot as snapshot

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def _load_watchlist() -> list[str]:
    with open(_CONFIG_DIR / "watchlist.yaml") as f:
        return yaml.safe_load(f)["assets"]


async def run(args: argparse.Namespace) -> None:
    watchlist = _load_watchlist()
    rules = load_tier_rules()

    async with httpx.AsyncClient() as client:
        entries = await fetch_leaderboard(client)
        wallets = [e.eth_address for e in entries]
        if args.top > 0:
            wallets = wallets[:args.top]
        log.info("fetching positions for %d wallets...", len(wallets))

        positions = await fetch_positions(
            client, wallets, watchlist, concurrency=args.concurrency
        )

    asset_summaries = {}
    for asset in watchlist:
        asset_summaries[asset] = aggregate_cohort(positions, asset, rules)

    if args.json:
        print(to_json(asset_summaries))
    else:
        print_all(asset_summaries)

    if args.save:
        db = snapshot.init_db()
        today = date.today()
        for asset, summaries in asset_summaries.items():
            for s in summaries:
                snapshot.write_snapshot(
                    db, today, asset, s.tier,
                    s.bias_pct, s.position_count,
                    s.total_value, s.avg_liq_distance_pct,
                )
        log.info("snapshot saved for %s", today.isoformat())


def main() -> None:
    ap = argparse.ArgumentParser(description="HyperTracker cohort PNL breakdown")
    ap.add_argument("--json", action="store_true", help="output JSON instead of rich tables")
    ap.add_argument("--save", action="store_true", help="write daily snapshot to SQLite")
    ap.add_argument("--top", type=int, default=1000,
                    help="number of leaderboard wallets to query (default 1000, 0 = all)")
    ap.add_argument("--concurrency", type=int, default=20,
                    help="max concurrent clearinghouseState calls (default 20)")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
