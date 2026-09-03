"""Tests for risk analysis, VWAP confirmation, and hedge selection."""

import pytest
from agent.trading.risk import (
    calculate_vwap,
    confirm_signal_with_vwap,
    calculate_portfolio_exposure,
    select_hedge_structure,
    ALLOWED_STRUCTURES
)
from agent.execution_pipeline import validate_option_overlay_legs
from agent.risk.vwap_guard import evaluate_vwap_and_tp


def test_calculate_vwap():
    bars = [
        {"high": 105.0, "low": 95.0, "close": 100.0, "volume": 1000},  # tp = 100, vol = 1000
        {"high": 115.0, "low": 105.0, "close": 110.0, "volume": 2000},  # tp = 110, vol = 2000
    ]
    # (100*1000 + 110*2000) / 3000 = (100000 + 220000) / 3000 = 320000 / 3000 = 106.6667
    vwap = calculate_vwap(bars)
    assert abs(vwap - 106.6667) < 0.01


def test_order_guardrails_reject_vwap_chase_and_validate_legs():
    guard = evaluate_vwap_and_tp(
        {"symbol": "NVDA", "qty": 10, "entry_price": 100.0},
        current_price=102.0,
        vwap_price=100.0,
    )
    assert guard["is_chasing"] is True
    assert validate_option_overlay_legs([])["approved"] is False
    assert validate_option_overlay_legs([{"symbol": "NVDA260918P00100", "side": "buy", "qty": 1}])["approved"] is True


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
        {"symbol": "NVDA240920P00115000", "type": "put", "strike_price": 115.0, "expiration_date": "2026-09-18", "open_interest": 100, "bid_price": 3.0, "ask_price": 3.5},
        {"symbol": "NVDA240920P00120000", "type": "put", "strike_price": 120.0, "expiration_date": "2026-09-18", "open_interest": 100, "bid_price": 3.0, "ask_price": 3.5},
    ]

    # 1. Protective Put
    put_hedge = select_hedge_structure("downside_risk", 120.0, contracts, "NVDA", stock_qty=200)
    assert put_hedge["structure_type"] in ALLOWED_STRUCTURES
    assert len(put_hedge["legs"]) >= 1
    assert put_hedge["legs"][0]["type"] == "put"
    assert put_hedge["legs"][0]["side"] == "buy"

    assert put_hedge["legs"][0]["qty"] == 2

    rejected = select_hedge_structure("downside_risk", 120.0, contracts, "NVDA", stock_qty=150)
    assert rejected["legs"] == []
    assert rejected["rejection"] == "UNHEDGED_REMAINDER_OR_SUB_LOT"


def test_calculate_portfolio_exposure():
    positions = [
        {"symbol": "NVDA", "qty": 100, "market_value": 12000.0, "asset_class": "us_equity"},
        {"symbol": "AMD", "qty": 50, "market_value": 7500.0, "asset_class": "us_equity"}
    ]
    exp = calculate_portfolio_exposure(positions, total_equity=100000.0)
    assert exp["total_market_value"] == 19500.0
    assert exp["gross_exposure_pct"] == 19.5
    assert exp["position_count"] == 2
