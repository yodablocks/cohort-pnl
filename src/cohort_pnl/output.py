"""output.py -- terminal (rich) and JSON output.

Layout: one rich table per watchlist asset, tier rows with
Bias / # Pos / Value / Close to Liq columns. Header line showing
most bullish cohort. JSON via --json flag.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table
from rich import box

from cohort_pnl.aggregate import TierSummary
from cohort_pnl.tiers import TIER_NAMES

console = Console()

# Tier color hints for the terminal table
_TIER_STYLE = {
    "Money Print":    "bold green",
    "Smart Money":    "green",
    "Grinder":        "cyan",
    "Humble Earner":  "white",
    "Exit Liquidity": "yellow",
    "Semi-Rekt":      "dark_orange",
    "Full Rekt":      "red",
    "Giga-Rekt":      "bold red",
}


def _fmt_bias(bias_pct: float) -> str:
    direction = "L" if bias_pct >= 50 else "S"
    dominant = bias_pct if bias_pct >= 50 else 100.0 - bias_pct
    return f"{dominant:.0f}% {direction}"


def _fmt_value(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


# Cross-margin positions can produce technically valid but meaningless liq
# distances (e.g. 168,000,000%) because the account has enough collateral to
# absorb almost any move. Suppress anything above this threshold -- it adds
# noise, not signal.
_LIQ_DIST_MAX_DISPLAY = 500.0


def _fmt_liq(dist: float | None) -> str:
    if dist is None or dist > _LIQ_DIST_MAX_DISPLAY:
        return "N/A"
    return f"{dist:.1f}%"


def print_asset_table(asset: str, summaries: list[TierSummary]) -> None:
    active = [s for s in summaries if s.position_count > 0]

    most_bullish = max(active, key=lambda s: s.bias_pct) if active else None
    header = f"[bold]{asset}[/bold]"
    if most_bullish:
        header += f"  |  Most Bullish: [green]{most_bullish.tier}[/green] ({most_bullish.bias_pct:.0f}% Long)"

    table = Table(
        title=header,
        box=box.SIMPLE_HEAD,
        show_lines=False,
        expand=False,
    )
    table.add_column("Tier", style="bold", min_width=14)
    table.add_column("Bias", justify="right", min_width=10)
    table.add_column("# Pos", justify="right", min_width=6)
    table.add_column("Value", justify="right", min_width=10)
    table.add_column("Close to Liq", justify="right", min_width=12)

    for s in summaries:
        style = _TIER_STYLE.get(s.tier, "")
        table.add_row(
            s.tier,
            _fmt_bias(s.bias_pct) if s.position_count > 0 else "--",
            str(s.position_count),
            _fmt_value(s.total_value) if s.position_count > 0 else "--",
            _fmt_liq(s.avg_liq_distance_pct),
            style=style if s.position_count > 0 else "dim",
        )

    console.print(table)


def print_all(asset_summaries: dict[str, list[TierSummary]]) -> None:
    for asset in asset_summaries:
        print_asset_table(asset, asset_summaries[asset])


def to_json(asset_summaries: dict[str, list[TierSummary]]) -> str:
    out: dict[str, Any] = {}
    for asset, summaries in asset_summaries.items():
        out[asset] = [
            {
                "tier": s.tier,
                "bias_pct": s.bias_pct,
                "long_count": s.long_count,
                "short_count": s.short_count,
                "position_count": s.position_count,
                "total_value": s.total_value,
                "avg_liq_distance_pct": s.avg_liq_distance_pct,
            }
            for s in summaries
        ]
    return json.dumps(out, indent=2)
