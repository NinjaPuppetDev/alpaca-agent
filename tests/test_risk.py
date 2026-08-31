"""Tests for risk analysis, VWAP confirmation, and hedge selection."""

import pytest
from agent.trading.risk import (
    calculate_vwap,
    confirm_signal_with_vwap,
    calculate_portfolio_exposure,
    select_hedge_structure,
    ALLOWED_STRUCTURES
)


def test_calculate_vwap():
    bars = [
        {"high": 105.0, "low": 95.0, "close": 100.0, "volume": 1000},  # tp = 100, vol = 1000
        {"high": 115.0, "low": 105.0, "close": 110.0, "volume": 2000},  # tp = 110, vol = 2000
    ]
    # (100*1000 + 110*2000) / 3000 = (100000 + 220000) / 3000 = 320000 / 3000 = 106.6667
    vwap = calculate_vwap(bars)
    assert abs(vwap - 106.6667) < 0.01


def test_confirm_signal_with_vwap():
    bars = [
        {"high": 102.0, "low": 98.0, "close": 100.0, "volume": 1000},
        {"high": 101.0, "low": 95.0, "close": 96.0, "volume": 2500},
    ]
    # Price is 96, VWAP is ~98.3, high volume -> should confirm bearish
    res = confirm_signal_with_vwap("TEST", bars, current_price=96.0)
    assert res["confirmed"] is True
    assert res["direction"] == "bearish"


def test_select_hedge_structures():
    contracts = [
        {"symbol": "NVDA240920P00115000", "type": "put", "strike_price": 115.0, "expiration_date": "2026-09-18"},
        {"symbol": "NVDA240920P00120000", "type": "put", "strike_price": 120.0, "expiration_date": "2026-09-18"},
        {"symbol": "NVDA240920C00135000", "type": "call", "strike_price": 135.0, "expiration_date": "2026-09-18"},
        {"symbol": "NVDA240920C00140000", "type": "call", "strike_price": 140.0, "expiration_date": "2026-09-18"},
    ]

    # 1. Protective Put
    put_hedge = select_hedge_structure("downside_risk", 80.0, contracts, "NVDA")
    assert put_hedge["structure_type"] in ALLOWED_STRUCTURES
    assert len(put_hedge["legs"]) >= 1
    assert put_hedge["legs"][0]["type"] == "put"
    assert put_hedge["legs"][0]["side"] == "buy"

    # 2. Collar
    collar_hedge = select_hedge_structure("downside_risk", 130.0, contracts, "NVDA")
    assert collar_hedge["structure_type"] == "collar"
    assert len(collar_hedge["legs"]) == 2
    types = {leg["type"] for leg in collar_hedge["legs"]}
    assert "put" in types and "call" in types

    # 3. Covered Call
    cc_hedge = select_hedge_structure("range_bound", 125.0, contracts, "NVDA")
    assert cc_hedge["structure_type"] == "covered_call"
    assert cc_hedge["legs"][0]["side"] == "sell"

    # 4. Vertical Spread
    vs_hedge = select_hedge_structure("defined_downside", 125.0, contracts, "NVDA")
    assert vs_hedge["structure_type"] == "vertical_spread"
    assert len(vs_hedge["legs"]) == 2


def test_calculate_portfolio_exposure():
    positions = [
        {"symbol": "NVDA", "qty": 100, "market_value": 12000.0, "asset_class": "us_equity"},
        {"symbol": "AMD", "qty": 50, "market_value": 7500.0, "asset_class": "us_equity"}
    ]
    exp = calculate_portfolio_exposure(positions, total_equity=100000.0)
    assert exp["total_market_value"] == 19500.0
    assert exp["gross_exposure_pct"] == 19.5
    assert exp["position_count"] == 2
