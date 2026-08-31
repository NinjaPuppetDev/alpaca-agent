"""Tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient
from agent.main import app
from agent.data.db import init_db

init_db()
client = TestClient(app)


def test_api_status_endpoint():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "layers" in data
    assert "theme_portfolio" in data["layers"]
    assert "derivatives_overlay" in data["layers"]
    assert "expiration_watchdog" in data["layers"]


def test_api_portfolio_endpoint():
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "account" in data
    assert "positions" in data
    assert "themes" in data


def test_api_hedges_endpoint():
    response = client.get("/api/hedges")
    assert response.status_code == 200
    data = response.json()
    assert "hedges" in data
    assert "open_count" in data


def test_api_decisions_endpoint():
    response = client.get("/api/decisions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_manual_trigger():
    response = client.post("/api/trigger/theme")
    assert response.status_code == 200
    data = response.json()
    assert data["triggered"] == "theme_portfolio"

    response = client.post("/api/trigger/overlay")
    assert response.status_code == 200

    response = client.post("/api/trigger/watchdog")
    assert response.status_code == 200
