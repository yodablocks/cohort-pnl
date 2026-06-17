"""tiers.py -- pure tier classification. No I/O, fully testable.

Tier dimensions:
  Primary:   unrealized_pnl_pct = unrealized_pnl / margin_used * 100
  Secondary: liq_distance_pct   = |mark_px - liq_px| / mark_px * 100

Liquidation proximity (secondary) is evaluated first for the worst tiers
(Giga-Rekt, Full Rekt). A position very close to liquidation lands in those
tiers even if its PNL% looks modest -- e.g. high leverage, tiny margin.

Boundaries are loaded from config/tiers.yaml, never hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cohort_pnl.fetchers.positions import PositionRecord


TIER_NAMES = [
    "Money Print",
    "Smart Money",
    "Grinder",
    "Humble Earner",
    "Exit Liquidity",
    "Semi-Rekt",
    "Full Rekt",
    "Giga-Rekt",
]

_DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "tiers.yaml"


@dataclass(frozen=True)
class TierRule:
    name: str
    liq_distance_max_pct: float | None = None  # triggers on proximity
    pnl_pct_min: float | None = None
    pnl_pct_max: float | None = None


def load_tier_rules(path: Path = _DEFAULT_CONFIG) -> list[TierRule]:
    """Load tier rules from YAML. Rules are ordered; first match wins."""
    with open(path) as f:
        cfg = yaml.safe_load(f)

    rules: list[TierRule] = []
    for entry in cfg["tiers"]:
        rules.append(
            TierRule(
                name=entry["name"],
                liq_distance_max_pct=entry.get("liq_distance_max_pct"),
                pnl_pct_min=entry.get("pnl_pct_min"),
                pnl_pct_max=entry.get("pnl_pct_max"),
            )
        )
    return rules


def _pnl_pct(position: PositionRecord) -> float | None:
    if position.margin_used <= 0:
        return None
    return (position.unrealized_pnl / position.margin_used) * 100.0


def _liq_distance_pct(position: PositionRecord) -> float | None:
    if position.liq_px is None or position.mark_px <= 0:
        return None
    return abs(position.mark_px - position.liq_px) / position.mark_px * 100.0


def classify_tier(position: PositionRecord, rules: list[TierRule]) -> str:
    """Return the tier label for one position.

    Rules are evaluated in order. First match wins.
    Falls back to "Humble Earner" if no rule matches (should not happen with
    a well-formed config that covers all PNL ranges, but avoids a hard crash).

    Boundary convention: pnl_pct_max is exclusive (< not <=). A position
    exactly on a boundary falls into the higher (better) tier.
    """
    pnl = _pnl_pct(position)
    liq_dist = _liq_distance_pct(position)

    for rule in rules:
        # -- liquidation-proximity rules (Giga-Rekt, Full Rekt) --
        if rule.liq_distance_max_pct is not None:
            if liq_dist is not None and liq_dist <= rule.liq_distance_max_pct:
                return rule.name
            # No liq_px means we cannot confirm proximity; skip this rule.
            continue

        # -- PNL% rules --
        if pnl is None:
            # Cannot compute PNL% (zero margin); skip PNL-based rules.
            continue

        min_ok = rule.pnl_pct_min is None or pnl >= rule.pnl_pct_min
        max_ok = rule.pnl_pct_max is None or pnl < rule.pnl_pct_max

        if min_ok and max_ok:
            return rule.name

    return "Humble Earner"
