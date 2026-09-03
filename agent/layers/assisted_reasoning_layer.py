"""Intermediate assistant reasoning layer between signal generation and order routing."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional

from agent.data.db import SessionLocal
from agent.data.models import DecisionLog
from agent.risk.vwap_guard import evaluate_vwap_and_tp

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _trade_symbol(trade: Mapping[str, Any]) -> str:
    return str(trade.get("symbol") or trade.get("ticker") or "UNKNOWN")


def run_assisted_reasoning_layer(
    proposed_trades: Optional[Iterable[Mapping[str, Any]]],
    market_context: Optional[Mapping[str, Any]],
    llm: Optional[Any],
) -> Dict[str, Any]:
    """Evaluate trade ideas before they reach order routing.

    The layer applies VWAP guardrails to long entry ideas and ensures large
    allocations are covered by a protective option overlay. It writes a DecisionLog
    under layer='assistant_reasoning' and returns a JSON-compatible structure.
    """
    trades = list(proposed_trades or [])
    context = dict(market_context or {})
    approved_trades: List[Dict[str, Any]] = []
    rejected_trades: List[Dict[str, Any]] = []
    notes: List[str] = []

    positions_by_symbol = {
        str(k): v for k, v in dict(context.get("positions", {}) or {}).items()
    }
    vwap_by_symbol = {
        str(k): _safe_float(v) for k, v in dict(context.get("vwap_prices", {}) or {}).items()
    }
    current_prices = {
        str(k): _safe_float(v) for k, v in dict(context.get("current_prices", {}) or {}).items()
    }

    for trade in trades:
        trade_copy = dict(trade)
        symbol = _trade_symbol(trade_copy)
        qty = _safe_float(trade_copy.get("quantity", trade_copy.get("qty", 0.0)), 0.0)
        current_price = (
            _safe_float(trade_copy.get("current_price"), current_prices.get(symbol, 0.0))
            or current_prices.get(symbol, 0.0)
        )
        vwap_price = (
            _safe_float(trade_copy.get("vwap_price"), vwap_by_symbol.get(symbol, 0.0))
            or vwap_by_symbol.get(symbol, 0.0)
        )
        position = trade_copy.get("position") or positions_by_symbol.get(symbol)

        if trade_copy.get("side", "buy").lower() in {"buy", "long"}:
            guard = evaluate_vwap_and_tp(position or {"quantity": qty, "entry_price": trade_copy.get("entry_price", current_price)}, current_price, vwap_price)
            trade_copy["vwap_guard"] = guard

            if guard.get("is_chasing"):
                rejection = {
                    **trade_copy,
                    "reason": "Rejected: trade is chasing VWAP above the 1.5% guardrail.",
                    "guard": guard,
                }
                rejected_trades.append(rejection)
                notes.append(f"{symbol}: VWAP chase guard triggered; buy was rejected.")
                continue

        large_allocation = bool(
            _safe_float(trade_copy.get("allocation_pct", trade_copy.get("allocation", 0.0)), 0.0) >= 5.0
            or _safe_float(trade_copy.get("notional", 0.0), 0.0) >= 50000.0
        )
        hedge_confirmed = bool(
            trade_copy.get("protective_hedge_confirmed")
            or trade_copy.get("hedge_overlay")
            or trade_copy.get("requires_hedge_overlay") is False
        )

        if large_allocation and not hedge_confirmed:
            rejection = {
                **trade_copy,
                "reason": "Rejected: large allocation requires an explicit protective option hedge overlay.",
            }
            rejected_trades.append(rejection)
            notes.append(f"{symbol}: large allocation requires protective hedge overlay before approval.")
            continue

        if trade_copy.get("side", "buy").lower() in {"sell", "exit", "short"}:
            guard = evaluate_vwap_and_tp(position or {"quantity": qty, "entry_price": trade_copy.get("entry_price", current_price)}, current_price, vwap_price)
            trade_copy["vwap_guard"] = guard
            if guard.get("action") == "TAKE_PROFIT_PARTIAL":
                trade_copy["partial_exit_qty"] = guard.get("qty")
                trade_copy["risk_action"] = guard.get("action")

        approved_trades.append(trade_copy)

    assistant_notes = "; ".join(notes) if notes else "Assistant reasoning confirmed the proposed trades without risk guard triggers."
    decision_log = DecisionLog(
        layer="assistant_reasoning",
        input_summary={
            "proposed_trades": trades,
            "market_context": context,
            "approved_count": len(approved_trades),
            "rejected_count": len(rejected_trades),
        },
        reasoning=assistant_notes,
        action_taken=json.dumps({
            "approved": [t.get("symbol", "UNKNOWN") for t in approved_trades],
            "rejected": [t.get("symbol", "UNKNOWN") for t in rejected_trades],
        }),
    )

    db = SessionLocal()
    try:
        db.add(decision_log)
        db.commit()
    except Exception:
        logger.exception("Failed to persist assistant reasoning decision log")
    finally:
        db.close()

    return {
        "approved_trades": approved_trades,
        "rejected_trades": rejected_trades,
        "assistant_notes": assistant_notes,
    }
