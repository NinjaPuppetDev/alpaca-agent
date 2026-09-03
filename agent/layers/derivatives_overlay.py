"""Derivatives Overlay Layer (Hourly Cadence).

Responsibilities:
1. Pull current portfolio positions and exposures.
2. News-gate: Check recent news headlines for held tickers.
3. Confirmation: Validate any news-driven catalyst with intraday VWAP divergence & volume expansion.
4. Risk classification: Use LLM / rules to evaluate exposure shape (downside risk / range-bound / income).
5. Structure selection: Select from allowed structures only:
   - Protective Put
   - Zero/Low-cost Collar
   - Covered Call
   - Vertical Spread (Bear Put / Bull Call)
   (Never standalone directional bets, never butterflies/condors).
6. Execute option trades via Alpaca Paper Trading.
7. Record open Hedge position and audit DecisionLog.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging
from sqlalchemy.orm import Session

from agent.trading.alpaca_client import get_alpaca_client, AlpacaClient
from agent.trading.risk import (
    calculate_portfolio_exposure,
    confirm_signal_with_vwap,
    select_hedge_structure,
    calculate_vwap,
)
from agent.llm.provider import get_llm_provider, LLMProvider
from agent.data.db import SessionLocal
from agent.data.models import Hedge, DecisionLog
from agent.risk.vwap_guard import evaluate_vwap_and_tp
from agent.execution_pipeline import validate_option_overlay_legs

logger = logging.getLogger(__name__)


def _all_orders_filled(order_results: List[Dict[str, Any]]) -> bool:
    """Only broker-confirmed fills are eligible for persistent hedge state."""
    return bool(order_results) and all(order.get("status") == "filled" for order in order_results)


def evaluate_ticker_risk(
    symbol: str,
    client: AlpacaClient,
    llm: LLMProvider
) -> Dict[str, Any]:
    """Evaluates risk for a held ticker: news check + VWAP/volume confirmation + LLM exposure classification.

    Args:
        symbol: Held ticker symbol.
        client: AlpacaClient.
        llm: LLMProvider.

    Returns:
        Dict detailing risk status, confirmation result, and recommended exposure shape.
    """
    # 1. Check news specifically for this ticker
    news = client.get_news(symbols=[symbol], limit=5)
    has_news = len(news) > 0

    # 2. Check VWAP and Volume confirmation
    bars = client.get_bars(symbol, timeframe_str="1Hour", limit=24)
    current_price = client.get_latest_price(symbol)
    vwap_check = confirm_signal_with_vwap(symbol, bars, current_price)

    # 3. Classify risk with LLM if news hit or strong VWAP breakdown
    exposure_shape = "neutral"
    rationale = ""

    if has_news or vwap_check["confirmed"]:
        news_summary = " | ".join([n.get("headline", "") for n in news[:2]])
        system_prompt = (
            "You are a derivatives risk manager for an equity portfolio. Given recent headlines and "
            "VWAP/volume confirmation, classify the equity exposure risk shape into one of:\n"
            "- 'downside_risk' (elevated drop risk, requires protective put or collar)\n"
            "- 'range_bound' (stagnation/sideways, suitable for covered call)\n"
            "- 'defined_downside' (moderate downward pressure, suitable for vertical spread)\n"
            "- 'neutral' (no immediate overlay required)\n"
            "Respond ONLY with a JSON object: {\"exposure_shape\": \"...\", \"reasoning\": \"...\"}"
        )
        user_prompt = (
            f"Ticker: {symbol}\n"
            f"Current Price: ${current_price:.2f}\n"
            f"VWAP: ${vwap_check['vwap']:.2f} (Diff: {vwap_check.get('price_diff_pct', 0):.2f}%)\n"
            f"Volume Ratio vs 24hr Avg: {vwap_check['volume_ratio']:.2f}x\n"
            f"Directional Confirmation: {vwap_check['direction']}\n"
            f"Recent Headlines: {news_summary or 'No major new headlines'}"
        )

        try:
            llm_res = llm.complete_json(prompt=user_prompt, system_prompt=system_prompt)
            exposure_shape = llm_res.get("exposure_shape", "downside_risk" if vwap_check["direction"] == "bearish" else "neutral")
            rationale = llm_res.get("reasoning", vwap_check["reasoning"])
        except Exception as e:
            logger.warning(f"LLM risk classification failed for {symbol}: {e}")
            if vwap_check["direction"] == "bearish":
                exposure_shape = "downside_risk"
                rationale = f"Rule-based trigger: {vwap_check['reasoning']}"
            else:
                exposure_shape = "neutral"
                rationale = "Signal unconfirmed."
    else:
        rationale = f"No catalyst or VWAP divergence detected for {symbol}."

    return {
        "symbol": symbol,
        "current_price": current_price,
        "has_news": has_news,
        "vwap_check": vwap_check,
        "exposure_shape": exposure_shape,
        "rationale": rationale
    }


def run_derivatives_overlay_layer(
    db: Optional[Session] = None,
    client: Optional[AlpacaClient] = None,
    llm: Optional[LLMProvider] = None
) -> Dict[str, Any]:
    """Executes the hourly derivatives overlay risk assessment and hedging.

    1. Scans held equity positions.
    2. Checks for existing open hedges to prevent duplicate over-hedging.
    3. Runs VWAP-gated risk evaluation.
    4. Selects and submits options hedge orders.
    5. Persists Hedge and DecisionLog audit entries.
    """
    client = client or get_alpaca_client()
    llm = llm or get_llm_provider()
    db_session = db or SessionLocal()
    should_close_db = db is None

    try:
        positions = client.get_positions()
        equity_positions = [p for p in positions if p.get("asset_class") != "us_option" and p.get("qty", 0) > 0]

        if not equity_positions:
            decision_log = DecisionLog(
                timestamp=datetime.now(timezone.utc),
                layer="overlay",
                input_summary={"held_equity_count": 0},
                reasoning="No equity positions currently held in portfolio to overlay.",
                action_taken="No hedging actions taken."
            )
            db_session.add(decision_log)
            db_session.commit()
            return {
                "status": "success",
                "layer": "derivatives_overlay",
                "hedges_created": [],
                "message": "No active equity positions to hedge."
            }

        # Check existing open hedges in DB
        open_hedges = db_session.query(Hedge).filter(Hedge.status == "open").all()
        hedged_tickers = {h.underlying_ticker for h in open_hedges}

        hedges_created = []
        evaluations = []

        for eq in equity_positions:
            sym = eq["symbol"]
            eval_res = evaluate_ticker_risk(sym, client, llm)
            evaluations.append(eval_res)

            current_price = float(eq.get("current_price", client.get_latest_price(sym)))
            vwap_price = float(
                calculate_vwap(client.get_bars(symbol=sym, timeframe_str="1Hour", limit=24) or [])
                if client.get_bars(symbol=sym, timeframe_str="1Hour", limit=24)
                else current_price
            )
            guard = evaluate_vwap_and_tp(eq, current_price, vwap_price)
            if guard.get("is_chasing"):
                logger.info(f"{sym} is chasing intraday VWAP; skipping hedge placement.")
                evaluations[-1]["vwap_guard"] = guard
                evaluations[-1]["rationale"] = f"VWAP chase guard triggered: {guard['notes']}"
                continue

            # If risk requires hedging and ticker does not already have an open hedge
            if eval_res["exposure_shape"] in ("downside_risk", "range_bound", "defined_downside", "high_volatility"):
                if sym in hedged_tickers:
                    logger.info(f"{sym} already has an active hedge; skipping duplicate.")
                    continue

                # Fetch option chain
                chain = client.get_option_contracts(underlying_symbol=sym)
                hedge_spec = select_hedge_structure(
                    exposure_shape=eval_res["exposure_shape"],
                    current_price=eval_res["current_price"],
                    option_contracts=chain,
                    underlying_symbol=sym,
                    stock_qty=float(eq.get("qty", 0)),
                )

                # Execute option order(s)
                if hedge_spec.get("legs"):
                    leg_guard = validate_option_overlay_legs(hedge_spec["legs"])
                    if not leg_guard["approved"]:
                        evaluations[-1]["rationale"] = leg_guard["reason"]
                        continue
                    order_results = client.place_multi_leg_option_order(hedge_spec["legs"])
                    if not _all_orders_filled(order_results):
                        failure_reason = "; ".join(str(order.get("error", order.get("status"))) for order in order_results)
                        db_session.add(DecisionLog(
                            timestamp=datetime.now(timezone.utc),
                            layer="overlay",
                            input_summary={"symbol": sym, "order_results": order_results},
                            reasoning="Broker did not confirm every protective-put leg.",
                            action_taken=f"FAILED_BROKER_REJECT: hedge for {sym} was not persisted. {failure_reason}",
                        ))
                        continue
                    
                    # Compute expiration date
                    exp_date_str = hedge_spec.get("expires_at", (datetime.now(timezone.utc) + timedelta(days=21)).strftime("%Y-%m-%d"))
                    try:
                        exp_dt = datetime.strptime(exp_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    except Exception:
                        exp_dt = datetime.now(timezone.utc) + timedelta(days=21)

                    # Persist Hedge in DB
                    new_hedge = Hedge(
                        underlying_ticker=sym,
                        structure_type=hedge_spec["structure_type"],
                        legs=hedge_spec["legs"],
                        status="open",
                        opened_at=datetime.now(timezone.utc),
                        expires_at=exp_dt,
                        notes=f"Triggered by {eval_res['exposure_shape']}: {eval_res['rationale']}"
                    )
                    db_session.add(new_hedge)
                    db_session.flush()

                    hedges_created.append({
                        "id": new_hedge.id,
                        "ticker": sym,
                        "structure": hedge_spec["structure_type"],
                        "legs": hedge_spec["legs"],
                        "rationale": hedge_spec["rationale"],
                        "order_results": order_results
                    })
                elif hedge_spec.get("rejection"):
                    evaluations[-1]["rationale"] = hedge_spec["rationale"]

        # Summary audit log
        if hedges_created:
            actions_text = "; ".join([
                f"Opened {h['structure']} overlay on {h['ticker']} ({len(h['legs'])} legs)"
                for h in hedges_created
            ])
            reasons_text = "\n".join([f"- {h['ticker']}: {h['rationale']}" for h in hedges_created])
        else:
            actions_text = f"Monitored {len(equity_positions)} equity positions. No new hedge overlays required."
            reasons_text = "All held positions within normal volatility and VWAP tolerance thresholds."

        decision_log = DecisionLog(
            timestamp=datetime.now(timezone.utc),
            layer="overlay",
            input_summary={
                "evaluated_positions": [e["symbol"] for e in evaluations],
                "active_hedges_before": list(hedged_tickers)
            },
            reasoning=reasons_text,
            action_taken=actions_text
        )
        db_session.add(decision_log)
        db_session.commit()

        return {
            "status": "success",
            "layer": "derivatives_overlay",
            "evaluations": evaluations,
            "hedges_created": hedges_created,
            "action_taken": actions_text
        }

    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error executing Derivatives Overlay layer: {e}")
        return {"status": "error", "layer": "derivatives_overlay", "error": str(e)}

    finally:
        if should_close_db:
            db_session.close()
