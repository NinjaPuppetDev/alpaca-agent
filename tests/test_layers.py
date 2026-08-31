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


def test_theme_portfolio_layer(test_db):
    client = AlpacaClient()
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


def test_derivatives_overlay_layer(test_db):
    client = AlpacaClient()
    llm = MockLLMProvider()

    # Seed equity position in client
    client.submit_stock_order(symbol="NVDA", qty=50, side="buy")

    res = run_derivatives_overlay_layer(db=test_db, client=client, llm=llm)
    assert res["status"] == "success"

    decision = test_db.query(DecisionLog).filter(DecisionLog.layer == "overlay").first()
    assert decision is not None


def test_expiration_watchdog_layer_rolls_near_expiry(test_db):
    client = AlpacaClient()
    llm = MockLLMProvider()

    # Seed an equity holding
    client.submit_stock_order(symbol="NVDA", qty=100, side="buy")

    # Seed a hedge expiring in 2 days (within threshold of 5 days)
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

    # Run watchdog
    res = run_expiration_watchdog_layer(db=test_db, client=client, llm=llm, threshold_days=5)
    assert res["status"] == "success"
    assert len(res["actions_taken"]) == 1
    assert res["actions_taken"][0]["action"] == "rolled"

    # Old hedge should now be rolled
    test_db.refresh(hedge)
    assert hedge.status == "rolled"

    # A new open hedge should be created with > 15 DTE
    new_hedge = test_db.query(Hedge).filter(Hedge.status == "open").first()
    assert new_hedge is not None
    assert new_hedge.id != hedge.id
    assert calculate_days_to_expiry(new_hedge.expires_at) > 10


def test_expiration_watchdog_layer_closes_when_underlying_not_held(test_db):
    client = AlpacaClient()
    llm = MockLLMProvider()

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
