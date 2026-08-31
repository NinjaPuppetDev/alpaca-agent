"""Tests for AlpacaClient wrapper."""

import pytest
from agent.trading.alpaca_client import AlpacaClient


def test_alpaca_client_account_and_price():
    client = AlpacaClient()
    account = client.get_account()
    assert "cash" in account
    assert "equity" in account
    assert account["cash"] > 0

    price = client.get_latest_price("NVDA")
    assert isinstance(price, float)
    assert price > 0


def test_alpaca_client_news_and_bars():
    client = AlpacaClient()
    news = client.get_news(limit=5)
    assert len(news) > 0
    assert "headline" in news[0]

    bars = client.get_bars("NVDA", limit=10)
    assert len(bars) > 0
    assert "close" in bars[0]
    assert "vwap" in bars[0]


def test_alpaca_client_options_and_orders():
    client = AlpacaClient()
    contracts = client.get_option_contracts("NVDA", option_type="put")
    assert len(contracts) > 0
    assert contracts[0]["type"] == "put"

    # Stock order
    stock_order = client.submit_stock_order(symbol="NVDA", qty=10, side="buy")
    assert stock_order["status"] in ("filled", "accepted", "new")

    positions = client.get_positions()
    assert any(p["symbol"] == "NVDA" for p in positions)

    # Option order
    opt_order = client.place_option_order(symbol=contracts[0]["symbol"], qty=1, side="buy")
    assert opt_order["status"] in ("filled", "accepted", "new")

    # Close position
    close_res = client.close_position("NVDA")
    assert close_res["status"] in ("closed", "closed_noop")
