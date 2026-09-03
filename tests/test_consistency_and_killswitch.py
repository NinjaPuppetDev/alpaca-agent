"""State synchronization and kill-switch tests with an injected offline broker."""

import pytest

from agent.api import routes
from agent.data.db import SessionLocal, init_db
from agent.scheduler import is_autonomous_mode_active, job_theme_portfolio, set_autonomous_mode


@pytest.fixture
def db():
    init_db()
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def test_portfolio_decision_log_consistency(db, monkeypatch):
    monkeypatch.setattr(routes, "is_kill_switch_active", lambda: False)
    theme_data = routes.trigger_layer("theme", db)["result"]
    assert theme_data["status"] == "success"

    portfolio_data = routes.get_portfolio(db)
    equity_positions = [p for p in portfolio_data["positions"] if p.get("asset_class") != "us_option"]
    assert equity_positions
    executed_symbols = {o["symbol"] for o in theme_data["executed_orders"] if o["side"] == "buy"}
    assert executed_symbols.issubset({p["symbol"] for p in equity_positions})

    latest_decision = routes.get_decisions(layer="theme", limit=1, db=db)[0]
    assert "Executed" in latest_decision["action_taken"]


def test_portfolio_uses_live_broker_positions_as_source_of_truth(db, monkeypatch):
    from agent.data.models import Position

    stale = Position(ticker="OLDCO", quantity=12.0, entry_price=50.0, current_value=600.0)
    db.add(stale)
    db.commit()

    class FakeClient:
        is_live = True

        def get_account(self):
            return {"cash": 25000.0, "equity": 30000.0, "buying_power": 50000.0, "currency": "USD", "status": "ACTIVE"}

        def get_positions(self):
            return [{
                "symbol": "AAPL",
                "qty": 8.0,
                "avg_entry_price": 180.0,
                "current_price": 190.0,
                "market_value": 1520.0,
                "unrealized_pl": 80.0,
                "asset_class": "us_equity",
                "side": "long",
            }]

        def get_latest_price(self, symbol):
            return 190.0 if symbol == "AAPL" else 50.0

    monkeypatch.setattr(routes, "get_alpaca_client", lambda: FakeClient())

    portfolio_data = routes.get_portfolio(db)
    symbols = {p["symbol"] for p in portfolio_data["positions"] if p.get("asset_class") == "us_equity"}
    assert "AAPL" in symbols
    assert "OLDCO" not in symbols
    assert db.query(Position).filter(Position.ticker == "AAPL").first() is not None
    assert db.query(Position).filter(Position.ticker == "OLDCO").first() is None


def test_option_only_live_account_does_not_restore_stale_equity_cache(db, monkeypatch):
    from agent.data.models import Position

    stale = Position(ticker="IRDM", quantity=191.0, entry_price=46.6, current_value=8914.92)
    stale2 = Position(ticker="RKLB", quantity=163.59, entry_price=63.67, current_value=10181.02)
    db.add_all([stale, stale2])
    db.commit()

    class FakeClient:
        is_live = True

        def get_account(self):
            return {"cash": 97729.43, "equity": 97747.43, "buying_power": 390917.72, "currency": "USD", "status": "ACTIVE"}

        def get_positions(self):
            return [
                {"symbol": "MARA260904P00010000", "qty": 1.0, "avg_entry_price": 0.14, "current_price": 0.16, "market_value": 16.0, "unrealized_pl": 2.0, "asset_class": "us_option", "side": "long"},
                {"symbol": "NEE260904P00078000", "qty": 1.0, "avg_entry_price": 0.03, "current_price": 0.0, "market_value": 0.0, "unrealized_pl": -3.0, "asset_class": "us_option", "side": "long"},
                {"symbol": "SNAP260904P00005000", "qty": 2.0, "avg_entry_price": 0.01, "current_price": 0.01, "market_value": 2.0, "unrealized_pl": 0.0, "asset_class": "us_option", "side": "long"},
            ]

        def get_latest_price(self, symbol):
            return 0.0

    monkeypatch.setattr(routes, "get_alpaca_client", lambda: FakeClient())

    portfolio_data = routes.get_portfolio(db)
    assert portfolio_data["positions"] == []
    assert portfolio_data["option_positions_count"] == 3
    assert {p["symbol"] for p in portfolio_data["option_positions"]} == {
        "MARA260904P00010000",
        "NEE260904P00078000",
        "SNAP260904P00005000",
    }
    assert db.query(Position).count() == 0


def test_option_liquidation_routes_mirror_equity_smart_and_all(db, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.closed = []
            self.positions = [
                {"symbol": "LOSER", "qty": 1, "asset_class": "us_option", "current_price": 0.10, "market_value": 10, "unrealized_pl": -5},
                {"symbol": "WINNER", "qty": 2, "asset_class": "us_option", "current_price": 0.20, "market_value": 40, "unrealized_pl": 5},
                {"symbol": "STOCK", "qty": 1, "asset_class": "us_equity", "current_price": 100, "market_value": 100, "unrealized_pl": -10},
            ]

        def get_positions(self):
            return self.positions

        def close_position(self, symbol):
            self.closed.append(symbol)
            self.positions = [p for p in self.positions if p["symbol"] != symbol]
            return {"symbol": symbol, "status": "closed"}

    client = FakeClient()
    monkeypatch.setattr(routes, "get_alpaca_client", lambda: client)

    smart = routes.liquidate_smart_options(db)
    assert smart["closed_count"] == 1
    assert client.closed == ["LOSER"]

    all_options = routes.liquidate_all_options(db)
    assert all_options["closed_count"] == 1
    assert client.closed == ["LOSER", "WINNER"]


def test_autonomous_mode_kill_switch(db, monkeypatch):
    # Do not start APScheduler in a unit test; verify state and job gating directly.
    import agent.scheduler as scheduler_module
    monkeypatch.setattr(scheduler_module, "start_scheduler", lambda: None)

    off = set_autonomous_mode(False, db=db)
    assert off["autonomous_mode"] is False
    assert is_autonomous_mode_active() is False
    assert routes.get_agent_status(db)["status"] == "paused"
    job_theme_portfolio()  # must be a no-op while the kill switch is active

    on = set_autonomous_mode(True, db=db)
    assert on["autonomous_mode"] is True
    assert routes.get_agent_status(db)["status"] == "online"
    set_autonomous_mode(False, db=db)
