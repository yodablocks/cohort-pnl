"""aggregate.py -- per-tier, per-asset aggregation.

Aggregation runs per watchlist asset. The same wallet address can appear in
two different per-asset tier tables if it holds positions in multiple assets.
This is intentional: we are doing per-position tiering, not account-wide.
"""

from __future__ import annotations

from dataclasses import dataclass

from cohort_pnl.fetchers.positions import PositionRecord
from cohort_pnl.tiers import TIER_NAMES, TierRule, classify_tier


@dataclass
class TierSummary:
    tier: str
    position_count: int
    long_count: int
    short_count: int
    bias_pct: float        # positive = net long bias (% long of total)
    total_value: float     # sum of margin_used across positions in tier
    avg_liq_distance_pct: float | None  # None if no positions have a liq_px


def aggregate_cohort(
    positions: list[PositionRecord],
    asset: str,
    rules: list[TierRule],
) -> list[TierSummary]:
    """Compute per-tier summary for one watchlist asset.

    Returns a TierSummary for every tier in TIER_NAMES order. Tiers with
    zero positions return zeroed values rather than raising.
    """
    asset_upper = asset.upper()
    asset_positions = [p for p in positions if p.coin == asset_upper]

    # Bucket by tier
    buckets: dict[str, list[PositionRecord]] = {name: [] for name in TIER_NAMES}
    for pos in asset_positions:
        tier = classify_tier(pos, rules)
        buckets.setdefault(tier, []).append(pos)

    summaries: list[TierSummary] = []
    for tier_name in TIER_NAMES:
        bucket = buckets.get(tier_name, [])
        if not bucket:
            summaries.append(
                TierSummary(
                    tier=tier_name,
                    position_count=0,
                    long_count=0,
                    short_count=0,
                    bias_pct=0.0,
                    total_value=0.0,
                    avg_liq_distance_pct=None,
                )
            )
            continue

        long_count = sum(1 for p in bucket if p.side == "long")
        short_count = len(bucket) - long_count
        total = len(bucket)
        bias_pct = (long_count / total) * 100.0

        total_value = sum(p.margin_used for p in bucket)

        liq_dists = []
        for p in bucket:
            if p.liq_px is not None and p.mark_px > 0:
                liq_dists.append(abs(p.mark_px - p.liq_px) / p.mark_px * 100.0)

        avg_liq = sum(liq_dists) / len(liq_dists) if liq_dists else None

        summaries.append(
            TierSummary(
                tier=tier_name,
                position_count=total,
                long_count=long_count,
                short_count=short_count,
                bias_pct=bias_pct,
                total_value=total_value,
                avg_liq_distance_pct=avg_liq,
            )
        )

    return summaries
