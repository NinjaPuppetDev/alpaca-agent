"""Test isolation: never permit the suite to reach Alpaca or the developer database."""

import os
import tempfile
import uuid

# Must be configured before application modules import Settings.
os.environ["ALPACA_API_KEY"] = ""
os.environ["ALPACA_SECRET_KEY"] = ""
os.environ["ALPACA_PAPER"] = "true"
os.environ["AUTONOMOUS_MODE"] = "false"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/alpaca-agent-tests-{uuid.uuid4().hex}.db"

import pytest


@pytest.fixture(autouse=True)
def isolated_broker(monkeypatch):
    """Inject one explicit offline client into all API and layer entry points."""
    from agent.trading.alpaca_client import AlpacaClient
    from agent import api
    from agent.layers import derivatives_overlay, expiration_watchdog, theme_portfolio

    client = AlpacaClient(api_key="", secret_key="", paper=True)
    monkeypatch.setattr(api.routes, "get_alpaca_client", lambda: client)
    monkeypatch.setattr(theme_portfolio, "get_alpaca_client", lambda: client)
    monkeypatch.setattr(derivatives_overlay, "get_alpaca_client", lambda: client)
    monkeypatch.setattr(expiration_watchdog, "get_alpaca_client", lambda: client)
    return client
