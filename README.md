# cohort-pnl

Position breakdown by PNL cohort for Hyperliquid leaderboard wallets.

Replicates the HyperTracker "Position Breakdown by Cohort" panel: wallets
bucketed into named PNL tiers with per-cohort bias (directional lean),
position count, total value, and proximity to liquidation. Covers 7
watchlist assets across native HL perps and the xyz HIP-3 dex.

## Watchlist

`BTC, ETH, SPCX, NVDA, TSLA, GOLD, SILVER`

Configured in `config/watchlist.yaml`. Each wallet is evaluated per
position, not per account -- a wallet long BTC and short SPCX produces
two separate cohort rows.

## Tiers

| Tier | Signal |
|------|--------|
| Money Print | PNL > +50% of margin |
| Smart Money | PNL +10% to +50% |
| Grinder | PNL 0% to +10% |
| Humble Earner | PNL -10% to 0% |
| Exit Liquidity | PNL -30% to -10% |
| Semi-Rekt | PNL < -30% |
| Full Rekt | within 5% of liquidation price |
| Giga-Rekt | within 2% of liquidation price |

Liquidation proximity (Full Rekt / Giga-Rekt) is evaluated before PNL%,
so a highly leveraged position close to liquidation lands there regardless
of its PNL percentage. Boundaries live in `config/tiers.yaml`.

## Coverage

Wallet universe is seeded from the full HL leaderboard
(`stats-data.hyperliquid.xyz/Mainnet/leaderboard`). By default the top
1000 wallets by leaderboard rank are queried.

**Known gap:** wallets that have never appeared on the leaderboard are not
captured. Small or dormant positions will be absent from the output.

## Setup

```bash
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Usage

```bash
# Rich tables to terminal (top 1000 wallets)
cohort-pnl

# JSON output
cohort-pnl --json

# Write daily snapshot to SQLite (data/snapshots.db)
cohort-pnl --save

# Raise concurrency (default 20)
cohort-pnl --concurrency 30
```

## Architecture

Two `clearinghouseState` calls are made per wallet:

- **No `dex` param**: native HL perps (BTC, ETH). Coins returned as plain tickers.
- **`dex: "xyz"`**: HIP-3 perps (SPCX, NVDA, TSLA, GOLD, SILVER). Coins returned as `xyz:SPCX`, `xyz:TSLA`, etc. -- the prefix is stripped internally.

Both calls share the same concurrency semaphore.

## Tests

```bash
pytest
```

14 unit and smoke tests. No network access required.

## Snapshot / Bias Trend

`--save` writes one row per `(date, asset, tier)` to `data/snapshots.db`.
The 7-day bias trend is a read query over this table. Run daily via cron
to accumulate history.
