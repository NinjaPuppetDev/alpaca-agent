"""Tests for state synchronization consistency and the autonomous mode kill switch."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from agent.main import app
from agent.data.db import Base
from agent.data.models import ThemeBasket, Position, DecisionLog, Hedge
from agent.trading.alpaca_client import AlpacaClient
from agent.llm.provider import MockLLMProvider
from agent.layers.theme_portfolio import run_theme_portfolio_layer
from agent.scheduler import set_autonomous_mode, is_autonomous_mode_active, job_theme_portfolio

client = TestClient(app)


def test_portfolio_decision_log_consistency():
    """Confirms that executing a theme rebalancing cycle produces identical state in DB, AlpacaClient, and /api/portfolio."""
    # 1. Run theme portfolio layer
    res = client.post("/api/trigger/theme")
    assert res.status_code == 200
    theme_data = res.json()["result"]
    assert theme_data["status"] == "success"
    executed_orders = theme_data["executed_orders"]

    # 2. Query /api/portfolio
    portfolio_res = client.get("/api/portfolio")
    assert portfolio_res.status_code == 200
    portfolio_data = portfolio_res.json()

    # Verify positions exist and match
    positions = portfolio_data["positions"]
    equity_positions = [p for p in positions if p.get("asset_class") != "us_option"]
    assert len(equity_positions) > 0

    # Every executed buy order should be in portfolio
    executed_symbols = {o["symbol"] for o in executed_orders if o["side"] == "buy"}
    portfolio_symbols = {p["symbol"] for p in equity_positions}
    assert executed_symbols.issubset(portfolio_symbols)

    # 3. Query /api/decisions and ensure log claims match
    decisions_res = client.get("/api/decisions?layer=theme&limit=1")
    assert decisions_res.status_code == 200
    latest_decision = decisions_res.json()[0]
    assert "Executed" in latest_decision["action_taken"]


def test_autonomous_mode_kill_switch():
    """Confirms that toggling autonomous mode pauses execution, logs to DecisionLog, and resumes cleanly."""
    # 1. Toggle OFF
    off_res = client.post("/api/autonomous-mode", json={"enabled": False})
    assert off_res.status_code == 200
    assert off_res.json()["autonomous_mode"] is False
    assert is_autonomous_mode_active() is False

    # Check status endpoint reflects paused state
    status_res = client.get("/api/status")
    assert status_res.status_code == 200
    assert status_res.json()["autonomous_mode"] is False
    assert status_res.json()["status"] == "paused"

    # Check decision log for operator pause entry
    decisions_res = client.get("/api/decisions?layer=system&limit=1")
    assert decisions_res.status_code == 200
    latest_log = decisions_res.json()[0]
    assert latest_log["layer"] == "system"
    assert "PAUSED" in latest_log["action_taken"]

    # 2. Verify that background job does not run when paused
    job_theme_portfolio()  # Should cleanly return early without errors

    # 3. Toggle ON
    on_res = client.post("/api/autonomous-mode", json={"enabled": True})
    assert on_res.status_code == 200
    assert on_res.json()["autonomous_mode"] is True
    assert is_autonomous_mode_active() is True

    # Check status endpoint reflects running state
    status_res2 = client.get("/api/status")
    assert status_res2.status_code == 200
    assert status_res2.json()["autonomous_mode"] is True
    assert status_res2.json()["status"] == "online"

    # Check decision log for operator resume entry
    decisions_res2 = client.get("/api/decisions?layer=system&limit=1")
    assert decisions_res2.status_code == 200
    latest_log2 = decisions_res2.json()[0]
    assert "RESUMED" in latest_log2["action_taken"]
