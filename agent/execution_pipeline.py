"""Simple execution pipeline hooks for VWAP and assistant reasoning guardrails."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from agent.layers.assisted_reasoning_layer import run_assisted_reasoning_layer
from agent.risk.vwap_guard import evaluate_vwap_and_tp


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_order_guardrails(
    order: Mapping[str, Any],
    client: Any,
    market_context: Optional[Mapping[str, Any]] = None,
    llm: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run the common pre-routing approval gate for every stock order path."""
    symbol = str(order.get("symbol") or order.get("ticker") or "").upper()
    side = str(order.get("side", "buy")).lower()
    quantity = _safe_float(order.get("quantity", order.get("qty", 0.0)))
    context = dict(market_context or {})
    current_price = _safe_float(
        order.get("current_price"),
        _safe_float(dict(context.get("current_prices", {})).get(symbol), 0.0),
    )
    if current_price <= 0:
        current_price = _safe_float(client.get_latest_price(symbol), 0.0)
    vwap_price = _safe_float(
        order.get("vwap_price"),
        _safe_float(dict(context.get("vwap_prices", {})).get(symbol), current_price),
    )

    proposed = dict(order)
    proposed.update({
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "qty": quantity,
        "current_price": current_price,
        "vwap_price": vwap_price,
    })
    result = run_assisted_reasoning_layer([proposed], context, llm)
    approved = bool(result.get("approved_trades"))
    return {
        "approved": approved,
        "order": result.get("approved_trades", [None])[0] if approved else proposed,
        "rejection": result.get("rejected_trades", [None])[0] if not approved else None,
        "assistant_reasoning": result,
    }


def submit_guarded_stock_order(
    client: Any,
    order: Mapping[str, Any],
    market_context: Optional[Mapping[str, Any]] = None,
    llm: Optional[Any] = None,
) -> Dict[str, Any]:
    """Approve a stock order through the shared gate, then submit it once."""
    guard = evaluate_order_guardrails(order, client, market_context, llm)
    if not guard["approved"]:
        rejection = guard["rejection"] or {}
        return {
            "status": "REJECTED_GUARDRAIL",
            "symbol": order.get("symbol"),
            "reason": rejection.get("reason", "Order rejected by assistant reasoning guardrail."),
            "guardrail": guard,
        }
    approved = guard["order"]
    return client.submit_stock_order(
        symbol=approved["symbol"],
        qty=approved["quantity"],
        side=approved["side"],
        order_type=str(order.get("order_type", "market")),
    )


def validate_option_overlay_legs(legs: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    """Reject malformed option orders before they can reach the broker."""
    normalized = list(legs or [])
    if not normalized:
        return {"approved": False, "reason": "Protective option overlay contains no legs."}
    invalid = [
        leg for leg in normalized
        if not leg.get("symbol")
        or str(leg.get("side", "")).lower() not in {"buy", "sell"}
        or _safe_float(leg.get("qty", 1.0)) <= 0
    ]
    if invalid:
        return {"approved": False, "reason": "Protective option overlay contains an invalid leg."}
    return {"approved": True, "legs": normalized}


def run_execution_pipeline(
    proposed_trades: Optional[Iterable[Mapping[str, Any]]],
    positions: Optional[Iterable[Any]],
    market_context: Optional[Mapping[str, Any]],
    llm: Optional[Any] = None,
) -> Dict[str, Any]:
    """Wire VWAP TP evaluation and the assistant reasoning step into the trade cycle.

    This maintains the existing execution flow while inserting a lightweight decision
    layer between news-driven ideas and order routing.
    """
    existing_positions = list(positions or [])
    vwap_guard_checks: List[Dict[str, Any]] = []
    partial_liquidations: List[Dict[str, Any]] = []

    for position in existing_positions:
        current_price = float(position.get("current_price", 0.0) if isinstance(position, Mapping) else getattr(position, "current_price", 0.0))
        vwap_price = float(position.get("vwap_price", current_price) if isinstance(position, Mapping) else getattr(position, "vwap_price", current_price))
        guard = evaluate_vwap_and_tp(position, current_price, vwap_price)
        vwap_guard_checks.append(guard)
        if guard.get("action") == "TAKE_PROFIT_PARTIAL":
            partial_liquidations.append({
                "position": position,
                "partial_exit_qty": guard.get("qty"),
                "reason": guard.get("notes"),
            })

    assistant_result = run_assisted_reasoning_layer(proposed_trades, market_context, llm)
    return {
        "vwap_guard_checks": vwap_guard_checks,
        "partial_liquidations": partial_liquidations,
        "assistant_reasoning": assistant_result,
    }
