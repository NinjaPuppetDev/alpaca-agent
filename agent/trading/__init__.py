"""Trading client and risk analysis package."""
from agent.trading.alpaca_client import AlpacaClient, get_alpaca_client
from agent.trading.risk import (
    calculate_portfolio_exposure,
    confirm_signal_with_vwap,
    select_hedge_structure,
    calculate_vwap
)

__all__ = [
    "AlpacaClient",
    "get_alpaca_client",
    "calculate_portfolio_exposure",
    "confirm_signal_with_vwap",
    "select_hedge_structure",
    "calculate_vwap"
]
