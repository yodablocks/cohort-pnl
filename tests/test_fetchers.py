"""Smoke tests for fetchers using respx mocks. No real network calls."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from cohort_pnl.fetchers.leaderboard import fetch_leaderboard, LEADERBOARD_URL
from cohort_pnl.fetchers.positions import fetch_positions, INFO_URL


@respx.mock
@pytest.mark.asyncio
async def test_leaderboard_returns_addresses():
    payload = {
        "leaderboardRows": [
            {"ethAddress": "0xaaa", "windowPerformances": []},
            {"ethAddress": "0xbbb", "windowPerformances": []},
            {"ethAddress": "", "windowPerformances": []},  # blank -- should be skipped
        ]
    }
    respx.get(LEADERBOARD_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with httpx.AsyncClient() as client:
        entries = await fetch_leaderboard(client)

    assert len(entries) == 2
    addrs = {e.eth_address for e in entries}
    assert "0xaaa" in addrs
    assert "0xbbb" in addrs


@respx.mock
@pytest.mark.asyncio
async def test_positions_filters_to_watchlist():
    """Mock response includes BTC, ETH, and a non-watchlist coin. Only BTC/ETH survive.

    Two POST calls are made per wallet: native dex (first) and xyz dex (second).
    """
    wallet = "0xwallet1"
    native_payload = {
        "assetPositions": [
            {
                "position": {
                    "coin": "BTC",
                    "szi": "0.5",
                    "entryPx": "40000",
                    "unrealizedPnl": "500",
                    "marginUsed": "2000",
                    "positionValue": "20000",
                    "liquidationPx": "35000",
                }
            },
            {
                "position": {
                    "coin": "ETH",
                    "szi": "-1.0",
                    "entryPx": "2500",
                    "unrealizedPnl": "-100",
                    "marginUsed": "500",
                    "positionValue": "2400",
                    "liquidationPx": "2800",
                }
            },
            {
                "position": {
                    "coin": "SOL",  # not in watchlist
                    "szi": "10.0",
                    "entryPx": "100",
                    "unrealizedPnl": "50",
                    "marginUsed": "200",
                    "positionValue": "1050",
                    "liquidationPx": "80",
                }
            },
        ]
    }
    respx.post(INFO_URL).mock(side_effect=[
        httpx.Response(200, json=native_payload),
        httpx.Response(200, json={"assetPositions": []}),  # xyz dex empty
    ])

    async with httpx.AsyncClient() as client:
        positions = await fetch_positions(
            client, [wallet], ["BTC", "ETH"], concurrency=1
        )

    assert len(positions) == 2
    coins = {p.coin for p in positions}
    assert coins == {"BTC", "ETH"}


@respx.mock
@pytest.mark.asyncio
async def test_positions_normalizes_hip3_coin():
    """xyz: prefix is stripped from HIP-3 coin names.

    Verified against live clearinghouseState with dex="xyz" on 2026-06-17:
    coins come back as "xyz:SPCX", "xyz:TSLA", etc. -- NOT "@N" suffixes.
    """
    wallet = "0xwallet2"
    empty = {"assetPositions": []}
    xyz_payload = {
        "assetPositions": [
            {
                "type": "oneWay",
                "position": {
                    "coin": "xyz:SPCX",  # confirmed live format
                    "szi": "100.0",
                    "entryPx": "50",
                    "unrealizedPnl": "200",
                    "marginUsed": "1000",
                    "positionValue": "5200",
                    "liquidationPx": "30",
                }
            },
        ]
    }
    # First call = native dex (no dex param) -- empty
    # Second call = xyz dex -- has SPCX
    respx.post(INFO_URL).mock(side_effect=[
        httpx.Response(200, json=empty),
        httpx.Response(200, json=xyz_payload),
    ])

    async with httpx.AsyncClient() as client:
        positions = await fetch_positions(
            client, [wallet], ["SPCX"], concurrency=1
        )

    assert len(positions) == 1
    assert positions[0].coin == "SPCX"


@respx.mock
@pytest.mark.asyncio
async def test_positions_skips_closed_positions():
    """Zero-size positions (closed) are filtered out."""
    wallet = "0xwallet3"
    payload = {
        "assetPositions": [
            {
                "position": {
                    "coin": "BTC",
                    "szi": "0.0",  # closed
                    "entryPx": "40000",
                    "unrealizedPnl": "0",
                    "marginUsed": "0",
                    "positionValue": "0",
                    "liquidationPx": None,
                }
            },
        ]
    }
    respx.post(INFO_URL).mock(side_effect=[
        httpx.Response(200, json=payload),
        httpx.Response(200, json={"assetPositions": []}),  # xyz dex empty
    ])

    async with httpx.AsyncClient() as client:
        positions = await fetch_positions(
            client, [wallet], ["BTC"], concurrency=1
        )

    assert len(positions) == 0
