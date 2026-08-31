"""Expiration Watchdog Layer (Runs on Hourly Cadence).

Responsibilities:
1. Queries all open `Hedge` positions from the database.
2. Calculates Days-to-Expiration (DTE) for each hedge.
3. For any hedge within the configured threshold (e.g. <= 5 trading days),
   forces an explicit CLOSE or ROLL decision — strictly enforcing the rule that
   no options position rides unmanaged into its final expiration week.
4. Executes required closing or rolling orders against Alpaca.
5. Updates database hedge state and writes an audit entry to `DecisionLog`.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging
from sqlalchemy.orm import Session

from agent.config import settings
from agent.trading.alpaca_client import get_alpaca_client, AlpacaClient
from agent.trading.risk import select_hedge_structure
from agent.llm.provider import get_llm_provider, LLMProvider
from agent.data.db import SessionLocal
from agent.data.models import Hedge, DecisionLog

logger = logging.getLogger(__name__)


def calculate_days_to_expiry(expires_at: datetime) -> int:
    """Calculates integer days remaining until contract expiration."""
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    diff = (expires_at - now).total_seconds() / 86400.0
    return max(0, int(diff))


def run_expiration_watchdog_layer(
    db: Optional[Session] = None,
    client: Optional[AlpacaClient] = None,
    llm: Optional[LLMProvider] = None,
    threshold_days: Optional[int] = None
) -> Dict[str, Any]:
    """Scans open option hedges and enforces close or roll for near-expiry positions.

    Args:
        db: Optional database session.
        client: AlpacaClient instance.
        llm: LLMProvider instance.
        threshold_days: DTE threshold (default from settings: 5 days).

    Returns:
        Summary dict of watchdog execution and actions taken.
    """
    client = client or get_alpaca_client()
    llm = llm or get_llm_provider()
    db_session = db or SessionLocal()
    should_close_db = db is None
    threshold = threshold_days if threshold_days is not None else settings.EXPIRATION_THRESHOLD_DAYS

    try:
        now = datetime.now(timezone.utc)
        open_hedges = db_session.query(Hedge).filter(Hedge.status == "open").all()
        current_positions = client.get_positions()
        held_equities = {
            p["symbol"] for p in current_positions
            if p.get("asset_class") != "us_option" and p.get("qty", 0) > 0
        }

        actions_taken = []
        monitored_hedges = []

        for hedge in open_hedges:
            dte = calculate_days_to_expiry(hedge.expires_at)
            monitored_hedges.append({
                "id": hedge.id,
                "underlying": hedge.underlying_ticker,
                "structure": hedge.structure_type,
                "dte": dte,
                "expires_at": hedge.expires_at.isoformat()
            })

            # Check if within expiration threshold
            if dte <= threshold:
                underlying = hedge.underlying_ticker
                is_equity_held = underlying in held_equities

                logger.info(
                    f"Watchdog trigger: Hedge #{hedge.id} on {underlying} has {dte} DTE (<= {threshold} threshold). "
                    f"Equity held: {is_equity_held}."
                )

                # 1. Close existing near-expiry option legs
                close_results = []
                for leg in (hedge.legs or []):
                    sym = leg.get("symbol")
                    if sym:
                        res = client.close_position(sym)
                        close_results.append(res)

                # 2. Decide: ROLL or CLOSE
                if is_equity_held:
                    # Still holding stock -> Roll out to a fresh 21-30 DTE contract
                    chain = client.get_option_contracts(underlying_symbol=underlying)
                    cur_px = client.get_latest_price(underlying)
                    
                    new_hedge_spec = select_hedge_structure(
                        exposure_shape="downside_risk",
                        current_price=cur_px,
                        option_contracts=chain,
                        underlying_symbol=underlying,
                        target_dte_days=21
                    )

                    roll_order_results = []
                    if new_hedge_spec.get("legs"):
                        roll_order_results = client.place_multi_leg_option_order(new_hedge_spec["legs"])

                    # Update existing hedge as rolled
                    hedge.status = "rolled"
                    hedge.closed_at = now
                    hedge.notes = f"{hedge.notes or ''} | Rolled at {dte} DTE to avoid final-week theta/gamma risk."

                    # Create new rolled Hedge row
                    new_exp_str = new_hedge_spec.get("expires_at", (now + timedelta(days=21)).strftime("%Y-%m-%d"))
                    try:
                        new_exp_dt = datetime.strptime(new_exp_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    except Exception:
                        new_exp_dt = now + timedelta(days=21)

                    rolled_hedge = Hedge(
                        underlying_ticker=underlying,
                        structure_type=new_hedge_spec["structure_type"],
                        legs=new_hedge_spec["legs"],
                        status="open",
                        opened_at=now,
                        expires_at=new_exp_dt,
                        notes=f"Rolled from Hedge #{hedge.id} via Expiration Watchdog ({threshold} DTE rule)."
                    )
                    db_session.add(rolled_hedge)

                    actions_taken.append({
                        "hedge_id": hedge.id,
                        "ticker": underlying,
                        "action": "rolled",
                        "dte": dte,
                        "reason": f"Underlying {underlying} is still held in portfolio. Closed near-expiry legs and rolled to {new_exp_str} ({new_hedge_spec['structure_type']}).",
                        "new_legs": new_hedge_spec["legs"]
                    })

                else:
                    # Underlying no longer held -> Close position completely
                    hedge.status = "closed"
                    hedge.closed_at = now
                    hedge.notes = f"{hedge.notes or ''} | Closed at {dte} DTE (underlying no longer held)."

                    actions_taken.append({
                        "hedge_id": hedge.id,
                        "ticker": underlying,
                        "action": "closed",
                        "dte": dte,
                        "reason": f"Underlying {underlying} is no longer held in portfolio. Closed near-expiry overlay to harvest remaining value."
                    })

        # Persist audit entry in DecisionLog
        if actions_taken:
            action_desc = "; ".join([f"{a['action'].upper()} hedge on {a['ticker']} (DTE={a['dte']})" for a in actions_taken])
            reason_desc = "\n".join([f"- {a['ticker']}: {a['reason']}" for a in actions_taken])
        else:
            action_desc = f"Audited {len(open_hedges)} open hedge positions. All positions have > {threshold} DTE."
            reason_desc = "No near-expiry positions detected. Expiration buffer intact."

        decision_log = DecisionLog(
            timestamp=now,
            layer="watchdog",
            input_summary={
                "threshold_days": threshold,
                "monitored_hedges_count": len(monitored_hedges),
                "open_hedges": monitored_hedges
            },
            reasoning=reason_desc,
            action_taken=action_desc
        )
        db_session.add(decision_log)
        db_session.commit()

        return {
            "status": "success",
            "layer": "expiration_watchdog",
            "monitored_hedges": monitored_hedges,
            "actions_taken": actions_taken,
            "summary": action_desc
        }

    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error executing Expiration Watchdog layer: {e}")
        return {"status": "error", "layer": "expiration_watchdog", "error": str(e)}

    finally:
        if should_close_db:
            db_session.close()
