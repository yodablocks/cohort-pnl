"""Unit tests for per-tier aggregation."""

from __future__ import annotations

from datetime import datetime, timezone

from cohort_pnl.aggregate import aggregate_cohort
from cohort_pnl.fetchers.positions import PositionRecord
from cohort_pnl.tiers import TierRule

_NOW = datetime.now(timezone.utc)

_RULES = [
    TierRule(name="Giga-Rekt", liq_distance_max_pct=2.0),
    TierRule(name="Full Rekt", liq_distance_max_pct=5.0),
    TierRule(name="Semi-Rekt", pnl_pct_max=-30.0),
    TierRule(name="Exit Liquidity", pnl_pct_max=-10.0, pnl_pct_min=-30.0),
    TierRule(name="Humble Earner", pnl_pct_max=0.0, pnl_pct_min=-10.0),
    TierRule(name="Grinder", pnl_pct_max=10.0, pnl_pct_min=0.0),
    TierRule(name="Smart Money", pnl_pct_max=50.0, pnl_pct_min=10.0),
    TierRule(name="Money Print", pnl_pct_min=50.0),
]


def _pos(side: str, pnl: float, margin: float = 100.0, liq_px: float = 10.0) -> PositionRecord:
    return PositionRecord(
        wallet="0xtest",
        coin="BTC",
        side=side,
        size=1.0,
        entry_px=100.0,
        mark_px=100.0,
        unrealized_pnl=pnl,
        margin_used=margin,
        liq_px=liq_px,
        fetched_at=_NOW,
    )


def test_aggregate_bias_split():
    """Mixed long/short in Grinder tier: bias% reflects the split."""
    positions = [
        _pos("long", 5.0),
        _pos("long", 5.0),
        _pos("short", 5.0),
    ]
    summaries = aggregate_cohort(positions, "BTC", _RULES)
    grinder = next(s for s in summaries if s.tier == "Grinder")

    assert grinder.position_count == 3
    assert grinder.long_count == 2
    assert grinder.short_count == 1
    assert abs(grinder.bias_pct - (2 / 3 * 100)) < 0.01


def test_aggregate_empty_tier():
    """A tier with zero positions returns zeros without raising."""
    positions = [_pos("long", 80.0)]  # only Money Print
    summaries = aggregate_cohort(positions, "BTC", _RULES)
    grinder = next(s for s in summaries if s.tier == "Grinder")

    assert grinder.position_count == 0
    assert grinder.total_value == 0.0
    assert grinder.avg_liq_distance_pct is None


def test_aggregate_different_assets_isolated():
    """Positions for ETH should not appear in BTC aggregation."""
    positions = [
        PositionRecord(
            wallet="0xa", coin="ETH", side="long", size=1.0,
            entry_px=3000.0, mark_px=3000.0,
            unrealized_pnl=300.0, margin_used=1000.0, liq_px=100.0,
            fetched_at=_NOW,
        ),
        _pos("long", 5.0),  # BTC
    ]
    btc_summaries = aggregate_cohort(positions, "BTC", _RULES)
    total_btc = sum(s.position_count for s in btc_summaries)
    assert total_btc == 1
