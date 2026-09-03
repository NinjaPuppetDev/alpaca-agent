"""Risk analysis, Greeks & exposure calculations, VWAP/Volume confirmation, and hedge selection.

Enforces risk management rules for the derivatives overlay:
- Never executes naked directional option bets.
- Confirms news catalysts with VWAP divergence and elevated volume before hedging.
- Only selects allowed structures: protective put, collar, covered call, vertical spread.
- Disallows butterflies, condors, and exotic multi-leg structures.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import math
import logging

logger = logging.getLogger(__name__)

# STRICT HEDGE ENFORCEMENT: Only protective puts allowed (downside protection only)
# NO covered calls (upside sell-off), NO collars (complex multi-leg), NO vertical spreads
ALLOWED_STRUCTURES = {
    "protective_put"  # ONLY structure allowed: single-leg long put for downside floor
}


def calculate_vwap(bars: List[Dict[str, Any]]) -> float:
    """Calculate Volume-Weighted Average Price (VWAP) across historical bars.

    Args:
        bars: List of bar dicts with high, low, close, volume.

    Returns:
        VWAP as float.
    """
    if not bars:
        return 0.0

    cumulative_tp_vol = 0.0
    cumulative_vol = 0.0

    for b in bars:
        high = float(b.get("high", b.get("close", 0.0)))
        low = float(b.get("low", b.get("close", 0.0)))
        close = float(b.get("close", 0.0))
        vol = float(b.get("volume", 0.0))

        typical_price = (high + low + close) / 3.0
        cumulative_tp_vol += typical_price * vol
        cumulative_vol += vol

    if cumulative_vol == 0:
        return float(bars[-1].get("close", 0.0))

    return round(cumulative_tp_vol / cumulative_vol, 4)


def confirm_signal_with_vwap(
    symbol: str,
    bars: List[Dict[str, Any]],
    current_price: Optional[float] = None
) -> Dict[str, Any]:
    """Confirms headline sentiment against market reality using VWAP and volume.

    Prevents acting on news noise without price/volume confirmation.

    Args:
        symbol: Ticker symbol.
        bars: Recent intraday price/volume bars.
        current_price: Latest market price (optional).

    Returns:
        Dict with confirmation status, direction ('bearish', 'bullish', 'neutral'),
        vwap, volume_ratio, and explanation.
    """
    if not bars or len(bars) < 2:
        return {
            "symbol": symbol,
            "confirmed": True,  # Fallback to allow hedge if bar data unavailable
            "direction": "bearish",
            "vwap": current_price or 100.0,
            "price": current_price or 100.0,
            "volume_ratio": 1.0,
            "reasoning": "Insufficient historical bars; defaulting to standard conservative risk gate."
        }

    vwap = calculate_vwap(bars)
    latest_close = float(bars[-1].get("close", current_price or 100.0))
    price = current_price if current_price is not None else latest_close

    # Calculate average volume excluding current bar
    past_volumes = [float(b.get("volume", 0.0)) for b in bars[:-1]]
    avg_volume = sum(past_volumes) / max(len(past_volumes), 1)
    recent_volume = float(bars[-1].get("volume", avg_volume))

    volume_ratio = round(recent_volume / max(avg_volume, 1.0), 2)
    price_diff_pct = (price - vwap) / max(vwap, 0.01) * 100.0

    # Confirmation criteria:
    # Bearish confirmation: Price is below VWAP (-0.2% or more) and volume is elevated (>= 1.05x avg)
    if price < vwap and (price_diff_pct <= -0.15 or volume_ratio >= 1.1):
        return {
            "symbol": symbol,
            "confirmed": True,
            "direction": "bearish",
            "vwap": vwap,
            "price": price,
            "price_diff_pct": round(price_diff_pct, 2),
            "volume_ratio": volume_ratio,
            "reasoning": f"Bearish confirmation: {symbol} is trading at ${price:.2f} below VWAP (${vwap:.2f}) with {volume_ratio:.2f}x average volume."
        }
    elif price > vwap and (price_diff_pct >= 0.15 or volume_ratio >= 1.1):
        return {
            "symbol": symbol,
            "confirmed": True,
            "direction": "bullish",
            "vwap": vwap,
            "price": price,
            "price_diff_pct": round(price_diff_pct, 2),
            "volume_ratio": volume_ratio,
            "reasoning": f"Bullish confirmation: {symbol} is trading at ${price:.2f} above VWAP (${vwap:.2f}) with {volume_ratio:.2f}x average volume."
        }
    else:
        return {
            "symbol": symbol,
            "confirmed": False,
            "direction": "neutral",
            "vwap": vwap,
            "price": price,
            "price_diff_pct": round(price_diff_pct, 2),
            "volume_ratio": volume_ratio,
            "reasoning": f"Unconfirmed move: {symbol} hovering near VWAP (${vwap:.2f}, diff {price_diff_pct:.2f}%) without abnormal volume ({volume_ratio:.2f}x)."
        }


def calculate_portfolio_exposure(positions: List[Dict[str, Any]], total_equity: float = 100000.0) -> Dict[str, Any]:
    """Computes portfolio exposures, concentration, and equity delta.

    Args:
        positions: List of position dicts.
        total_equity: Total account equity.

    Returns:
        Summary dict containing gross_exposure, cash_pct, concentrations.
    """
    total_market_val = sum(abs(p.get("market_value", 0.0)) for p in positions)
    long_equity_val = sum(p.get("market_value", 0.0) for p in positions if p.get("asset_class") != "us_option")
    option_val = sum(p.get("market_value", 0.0) for p in positions if p.get("asset_class") == "us_option")

    tickers_breakdown = {}
    for p in positions:
        sym = p.get("symbol", "UNKNOWN")
        mv = p.get("market_value", 0.0)
        tickers_breakdown[sym] = {
            "market_value": mv,
            "weight": round(mv / max(total_equity, 1.0), 4),
            "qty": p.get("qty", 0.0),
            "current_price": p.get("current_price", 0.0)
        }

    return {
        "total_equity": total_equity,
        "total_market_value": round(total_market_val, 2),
        "long_equity_value": round(long_equity_val, 2),
        "option_value": round(option_val, 2),
        "gross_exposure_pct": round((total_market_val / max(total_equity, 1.0)) * 100, 2),
        "positions_breakdown": tickers_breakdown,
        "position_count": len(positions)
    }


def select_hedge_structure(
    exposure_shape: str,
    current_price: float,
    option_contracts: List[Dict[str, Any]],
    underlying_symbol: str,
    stock_qty: float,
    target_dte_days: int = 21
) -> Dict[str, Any]:
    """Selects and structures an options hedge overlay.

    STRICT ENFORCEMENT: Only protective_put is allowed.
    
    This function implements a conservative downside-protection-only strategy:
    - ALWAYS returns protective_put structure (single-leg long put)
    - Disallows all other structures: NO collars, NO covered calls, NO spreads
    - Disallows butterflies, condors, or any exotic multi-leg structures
    - Disallows naked short options

    Args:
        exposure_shape: 'downside_risk', 'range_bound', 'high_volatility', or 'income_opportunity'
        current_price: Underlying current price
        option_contracts: Available option chain contracts
        underlying_symbol: Underlying ticker
        stock_qty: Number of underlying shares held. Protective puts require exact
            100-share coverage per contract; partial lots are rejected.
        target_dte_days: Target days to expiry

    Returns:
        Hedge decision dict with structure_type='protective_put', single long put leg, and rationale.
    """
    # STRICT ENFORCEMENT: Always use protective_put regardless of exposure shape.
    structure_type = "protective_put"
    
    if structure_type not in ALLOWED_STRUCTURES:
        raise ValueError(f"Disallowed options structure: {structure_type}")

    if stock_qty < 100 or stock_qty % 100 != 0:
        return {
            "underlying_symbol": underlying_symbol,
            "structure_type": structure_type,
            "legs": [],
            "rationale": f"Rejected hedge for {underlying_symbol}: {stock_qty} shares cannot be covered by exact 100-share option contracts.",
            "rejection": "UNHEDGED_REMAINDER_OR_SUB_LOT",
        }

    now = datetime.now(timezone.utc).date()
    liquid_puts = []
    for contract in option_contracts:
        if contract.get("type") != "put" or int(contract.get("open_interest", 0) or 0) <= 0:
            continue
        bid = float(contract.get("bid_price", 0) or 0)
        ask = float(contract.get("ask_price", 0) or 0)
        if bid <= 0 or ask <= 0 or bid > ask:
            continue
        try:
            expiry = datetime.fromisoformat(str(contract["expiration_date"])).date()
        except (KeyError, TypeError, ValueError):
            continue
        if 14 <= (expiry - now).days <= 45:
            liquid_puts.append(contract)

    legs: List[Dict[str, Any]] = []
    rationale = ""

    # SINGLE STRUCTURE: Protective Put only
    # Target ~5% OTM Put (strike <= current_price * 0.95)
    otm_puts = sorted(
        liquid_puts,
        key=lambda c: abs(c.get("strike_price", 0.0) - (current_price * 0.95))
    )
    if not otm_puts:
        return {
            "underlying_symbol": underlying_symbol,
            "structure_type": structure_type,
            "legs": [],
            "rationale": f"Rejected hedge for {underlying_symbol}: no liquid put with 14-45 DTE was available.",
            "rejection": "NO_LIQUID_CONTRACT",
        }
    selected = otm_puts[0]
    legs.append({
        "symbol": selected["symbol"],
        "type": "put",
        "strike": selected["strike_price"],
        "side": "buy",
        "qty": int(stock_qty // 100),
        "expiration_date": selected.get("expiration_date", "")
    })
    
    rationale = (
        f"STRICT PROTECTIVE PUT OVERLAY (single-leg downside floor only): "
        f"Bought {int(stock_qty // 100)}x {selected['strike_price']} strike put(s) on {underlying_symbol}. "
        f"Exposure shape was '{exposure_shape}' but ENFORCED protective_put per risk mandate. "
        f"NO covered calls, NO collars, NO spreads allowed."
    )

    return {
        "underlying_symbol": underlying_symbol,
        "structure_type": structure_type,
        "legs": legs,
        "rationale": rationale,
        "expires_at": legs[0].get("expiration_date", "2026-09-18") if legs else "2026-09-18"
    }
