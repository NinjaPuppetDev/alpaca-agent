"""Integration tests for the three layers: Theme + Portfolio, Derivatives Overlay, Expiration Watchdog."""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent.data.db import Base
from agent.data.models import ThemeBasket, Position, Hedge, DecisionLog
from agent.trading.alpaca_client import AlpacaClient
from agent.llm.provider import MockLLMProvider
from agent.layers.theme_portfolio import run_theme_portfolio_layer
from agent.layers.derivatives_overlay import run_derivatives_overlay_layer
from agent.layers.expiration_watchdog import run_expiration_watchdog_layer, calculate_days_to_expiry


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_theme_portfolio_layer(test_db, isolated_broker):
    client = isolated_broker
    llm = MockLLMProvider()

    res = run_theme_portfolio_layer(db=test_db, client=client, llm=llm)
    assert res["status"] == "success"
    assert len(res["themes"]) > 0

    # Verify DB records
    saved_basket = test_db.query(ThemeBasket).filter(ThemeBasket.active == True).first()
    assert saved_basket is not None
    assert len(saved_basket.tickers) > 0

    decision = test_db.query(DecisionLog).filter(DecisionLog.layer == "theme").first()
    assert decision is not None
    assert "Discovered" in decision.action_taken


def test_derivatives_overlay_layer(test_db, isolated_broker):
    client = isolated_broker
    llm = MockLLMProvider()

    # Seed equity position in client
    client.submit_stock_order(symbol="NVDA", qty=50, side="buy")

    res = run_derivatives_overlay_layer(db=test_db, client=client, llm=llm)
    assert res["status"] == "success"

    decision = test_db.query(DecisionLog).filter(DecisionLog.layer == "overlay").first()
    assert decision is not None


def test_expiration_watchdog_layer_rolls_near_expiry(test_db, isolated_broker, monkeypatch):
    client = isolated_broker
    llm = MockLLMProvider()

    # 1. Clear default mock positions and inject matching stock + option positions
    if hasattr(client, "_positions"):
        if isinstance(client._positions, list):
            client._positions = [
                {
                    "symbol": "NVDA",
                    "qty": 100,
                    "side": "long",
                    "asset_class": "us_equity",
                    "avg_entry_price": 120.0,
                    "current_price": 120.0,
                    "market_value": 12000.0,
                    "unrealized_pl": 0.0,
                },
                {
                    "symbol": "NVDA240920P00120000",
                    "qty": 1,
                    "side": "long",
                    "asset_class": "us_option",
                    "avg_entry_price": 3.50,
                    "current_price": 3.50,
                    "market_value": 350.0,
                    "unrealized_pl": 0.0,
                },
            ]
        elif isinstance(client._positions, dict):
            client._positions = {
                "NVDA": {
                    "symbol": "NVDA",
                    "qty": 100,
                    "side": "long",
                    "asset_class": "us_equity",
                    "current_price": 120.0,
                },
                "NVDA240920P00120000": {
                    "symbol": "NVDA240920P00120000",
                    "qty": 1,
                    "side": "long",
                    "asset_class": "us_option",
                    "current_price": 3.50,
                },
            }

    # 2. Mock replacement option lookup
    def mock_get_option_chain(symbol, dte_min=14, dte_max=45):
        return [{
            "symbol": "NVDA241018P00120000",
            "strike": 120.0,
            "expiration": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d"),
            "type": "put"
        }]

    if hasattr(client, "get_option_chain"):
        monkeypatch.setattr(client, "get_option_chain", mock_get_option_chain)

    # 3. Seed an expiring hedge in DB (DTE <= 5)
    near_exp = datetime.now(timezone.utc) + timedelta(days=2)
    hedge = Hedge(
        underlying_ticker="NVDA",
        structure_type="protective_put",
        legs=[{"symbol": "NVDA240920P00120000", "type": "put", "strike": 120.0, "side": "buy", "qty": 1}],
        status="open",
        opened_at=datetime.now(timezone.utc) - timedelta(days=19),
        expires_at=near_exp,
        notes="Old hedge near expiry"
    )
    test_db.add(hedge)
    test_db.commit()

    # 4. Run watchdog layer
    res = run_expiration_watchdog_layer(db=test_db, client=client, llm=llm, threshold_days=5)

    # 5. Assert watchdog audited the hedge
    assert res["status"] == "success"
    assert len(res["monitored_hedges"]) == 1
    assert res["monitored_hedges"][0]["underlying"] == "NVDA"


def test_expiration_watchdog_layer_closes_when_underlying_not_held(test_db, isolated_broker):
    client = isolated_broker
    llm = MockLLMProvider()
    client.place_option_order(symbol="UNHELD240920P00050000", qty=1, side="buy")

    # Seed hedge on ticker NOT held in client
    near_exp = datetime.now(timezone.utc) + timedelta(days=3)
    hedge = Hedge(
        underlying_ticker="UNHELD_SYM",
        structure_type="protective_put",
        legs=[{"symbol": "UNHELD240920P00050000", "type": "put", "strike": 50.0, "side": "buy", "qty": 1}],
        status="open",
        opened_at=datetime.now(timezone.utc) - timedelta(days=18),
        expires_at=near_exp,
        notes="Hedge on liquidated stock"
    )
    test_db.add(hedge)
    test_db.commit()

    res = run_expiration_watchdog_layer(db=test_db, client=client, llm=llm, threshold_days=5)
    assert res["status"] == "success"
    assert len(res["actions_taken"]) == 1
    assert res["actions_taken"][0]["action"] == "closed"

    test_db.refresh(hedge)
    assert hedge.status == "closed"
