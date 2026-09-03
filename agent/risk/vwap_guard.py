"""VWAP and take-profit guardrails for entry and exit decisions."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

TAKE_PROFIT_PARTIAL = "TAKE_PROFIT_PARTIAL"
VWAP_CHASE_MULTIPLIER = 1.015


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _position_value(position: Any, key: str, default: float = 0.0) -> float:
    if isinstance(position, Mapping):
        return _coerce_float(position.get(key), default)
    return _coerce_float(getattr(position, key, default), default)


def calculate_vwap(ticks: Iterable[Mapping[str, Any]]) -> float:
    """Return the intraday VWAP for a collection of tick/bar records."""
    ticks = list(ticks or [])
    if not ticks:
        return 0.0

    total_price_volume = 0.0
    total_volume = 0.0
    for tick in ticks:
        price = _coerce_float(
            tick.get("price", tick.get("close", tick.get("last", 0.0))),
            0.0,
        )
        volume = _coerce_float(tick.get("volume", 0.0), 0.0)
        total_price_volume += price * volume
        total_volume += volume

    if total_volume <= 0:
        return 0.0
    return total_price_volume / total_volume


def evaluate_vwap_and_tp(
    position: Any,
    current_price: float,
    vwap_price: float,
    tp_threshold: float = 0.08,
) -> Dict[str, Any]:
    """Guard against chasing news spikes and enforce partial profit-taking.

    A position is considered 'chasing' if the market price is more than 1.5% above
    intraday VWAP. If the unrealized gain exceeds the configured threshold, the
    function returns a TAKE_PROFIT_PARTIAL action sized at 50% of the quantity.
    """
    qty = max(0.0, _position_value(position, "quantity", _position_value(position, "qty", 0.0)))
    entry_price = max(
        1e-9,
        _position_value(position, "entry_price", _position_value(position, "avg_entry_price", 0.0)),
    )
    unrealized_gain_pct = ((float(current_price) - entry_price) / entry_price) if entry_price > 0 else 0.0
    vwap_guard_price = float(vwap_price) * VWAP_CHASE_MULTIPLIER
    is_chasing = bool(float(current_price) > vwap_guard_price)

    action = None
    partial_qty = 0
    notes: list[str] = []

    if unrealized_gain_pct >= float(tp_threshold):
        partial_qty = max(1, int(qty * 0.5)) if qty > 0 else 1
        action = TAKE_PROFIT_PARTIAL
        notes.append(
            f"Unrealized gain {unrealized_gain_pct:.2%} passed the {tp_threshold:.2%} take-profit threshold."
        )
    if is_chasing:
        notes.append(
            f"Current price ${current_price:.2f} exceeds VWAP guard rail (${vwap_guard_price:.2f}); suppressing chase entry."
        )

    return {
        "symbol": getattr(position, "ticker", None) if not isinstance(position, Mapping) else position.get("symbol", position.get("ticker")),
        "is_chasing": is_chasing,
        "entry_guardrail": {
            "triggered": is_chasing,
            "current_price": float(current_price),
            "vwap_price": float(vwap_price),
            "guard_price": vwap_guard_price,
        },
        "unrealized_gain_pct": unrealized_gain_pct,
        "take_profit_action": {
            "triggered": action is not None,
            "action": action,
            "qty": partial_qty,
            "threshold": float(tp_threshold),
        },
        "action": action,
        "qty": partial_qty,
        "notes": " | ".join(notes) if notes else "No VWAP or TP guardrail triggered.",
    }
