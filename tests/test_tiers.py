"""Unit tests for tier classification. No network access."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cohort_pnl.fetchers.positions import PositionRecord
from cohort_pnl.tiers import TierRule, classify_tier, load_tier_rules

_NOW = datetime.now(timezone.utc)


def _pos(
    *,
    unrealized_pnl: float,
    margin_used: float,
    mark_px: float = 100.0,
    liq_px: float | None = None,
    side: str = "long",
) -> PositionRecord:
    return PositionRecord(
        wallet="0xtest",
        coin="BTC",
        side=side,
        size=1.0,
        entry_px=mark_px,
        mark_px=mark_px,
        unrealized_pnl=unrealized_pnl,
        margin_used=margin_used,
        liq_px=liq_px,
        fetched_at=_NOW,
    )


def _default_rules() -> list[TierRule]:
    cfg = Path(__file__).parent.parent / "config" / "tiers.yaml"
    return load_tier_rules(cfg)


def test_classify_money_print():
    rules = _default_rules()
    # +80% PNL, far from liq
    pos = _pos(unrealized_pnl=80.0, margin_used=100.0, mark_px=100.0, liq_px=10.0)
    assert classify_tier(pos, rules) == "Money Print"


def test_classify_smart_money():
    rules = _default_rules()
    # +25% PNL
    pos = _pos(unrealized_pnl=25.0, margin_used=100.0, mark_px=100.0, liq_px=10.0)
    assert classify_tier(pos, rules) == "Smart Money"


def test_classify_giga_rekt():
    rules = _default_rules()
    # mark=100, liq=99 -> 1% distance -> Giga-Rekt
    pos = _pos(unrealized_pnl=-5.0, margin_used=100.0, mark_px=100.0, liq_px=99.0)
    assert classify_tier(pos, rules) == "Giga-Rekt"


def test_classify_full_rekt():
    rules = _default_rules()
    # mark=100, liq=96 -> 4% distance -> Full Rekt (not Giga, within 5%)
    pos = _pos(unrealized_pnl=-10.0, margin_used=100.0, mark_px=100.0, liq_px=96.0)
    assert classify_tier(pos, rules) == "Full Rekt"


def test_classify_semi_rekt():
    rules = _default_rules()
    # PNL -50%, far from liq (distance > 5%)
    pos = _pos(unrealized_pnl=-50.0, margin_used=100.0, mark_px=100.0, liq_px=50.0)
    assert classify_tier(pos, rules) == "Semi-Rekt"


def test_classify_boundary_exact():
    """A position exactly at the pnl_pct_min boundary falls into the higher tier.

    Boundary convention: pnl_pct_max is exclusive (< not <=).
    At pnl=0.0, pnl_pct=0%: Humble Earner rule requires pnl_pct_min=-10 and
    pnl_pct_max=0. Since 0.0 is NOT < 0.0 (exclusive upper bound), this
    position falls into Grinder (pnl_pct_min=0, pnl_pct_max=10).
    """
    rules = _default_rules()
    pos = _pos(unrealized_pnl=0.0, margin_used=100.0, mark_px=100.0, liq_px=10.0)
    assert classify_tier(pos, rules) == "Grinder"


def test_classify_uses_config_boundaries():
    """Swapping in different boundaries moves the same position to a different tier."""
    custom_rules = [
        TierRule(name="Giga-Rekt", liq_distance_max_pct=2.0),
        TierRule(name="Full Rekt", liq_distance_max_pct=5.0),
        TierRule(name="Money Print", pnl_pct_min=10.0),  # anything >= 10% is "Money Print"
        TierRule(name="Humble Earner"),                   # catch-all
    ]
    pos = _pos(unrealized_pnl=30.0, margin_used=100.0, mark_px=100.0, liq_px=10.0)
    assert classify_tier(pos, custom_rules) == "Money Print"

    # With default rules the same position is "Smart Money"
    assert classify_tier(pos, _default_rules()) == "Smart Money"
