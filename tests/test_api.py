"""Route-function tests using an injected offline broker; no ASGI transport or network."""

import pytest

from agent.api import routes
from agent.data.db import SessionLocal, init_db


@pytest.fixture
def db():
    init_db()
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def test_api_status_endpoint(db):
    data = routes.get_agent_status(db)
    assert data["status"] == "paused"
    assert "theme_portfolio" in data["layers"]


def test_api_portfolio_endpoint(db):
    data = routes.get_portfolio(db)
    assert "account" in data
    assert "positions" in data
    assert "themes" in data


def test_api_hedges_endpoint(db):
    data = routes.get_hedges(status=None, db=db)
    assert "hedges" in data
    assert "open_count" in data


def test_api_decisions_endpoint(db):
    data = routes.get_decisions(layer=None, limit=50, db=db)
    assert isinstance(data, list)


def test_manual_trigger_obeys_kill_switch(db, monkeypatch):
    with pytest.raises(Exception) as exc_info:
        routes.trigger_layer("theme", db)
    assert getattr(exc_info.value, "status_code", None) == 403

    monkeypatch.setattr(routes, "is_kill_switch_active", lambda: False)
    data = routes.trigger_layer("theme", db)
    assert data["triggered"] == "theme_portfolio"
