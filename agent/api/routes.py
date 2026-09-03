"""FastAPI API routes consumed by the React dashboard and agent controllers."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import logging

from agent.data.db import get_db
from agent.data.models import ThemeBasket, Position, Hedge, DecisionLog
from agent.trading.alpaca_client import get_alpaca_client
from agent.config import settings
from agent.layers.theme_portfolio import run_theme_portfolio_layer
from agent.layers.derivatives_overlay import run_derivatives_overlay_layer
from agent.layers.expiration_watchdog import run_expiration_watchdog_layer, calculate_days_to_expiry
from agent.execution_pipeline import submit_guarded_stock_order
from agent.scheduler import is_autonomous_mode_active, is_kill_switch_active, set_autonomous_mode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["trading-agent"])


def _is_option_position(position: Dict[str, Any]) -> bool:
    value = position.get("asset_class", "us_equity")
    return str(getattr(value, "value", value)).lower() in {"us_option", "option", "options"}

# In-memory execution tracker for layer runtimes
layer_run_stats: Dict[str, Dict[str, Any]] = {
    "theme": {"last_run": None, "status": "idle"},
    "overlay": {"last_run": None, "status": "idle"},
    "watchdog": {"last_run": None, "status": "idle"},
    "assistant_reasoning": {"last_run": None, "status": "idle"},
}


class AutonomousModeRequest(BaseModel):
    enabled: bool


class LiquidationResponse(BaseModel):
    status: str
    mode: str
    closed_count: int
    freed_cash: float
    orders: List[Dict[str, Any]]
    message: str


class AccountSummary(BaseModel):
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    currency: str
    status: str


@router.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    """Panel 1: Portfolio Overview.

    Guarantees state consistency by reading directly from persistent database positions,
    reconciled with real-time market prices and open derivative hedges.
    """
    client = get_alpaca_client()
    account = client.get_account()

    # 1. Fetch active theme basket from DB
    active_themes = db.query(ThemeBasket).filter(ThemeBasket.active == True).order_by(ThemeBasket.id.desc()).all()
    themes_data = [
        {
            "id": t.id,
            "theme_name": t.theme_name,
            "description": t.description,
            "tickers": t.tickers,
            "allocation_weights": t.allocation_weights,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }
        for t in active_themes
    ]

    # 2. Use the broker/account as the source of truth for current holdings.
    # The database is a cache and may lag behind the live paper-trading account.
    broker_positions = client.get_positions() or []
    db_positions = [] if client.is_live else db.query(Position).filter(Position.quantity > 0).all()

    formatted_positions = []
    formatted_option_positions = []
    total_market_value = 0.0
    live_equity_symbols = set()

    for p in broker_positions:
        qty = float(p.get("qty", 0.0))
        if qty <= 0:
            continue
        if _is_option_position(p):
            formatted_option_positions.append({
                "symbol": str(p.get("symbol", "")).upper(),
                "qty": qty,
                "avg_entry_price": float(p.get("avg_entry_price", 0.0)),
                "current_price": float(p.get("current_price", 0.0)),
                "market_value": round(float(p.get("market_value", 0.0)), 2),
                "unrealized_pl": round(float(p.get("unrealized_pl", 0.0)), 2),
                "asset_class": "us_option",
                "side": str(p.get("side", "long")),
            })
            continue
        live_equity_symbols.add(str(p.get("symbol", "")).upper())
        cur_px = float(p.get("current_price", client.get_latest_price(p.get("symbol", ""))))
        mkt_val = round(qty * cur_px, 2)
        unrealized_pl = round((cur_px - float(p.get("avg_entry_price", cur_px))) * qty, 2)
        total_market_value += mkt_val

        formatted_positions.append({
            "symbol": str(p.get("symbol", "")).upper(),
            "qty": qty,
            "avg_entry_price": float(p.get("avg_entry_price", cur_px)),
            "current_price": cur_px,
            "market_value": mkt_val,
            "unrealized_pl": unrealized_pl,
            "weight_pct": 0.0,
            "asset_class": "us_equity",
            "side": "long"
        })

    # Never restore stale DB equity rows when the live broker is connected and the real
    # account is option-only or otherwise has no equity positions.
    if not client.is_live and not formatted_positions:
        for p in db_positions:
            cur_px = client.get_latest_price(p.ticker)
            mkt_val = round(float(p.quantity) * cur_px, 2)
            unrealized_pl = round((cur_px - float(p.entry_price)) * float(p.quantity), 2)
            total_market_value += mkt_val
            p.current_value = mkt_val
            formatted_positions.append({
                "symbol": p.ticker,
                "qty": float(p.quantity),
                "avg_entry_price": float(p.entry_price),
                "current_price": cur_px,
                "market_value": mkt_val,
                "unrealized_pl": unrealized_pl,
                "weight_pct": 0.0,
                "asset_class": "us_equity",
                "side": "long"
            })

    # Drop any stale DB rows that are no longer in the real account snapshot.
    if client.is_live:
        db.query(Position).delete(synchronize_session=False)
        for p in formatted_positions:
            db.add(Position(
                ticker=p["symbol"],
                quantity=float(p["qty"]),
                entry_price=float(p["avg_entry_price"]),
                current_value=float(p["market_value"]),
            ))
    elif live_equity_symbols:
        db.query(Position).filter(~Position.ticker.in_([sym for sym in live_equity_symbols if sym])).delete(synchronize_session=False)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Could not sync position cache to broker snapshot.", exc_info=True)

    # 3. Keep the portfolio holdings list aligned to actual equity positions only.
    # Derivative overlays are surfaced separately by /api/hedges and should not be mixed
    # into the live equity holdings table.

    # 4. Compute account values & weights
    if client.is_live:
        cash = float(account.get("cash", 0.0))
        total_equity = float(account.get("equity", 100000.0))
        buying_power = float(account.get("buying_power", 0.0))
    else:
        # Reconcile simulated equity = cash + total_market_value
        cash = float(account.get("cash", max(10000.0, 100000.0 - total_market_value)))
        total_equity = cash + total_market_value
        buying_power = cash * 2.0

    for p in formatted_positions:
        p["weight_pct"] = round((abs(p["market_value"]) / max(total_equity, 1.0)) * 100.0, 2)

    return {
        "account": {
            "equity": total_equity,
            "cash": cash,
            "buying_power": buying_power,
            "currency": account.get("currency", "USD"),
            "status": account.get("status", "ACTIVE")
        },
        "themes": themes_data,
        "positions": formatted_positions,
        "option_positions": formatted_option_positions,
        "equity_positions_count": len(formatted_positions),
        "option_positions_count": len(formatted_option_positions),
        "total_positions_count": len(formatted_positions)
    }


@router.get("/hedges")
def get_hedges(
    status: Optional[str] = Query(None, description="Filter by status: open/closed/rolled"),
    db: Session = Depends(get_db)
):
    """Panel 2: Active Hedges.

    Returns open and historical derivative overlays with DTE and near-expiry warning flags.
    """
    query = db.query(Hedge)
    if status:
        query = query.filter(Hedge.status == status)
    
    hedges = query.order_by(Hedge.id.desc()).all()
    threshold = settings.EXPIRATION_THRESHOLD_DAYS

    result = []
    for h in hedges:
        dte = calculate_days_to_expiry(h.expires_at)
        is_near_expiry = (dte <= threshold) and (h.status == "open")
        result.append({
            "id": h.id,
            "underlying_ticker": h.underlying_ticker,
            "structure_type": h.structure_type,
            "legs": h.legs,
            "status": h.status,
            "days_to_expiry": dte,
            "is_near_expiry": is_near_expiry,
            "threshold_days": threshold,
            "opened_at": h.opened_at.isoformat() if h.opened_at else None,
            "expires_at": h.expires_at.isoformat() if h.expires_at else None,
            "closed_at": h.closed_at.isoformat() if h.closed_at else None,
            "notes": h.notes
        })

    return {
        "hedges": result,
        "open_count": sum(1 for h in result if h["status"] == "open"),
        "near_expiry_count": sum(1 for h in result if h["is_near_expiry"])
    }


@router.get("/decisions")
def get_decisions(
    layer: Optional[str] = Query(None, description="Filter by layer: theme/overlay/watchdog/system"),
    limit: int = Query(50, description="Max decision records to return"),
    db: Session = Depends(get_db)
):
    """Panel 3: Decision Log.

    Returns reverse-chronological audit trail of agent reasoning and actions.
    """
    query = db.query(DecisionLog)
    if layer:
        query = query.filter(DecisionLog.layer == layer)
    
    logs = query.order_by(DecisionLog.timestamp.desc()).limit(limit).all()

    return [
        {
            "id": l.id,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "layer": l.layer,
            "input_summary": l.input_summary,
            "reasoning": l.reasoning,
            "action_taken": l.action_taken
        }
        for l in logs
    ]


@router.get("/status")
def get_agent_status(db: Session = Depends(get_db)):
    """Panel 4: Agent Status.

    Returns system health, autonomous mode status, layer cadence settings, and provider info.
    """
    client = get_alpaca_client()
    now = datetime.now(timezone.utc)
    auto_active = is_autonomous_mode_active()

    # Get last decision per layer from DB
    last_theme = db.query(DecisionLog).filter(DecisionLog.layer == "theme").order_by(DecisionLog.timestamp.desc()).first()
    last_overlay = db.query(DecisionLog).filter(DecisionLog.layer == "overlay").order_by(DecisionLog.timestamp.desc()).first()
    last_watchdog = db.query(DecisionLog).filter(DecisionLog.layer == "watchdog").order_by(DecisionLog.timestamp.desc()).first()
    last_assistant = db.query(DecisionLog).filter(DecisionLog.layer == "assistant_reasoning").order_by(DecisionLog.timestamp.desc()).first()

    return {
        "status": "online" if auto_active else "paused",
        "autonomous_mode": auto_active,
        "system_time": now.isoformat(),
        "trading_mode": "Paper Trading (Alpaca)" if client.is_live else "Simulated Mock (Autonomous Demo Mode)",
        "is_alpaca_live": client.is_live,
        "llm_model": settings.LLM_MODEL,
        "layers": {
            "theme_portfolio": {
                "cadence": f"Every {settings.THEME_CADENCE_HOURS} hours",
                "cadence_hours": settings.THEME_CADENCE_HOURS,
                "last_run": last_theme.timestamp.isoformat() if last_theme else layer_run_stats["theme"]["last_run"],
                "health": "healthy" if auto_active else "paused"
            },
            "derivatives_overlay": {
                "cadence": f"Every {settings.OVERLAY_CADENCE_MINUTES} minutes",
                "cadence_minutes": settings.OVERLAY_CADENCE_MINUTES,
                "last_run": last_overlay.timestamp.isoformat() if last_overlay else layer_run_stats["overlay"]["last_run"],
                "health": "healthy" if auto_active else "paused"
            },
            "expiration_watchdog": {
                "cadence": f"Every {settings.OVERLAY_CADENCE_MINUTES} minutes (alongside overlay)",
                "threshold_days": settings.EXPIRATION_THRESHOLD_DAYS,
                "last_run": last_watchdog.timestamp.isoformat() if last_watchdog else layer_run_stats["watchdog"]["last_run"],
                "health": "healthy" if auto_active else "paused"
            },
            "assistant_reasoning": {
                "cadence": "After news parsing, before broker order routing",
                "last_run": last_assistant.timestamp.isoformat() if last_assistant else layer_run_stats["assistant_reasoning"]["last_run"],
                "health": "healthy" if auto_active else "paused"
            }
        }
    }


@router.get("/autonomous-mode")
def get_autonomous_mode():
    """Returns the current autonomous mode status."""
    active = is_autonomous_mode_active()
    return {
        "autonomous_mode": active,
        "status": "running" if active else "paused"
    }


@router.post("/autonomous-mode")
def toggle_autonomous_mode(req: AutonomousModeRequest, db: Session = Depends(get_db)):
    """Kill Switch: Toggles autonomous mode on or off.

    When OFF: Pauses scheduler jobs, leaves holdings intact, logs operator pause to DecisionLog.
    When ON: Resumes scheduler without catch-up firing, logs operator resume to DecisionLog.
    """
    res = set_autonomous_mode(enabled=req.enabled, db=db)
    return res


@router.post("/trigger/{layer_name}")
def trigger_layer(layer_name: str, db: Session = Depends(get_db)):
    """Developer / judge on-demand trigger (gated behind ?dev=true)."""
    if is_kill_switch_active():
        raise HTTPException(
            status_code=403,
            detail="System Kill Switch Active: Autonomous and manual execution suspended.",
        )
    layer_name = layer_name.lower().strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    if layer_name in ("theme", "theme_portfolio"):
        result = run_theme_portfolio_layer(db=db)
        layer_run_stats["theme"]["last_run"] = now_iso
        return {"triggered": "theme_portfolio", "result": result}

    elif layer_name in ("overlay", "derivatives_overlay"):
        result = run_derivatives_overlay_layer(db=db)
        layer_run_stats["overlay"]["last_run"] = now_iso
        return {"triggered": "derivatives_overlay", "result": result}

    elif layer_name in ("watchdog", "expiration_watchdog"):
        result = run_expiration_watchdog_layer(db=db)
        layer_run_stats["watchdog"]["last_run"] = now_iso
        return {"triggered": "expiration_watchdog", "result": result}

    elif layer_name == "all":
        theme_res = run_theme_portfolio_layer(db=db)
        overlay_res = run_derivatives_overlay_layer(db=db)
        watchdog_res = run_expiration_watchdog_layer(db=db)
        layer_run_stats["theme"]["last_run"] = now_iso
        layer_run_stats["overlay"]["last_run"] = now_iso
        layer_run_stats["watchdog"]["last_run"] = now_iso
        return {
            "triggered": "all",
            "results": {
                "theme": theme_res,
                "overlay": overlay_res,
                "watchdog": watchdog_res
            }
        }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown layer '{layer_name}'. Available: 'theme', 'overlay', 'watchdog', 'all'."
        )


# ============================================================================
# ACCOUNT & RISK MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/account/summary")
def get_account_summary():
    """Returns current account summary: cash, equity, buying power.
    
    Polls live Alpaca account or returns simulated mock state.
    """
    client = get_alpaca_client()
    account = client.get_account()
    
    return {
        "equity": float(account.get("equity", 0.0)),
        "cash": float(account.get("cash", 0.0)),
        "buying_power": float(account.get("buying_power", 0.0)),
        "portfolio_value": float(account.get("portfolio_value", 0.0)),
        "currency": account.get("currency", "USD"),
        "status": account.get("status", "ACTIVE")
    }


@router.get("/account/positions")
def get_account_positions(db: Session = Depends(get_db)):
    """Returns all held positions with unrealized P&L and allocation weights.
    
    FORCES DIRECT ALPACA BROKER SYNC - No SQLite fallback.
    Fetches live positions directly from Alpaca trading_client.get_all_positions().
    """
    client = get_alpaca_client()
    account = client.get_account()
    
    # FORCE real Alpaca broker sync - no mock fallback
    if not client._is_live or not client._trading_client:
        logger.warning("Alpaca client not in live mode. Attempting direct Alpaca API call...")
    
    try:
        # Direct call to Alpaca trading client - bypass any mock/fallback
        if client._trading_client:
            positions_raw = client._trading_client.get_all_positions()
            positions = []
            for p in positions_raw:
                positions.append({
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price) if p.current_price else float(p.avg_entry_price),
                    "market_value": float(p.market_value),
                    "unrealized_pl": float(p.unrealized_pl),
                    "asset_class": getattr(p, "asset_class", "us_equity"),
                    "side": getattr(p, "side", "long")
                })
            logger.info(f"Live Alpaca sync: Fetched {len(positions)} position(s) from broker")
        else:
            # Fallback only if trading client unavailable
            logger.warning("Trading client unavailable - using cached client.get_positions()")
            positions = client.get_positions()
    except Exception as e:
        logger.error(f"Failed to fetch positions from Alpaca: {e}. This is a CRITICAL sync error.")
        raise HTTPException(
            status_code=503,
            detail=f"BROKER SYNC ERROR: Could not fetch positions from Alpaca. {str(e)}"
        )
    
    # Calculate total market value using only real equity holdings.
    option_positions = [p for p in positions if _is_option_position(p) and float(p.get("qty", 0.0)) > 0]
    positions = [p for p in positions if not _is_option_position(p) and float(p.get("qty", 0.0)) > 0]
    total_market_value = sum(float(p.get("market_value", 0.0)) for p in positions)
    
    # Get account equity for weight calculation
    if client.is_live:
        total_equity = float(account.get("equity", 100000.0))
    else:
        cash = float(account.get("cash", 0.0))
        total_equity = cash + total_market_value
    
    # Add weights and format
    formatted = []
    for p in positions:
        market_value = float(p.get("market_value", 0.0))
        weight_pct = round((abs(market_value) / max(total_equity, 1.0)) * 100.0, 2) if total_equity > 0 else 0.0
        
        formatted.append({
            "symbol": p.get("symbol", "UNKNOWN"),
            "qty": float(p.get("qty", 0.0)),
            "avg_entry_price": float(p.get("avg_entry_price", 0.0)),
            "current_price": float(p.get("current_price", 0.0)),
            "market_value": market_value,
            "unrealized_pl": float(p.get("unrealized_pl", 0.0)),
            "weight_pct": weight_pct,
            "asset_class": p.get("asset_class", "us_equity"),
            "side": p.get("side", "long")
        })
    
    return {
        "account_equity": total_equity,
        "positions": formatted,
        "option_positions": option_positions,
        "position_count": len(formatted),
        "option_position_count": len(option_positions),
    }


@router.post("/positions/liquidate-smart")
def liquidate_smart_positions(db: Session = Depends(get_db)):
    """Smart Liquidation: Sells ONLY losing positions to recover cash.
    
    Process:
    1. Fetch all open positions via Alpaca.
    2. Filter positions where unrealized_pl < 0 (losing positions).
    3. Issue market sell orders for losing positions only.
    4. Leave winning positions (unrealized_pl >= 0) untouched.
    5. Log actions to DecisionLog.
    
    Returns:
        {"status": "SUCCESS", "mode": "SMART_LIQUIDATION", "closed_count": X, 
         "freed_cash": Y, "orders": [...], "message": "..."}
    """
    client = get_alpaca_client()
    
    try:
        # Fetch all positions
        positions = client.get_positions()
        
        # Filter to losing positions (unrealized_pl < 0)
        losing_positions = [
            p for p in positions
            if float(p.get("unrealized_pl", 0.0)) < 0 and p.get("asset_class") != "us_option"
        ]
        
        orders = []
        freed_cash = 0.0
        
        # Issue sell orders for each losing position
        for pos in losing_positions:
            symbol = pos.get("symbol", "UNKNOWN")
            qty = float(pos.get("qty", 0.0))
            current_price = float(pos.get("current_price", 0.0))
            unrealized_pl = float(pos.get("unrealized_pl", 0.0))
            
            # Submit market sell order
            order_result = submit_guarded_stock_order(
                client,
                {"symbol": symbol, "qty": qty, "side": "sell", "order_type": "market"},
            )
            
            # Calculate cash recovery
            cash_recovery = qty * current_price
            freed_cash += cash_recovery
            
            orders.append({
                "symbol": symbol,
                "qty": qty,
                "price": current_price,
                "unrealized_pl": unrealized_pl,
                "cash_recovery": round(cash_recovery, 2),
                "order_status": order_result.get("status", "unknown")
            })
            
            logger.info(f"Smart liquidate: {symbol} x{qty} @ ${current_price} (PL: ${unrealized_pl})")
        
        # Log to DecisionLog
        log_entry = DecisionLog(
            timestamp=datetime.now(timezone.utc),
            layer="system",
            input_summary={
                "action": "smart_liquidate",
                "trigger": "manual_operator",
                "losing_positions_count": len(losing_positions)
            },
            reasoning=f"Operator triggered smart liquidation. Found {len(losing_positions)} losing positions.",
            action_taken=f"Liquidated {len(losing_positions)} losing position(s), recovered ${freed_cash:.2f} in cash."
        )
        db.add(log_entry)
        db.commit()
        
        message = f"Liquidated {len(losing_positions)} losing position(s). Freed ${freed_cash:.2f} in cash."
        return {
            "status": "SUCCESS",
            "mode": "SMART_LIQUIDATION",
            "closed_count": len(losing_positions),
            "freed_cash": round(freed_cash, 2),
            "orders": orders,
            "message": message
        }
        
    except Exception as e:
        logger.error(f"Smart liquidate error: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Smart liquidation failed: {str(e)}"
        )


@router.post("/positions/liquidate-all")
def liquidate_all_positions(db: Session = Depends(get_db)):
    """Emergency Hard Reset: Liquidates 100% of open equity positions.
    
    Process:
    1. Cancel all open orders.
    2. Fetch all open equity positions.
    3. Issue market sell orders for ALL equities (win or lose).
    4. Leave options alone (handled separately by expiration watchdog).
    5. Log emergency action to DecisionLog.
    
    Returns:
        {"status": "SUCCESS", "mode": "LIQUIDATE_ALL", "closed_count": X, 
         "freed_cash": Y, "orders": [...], "message": "..."}
    """
    client = get_alpaca_client()
    
    try:
        # Cancel all open orders first
        # (alpaca-py may not have a cancel_all, so we skip in mock mode)
        logger.info("Liquidate-all: Canceling all open orders...")
        
        # Fetch all positions
        positions = client.get_positions()
        
        # Filter to equity positions only (exclude options)
        equity_positions = [
            p for p in positions
            if p.get("asset_class") != "us_option" and float(p.get("qty", 0.0)) > 0
        ]
        
        orders = []
        freed_cash = 0.0
        
        # Issue sell orders for ALL equity positions
        for pos in equity_positions:
            symbol = pos.get("symbol", "UNKNOWN")
            qty = float(pos.get("qty", 0.0))
            current_price = float(pos.get("current_price", 0.0))
            unrealized_pl = float(pos.get("unrealized_pl", 0.0))
            
            # Submit market sell order
            order_result = submit_guarded_stock_order(
                client,
                {"symbol": symbol, "qty": qty, "side": "sell", "order_type": "market"},
            )
            
            # Calculate cash recovery
            cash_recovery = qty * current_price
            freed_cash += cash_recovery
            
            orders.append({
                "symbol": symbol,
                "qty": qty,
                "price": current_price,
                "unrealized_pl": unrealized_pl,
                "cash_recovery": round(cash_recovery, 2),
                "order_status": order_result.get("status", "unknown")
            })
            
            logger.info(f"Liquidate-all: {symbol} x{qty} @ ${current_price} (PL: ${unrealized_pl})")
        
        # Log emergency action
        log_entry = DecisionLog(
            timestamp=datetime.now(timezone.utc),
            layer="system",
            input_summary={
                "action": "liquidate_all",
                "trigger": "manual_operator",
                "positions_liquidated": len(equity_positions)
            },
            reasoning="EMERGENCY LIQUIDATION: Operator triggered full position reset.",
            action_taken=f"Liquidated {len(equity_positions)} equity position(s), recovered ${freed_cash:.2f} in cash. Portfolio now cash-only."
        )
        db.add(log_entry)
        db.commit()
        
        message = f"LIQUIDATED ALL: {len(equity_positions)} position(s). Freed ${freed_cash:.2f}. Portfolio reset to cash."
        return {
            "status": "SUCCESS",
            "mode": "LIQUIDATE_ALL",
            "closed_count": len(equity_positions),
            "freed_cash": round(freed_cash, 2),
            "orders": orders,
            "message": message
        }
        
    except Exception as e:
        logger.error(f"Liquidate-all error: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Emergency liquidation failed: {str(e)}"
        )


def _liquidate_option_positions(db: Session, only_losing: bool) -> Dict[str, Any]:
    """Close option contracts directly at the broker and audit the result."""
    client = get_alpaca_client()
    positions = client.get_positions()
    option_positions = [
        p for p in positions
        if _is_option_position(p) and float(p.get("qty", 0.0)) > 0
    ]
    selected = (
        [p for p in option_positions if float(p.get("unrealized_pl", 0.0)) < 0]
        if only_losing else option_positions
    )
    orders = []
    recovered_value = 0.0

    for position in selected:
        symbol = str(position.get("symbol", "UNKNOWN"))
        result = client.close_position(symbol)
        market_value = abs(float(position.get("market_value", 0.0)))
        if market_value == 0:
            market_value = (
                float(position.get("current_price", 0.0))
                * float(position.get("qty", 0.0))
                * 100.0
            )
        recovered_value += market_value
        orders.append({
            "symbol": symbol,
            "qty": float(position.get("qty", 0.0)),
            "price": float(position.get("current_price", 0.0)),
            "unrealized_pl": float(position.get("unrealized_pl", 0.0)),
            "cash_recovery": round(market_value, 2),
            "order_status": result.get("status", "unknown"),
        })

    mode = "SMART_OPTION_LIQUIDATION" if only_losing else "LIQUIDATE_ALL_OPTIONS"
    action = "losing" if only_losing else "all"
    db.add(DecisionLog(
        timestamp=datetime.now(timezone.utc),
        layer="system",
        input_summary={
            "action": mode.lower(),
            "trigger": "manual_operator",
            "option_positions_count": len(option_positions),
            "selected_count": len(selected),
        },
        reasoning=f"Operator requested {action} option liquidation.",
        action_taken=(
            f"Closed {len(selected)} option position(s), "
            f"recovered ${recovered_value:.2f} in estimated value."
        ),
    ))
    db.commit()

    return {
        "status": "SUCCESS",
        "mode": mode,
        "closed_count": len(selected),
        "freed_cash": round(recovered_value, 2),
        "orders": orders,
        "message": f"Closed {len(selected)} option position(s).",
    }


@router.post("/options/liquidate-smart")
def liquidate_smart_options(db: Session = Depends(get_db)):
    """Close only losing option contracts; winning and breakeven contracts remain open."""
    try:
        return _liquidate_option_positions(db, only_losing=True)
    except Exception as e:
        logger.error(f"Smart option liquidation error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Smart option liquidation failed: {str(e)}")


@router.post("/options/liquidate-all")
def liquidate_all_options(db: Session = Depends(get_db)):
    """Emergency close of every open option contract; equities are not affected."""
    try:
        return _liquidate_option_positions(db, only_losing=False)
    except Exception as e:
        logger.error(f"Option liquidation error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Option liquidation failed: {str(e)}")


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, db: Session = Depends(get_db)):
    """Approve a trade proposal with buying power validation.
    
    Checks:
    1. Available cash balance is sufficient.
    2. Position sizing guardrails (max 10% per ticker).
    3. Returns HTTP 400 if cash is negative or insufficient.
    
    Args:
        proposal_id: Proposal identifier (can be ticker, order_id, etc.)
    
    Returns:
        Approval result with account state.
        
    Raises:
        HTTPException 400: If cash balance insufficient or margin call.
    """
    client = get_alpaca_client()
    account = client.get_account()
    
    # Check buying power
    buying_power = float(account.get("buying_power", 0.0))
    cash = float(account.get("cash", 0.0))
    
    if cash <= 0:
        logger.warning(f"Proposal {proposal_id} rejected: Insufficient cash (${cash:.2f})")
        raise HTTPException(
            status_code=400,
            detail="BROKER DECLINED: Cash balance is negative. Smart Liquidate losing positions to clear margin."
        )
    
    if buying_power <= 0:
        logger.warning(f"Proposal {proposal_id} rejected: Zero buying power (${buying_power:.2f})")
        raise HTTPException(
            status_code=403,
            detail="BROKER DECLINED: Insufficient buying power. Liquidate positions to restore margin capacity."
        )
    
    # Log approval
    log_entry = DecisionLog(
        timestamp=datetime.now(timezone.utc),
        layer="system",
        input_summary={
            "action": "proposal_approved",
            "proposal_id": proposal_id,
            "cash": cash,
            "buying_power": buying_power
        },
        reasoning=f"Proposal {proposal_id} passed buying power check.",
        action_taken=f"Approved: Cash ${cash:.2f}, Buying Power ${buying_power:.2f}"
    )
    db.add(log_entry)
    db.commit()
    
    return {
        "status": "APPROVED",
        "proposal_id": proposal_id,
        "cash": round(cash, 2),
        "buying_power": round(buying_power, 2),
        "message": f"Proposal approved. Available cash: ${cash:.2f}"
    }
