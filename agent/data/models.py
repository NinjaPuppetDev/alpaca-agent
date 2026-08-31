"""SQLAlchemy ORM models for portfolio state, options hedges, and decision audits."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
from agent.data.db import Base


class ThemeBasket(Base):
    """Theme basket discovered from market news."""
    __tablename__ = "theme_baskets"

    id = Column(Integer, primary_key=True, index=True)
    theme_name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    tickers = Column(JSON, nullable=False)  # e.g., ["FCX", "SCCO", "VALE"] or [{"ticker": "NVDA", ...}]
    allocation_weights = Column(JSON, nullable=False)  # e.g., {"FCX": 0.33, "SCCO": 0.33, "VALE": 0.34}
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    positions = relationship("Position", back_populates="theme")


class Position(Base):
    """Held equity position in the portfolio."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, unique=True, index=True)
    quantity = Column(Float, nullable=False, default=0.0)
    entry_price = Column(Float, nullable=False, default=0.0)
    current_value = Column(Float, nullable=False, default=0.0)
    theme_id = Column(Integer, ForeignKey("theme_baskets.id"), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    theme = relationship("ThemeBasket", back_populates="positions")


class Hedge(Base):
    """Derivative overlay hedge position protecting an underlying stock."""
    __tablename__ = "hedges"

    id = Column(Integer, primary_key=True, index=True)
    underlying_ticker = Column(String(20), nullable=False, index=True)
    structure_type = Column(String(50), nullable=False)  # "protective_put", "collar", "covered_call", "vertical_spread"
    legs = Column(JSON, nullable=False)  # e.g. [{"symbol": "AAPL240920P00210000", "type": "put", "strike": 210, "side": "buy", "qty": 1}]
    status = Column(String(20), default="open", index=True)  # "open", "closed", "rolled"
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    closed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)


class DecisionLog(Base):
    """Audit log backing the agent's write-up and decision feed."""
    __tablename__ = "decision_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    layer = Column(String(50), nullable=False, index=True)  # "theme", "overlay", "watchdog"
    input_summary = Column(JSON, nullable=False)  # news headlines, risk metrics, expiry alerts
    reasoning = Column(Text, nullable=False)  # LLM output or rule description
    action_taken = Column(Text, nullable=False)  # orders placed, positions closed/rolled, no-op
