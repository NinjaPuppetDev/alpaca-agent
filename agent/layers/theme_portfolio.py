"""Theme + Portfolio Layer (Daily Cadence).

Responsibilities:
1. Pull recent market news via `AlpacaClient.get_news`.
2. Groq LLM call: cluster news headlines into 1-2 macro/thematic portfolios.
3. Map themes to target ticker baskets and equal-weight allocations.
4. Diff target allocations against currently held equity positions.
5. Submit rebalancing orders to Alpaca.
6. Persist ThemeBasket, updated Position records, and audit DecisionLog entries.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import json
import logging
from sqlalchemy.orm import Session

from agent.trading.alpaca_client import get_alpaca_client, AlpacaClient
from agent.llm.provider import get_llm_provider, LLMProvider
from agent.data.db import SessionLocal
from agent.data.models import ThemeBasket, Position, DecisionLog

logger = logging.getLogger(__name__)

# Sector/Thematic Fallback Mapping dictionary
THEME_TICKER_MAP = {
    "semiconductors": ["NVDA", "AMD", "TSM", "AVGO"],
    "ai hardware": ["NVDA", "AMD", "AVGO", "MSFT"],
    "clean energy": ["FCX", "CCJ", "ALB", "NEE"],
    "critical minerals": ["FCX", "CCJ", "VALE", "ALB"],
    "mining": ["FCX", "BHP", "VALE", "RIO"],
    "cloud & software": ["MSFT", "GOOGL", "AMZN", "AAPL"],
    "cybersecurity": ["CRWD", "PANW", "FTNT", "NET"]
}


def fetch_news_for_theming(client: AlpacaClient, limit: int = 15) -> List[Dict[str, Any]]:
    """Fetches broad market headlines for thematic clustering."""
    return client.get_news(symbols=None, limit=limit)


def cluster_news_into_themes(news_articles: List[Dict[str, Any]], llm: LLMProvider) -> Dict[str, Any]:
    """Uses LLM to analyze news headlines and extract 1-2 coherent investment themes.

    Args:
        news_articles: List of recent news articles.
        llm: Configured LLMProvider instance.

    Returns:
        Structured dict with themes (name, description, tickers) and reasoning.
    """
    headlines_text = "\n".join([
        f"- {art.get('headline')} (Symbols: {', '.join(art.get('symbols', []))}) Summary: {art.get('summary', '')[:140]}"
        for art in news_articles[:10]
    ])

    system_prompt = (
        "You are an expert thematic portfolio manager. Analyze market news to identify emerging, "
        "high-conviction investment themes (e.g. 'Semiconductor CapEx Acceleration', 'Critical Minerals Grid Demand'). "
        "Extract 1 or 2 distinct themes and assign 3 to 4 liquid US equities to each theme. "
        "Respond ONLY with a JSON object format:\n"
        "{\n"
        '  "themes": [\n'
        '    {"name": "Theme Name", "description": "Brief catalyst summary", "tickers": ["SYM1", "SYM2", "SYM3"]}\n'
        "  ],\n"
        '  "reasoning": "Audit rationale explaining why these themes were selected from the news catalysts."\n'
        "}"
    )

    user_prompt = f"Recent Market News Feed:\n{headlines_text}\n\nIdentify the top 1-2 themes and their corresponding ticker baskets."

    try:
        result = llm.complete_json(prompt=user_prompt, system_prompt=system_prompt)
        if "themes" in result and isinstance(result["themes"], list) and len(result["themes"]) > 0:
            return result
    except Exception as e:
        logger.error(f"Error in LLM theme clustering: {e}")

    # Deterministic fallback if LLM extraction fails or is empty
    return {
        "themes": [
            {
                "name": "Semiconductors & AI Infrastructure",
                "description": "Accelerating data center infrastructure buildout and enterprise AI silicon demand.",
                "tickers": ["NVDA", "AMD", "TSM", "AVGO"]
            }
        ],
        "reasoning": "Fallback clustering based on active technology and hardware infrastructure headlines."
    }


VALID_EQUITY_UNIVERSE = {
    "NVDA", "AMD", "TSM", "AVGO", "FCX", "CCJ", "ALB", "NEE", "AAPL", "MSFT", "AMZN", "GOOGL",
    "CRWD", "PANW", "FTNT", "NET", "VALE", "BHP", "RIO", "META", "INTC", "QCOM", "TXN", "ASML",
    "MU", "LRCX", "KLAC", "AMAT", "MRVL", "ARM"
}


def map_themes_to_allocation(themes: List[Dict[str, Any]], target_capital: float) -> Dict[str, Dict[str, Any]]:
    """Calculates equal-weight capital allocation across selected theme tickers.

    Args:
        themes: List of theme dicts with 'tickers'.
        target_capital: Total capital allocated to thematic equity (e.g., 80-90% of equity).

    Returns:
        Dict of ticker -> {'target_weight': float, 'target_dollars': float, 'theme_name': str}
    """
    all_tickers = []
    ticker_theme_map = {}
    for t in themes:
        theme_name = t.get("name", "Thematic Basket")
        for sym in t.get("tickers", []):
            clean_sym = sym.strip().upper()
            # Only include liquid active symbols
            if clean_sym and (clean_sym in VALID_EQUITY_UNIVERSE or len(clean_sym) <= 4 and clean_sym.isalpha()):
                if clean_sym not in all_tickers:
                    all_tickers.append(clean_sym)
                    ticker_theme_map[clean_sym] = theme_name

    if not all_tickers:
        all_tickers = ["NVDA", "AMD", "FCX", "CCJ"]
        for sym in all_tickers:
            ticker_theme_map[sym] = "Default Balanced Theme"

    weight_per_ticker = 1.0 / len(all_tickers)
    capital_per_ticker = target_capital * weight_per_ticker

    allocations = {}
    for sym in all_tickers:
        allocations[sym] = {
            "target_weight": round(weight_per_ticker, 4),
            "target_dollars": round(capital_per_ticker, 2),
            "theme_name": ticker_theme_map[sym]
        }
    return allocations



def compute_rebalance_diff(
    current_positions: List[Dict[str, Any]],
    target_allocations: Dict[str, Dict[str, Any]],
    client: AlpacaClient
) -> List[Dict[str, Any]]:
    """Computes order diff (shares to buy/sell) to adjust current holdings to target.

    Args:
        current_positions: Currently held stock positions.
        target_allocations: Desired allocation mapping.
        client: AlpacaClient for price lookup.

    Returns:
        List of order instructions: [{'symbol': str, 'side': 'buy'|'sell', 'qty': float, 'reason': str}]
    """
    current_holdings = {
        p["symbol"]: {
            "qty": p.get("qty", 0.0),
            "current_price": p.get("current_price", client.get_latest_price(p["symbol"])),
            "market_value": p.get("market_value", 0.0)
        }
        for p in current_positions
        if p.get("asset_class") != "us_option"  # Exclude option legs from equity rebalancing
    }

    orders = []

    # 1. Liquidate or reduce positions no longer in target themes
    for sym, hold in current_holdings.items():
        if sym not in target_allocations:
            orders.append({
                "symbol": sym,
                "side": "sell",
                "qty": hold["qty"],
                "reason": f"Liquidate {sym}: Not in active thematic basket."
            })

    # 2. Rebalance or enter target theme positions
    for sym, target in target_allocations.items():
        price = client.get_latest_price(sym)
        target_qty = target["target_dollars"] / max(price, 0.01)
        current_qty = current_holdings.get(sym, {}).get("qty", 0.0)
        qty_diff = target_qty - current_qty

        # Only place order if rebalance delta is meaningful (> 5% of target shares or >= 1 share)
        if qty_diff > 0.5:
            orders.append({
                "symbol": sym,
                "side": "buy",
                "qty": round(qty_diff, 2),
                "reason": f"Rebalance buy {sym} to target {target['target_weight']*100:.1f}% (${target['target_dollars']:.2f})."
            })
        elif qty_diff < -0.5:
            orders.append({
                "symbol": sym,
                "side": "sell",
                "qty": round(abs(qty_diff), 2),
                "reason": f"Rebalance trim {sym} to target {target['target_weight']*100:.1f}%."
            })

    return orders


def run_theme_portfolio_layer(
    db: Optional[Session] = None,
    client: Optional[AlpacaClient] = None,
    llm: Optional[LLMProvider] = None
) -> Dict[str, Any]:
    """Main execution function for the daily Theme + Portfolio layer.

    1. Gathers news.
    2. Clusters themes with Groq LLM.
    3. Calculates target weights & rebalancing delta.
    4. Executes orders.
    5. Records audit log in DecisionLog and updates DB.
    """
    client = client or get_alpaca_client()
    llm = llm or get_llm_provider()
    db_session = db or SessionLocal()
    should_close_db = db is None

    try:
        account = client.get_account()
        total_equity = float(account.get("equity", 100000.0))
        # Keep 15% as cash buffer for options overlay margin & volatility
        equity_budget = total_equity * 0.85

        # 1. News collection
        news_items = fetch_news_for_theming(client, limit=12)

        # 2. LLM Theme Discovery
        cluster_result = cluster_news_into_themes(news_items, llm)
        themes = cluster_result.get("themes", [])
        reasoning = cluster_result.get("reasoning", "Thematic portfolio rebalanced based on incoming market catalysts.")

        # 3. Allocation mapping
        target_allocations = map_themes_to_allocation(themes, target_capital=equity_budget)

        # 4. Rebalance diff against current positions
        current_positions = client.get_positions()
        orders_to_execute = compute_rebalance_diff(current_positions, target_allocations, client)

        # 5. Execute orders
        executed_orders = []
        for ord_spec in orders_to_execute:
            res = client.submit_stock_order(
                symbol=ord_spec["symbol"],
                qty=ord_spec["qty"],
                side=ord_spec["side"]
            )
            executed_orders.append({
                "symbol": ord_spec["symbol"],
                "side": ord_spec["side"],
                "qty": ord_spec["qty"],
                "reason": ord_spec["reason"],
                "result": res
            })

        # 6. Persist ThemeBasket in DB
        # Mark previous baskets inactive
        db_session.query(ThemeBasket).filter(ThemeBasket.active == True).update({"active": False})
        saved_baskets = []
        for t in themes:
            basket = ThemeBasket(
                theme_name=t.get("name", "Thematic Discovery"),
                description=t.get("description", ""),
                tickers=t.get("tickers", []),
                allocation_weights={
                    sym: target_allocations[sym]["target_weight"]
                    for sym in t.get("tickers", []) if sym in target_allocations
                },
                active=True,
                created_at=datetime.now(timezone.utc)
            )
            db_session.add(basket)
            db_session.flush()
            saved_baskets.append(basket)

        # Update Position table from current broker state
        refreshed_positions = client.get_positions()
        active_equity_symbols = set()
        for p in refreshed_positions:
            if p.get("asset_class") != "us_option" and float(p.get("qty", 0)) > 0:
                active_equity_symbols.add(p["symbol"])
                existing = db_session.query(Position).filter(Position.ticker == p["symbol"]).first()
                if existing:
                    existing.quantity = float(p.get("qty", 0.0))
                    existing.entry_price = float(p.get("avg_entry_price", 0.0))
                    existing.current_value = float(p.get("market_value", 0.0))
                    if saved_baskets:
                        existing.theme_id = saved_baskets[0].id
                else:
                    db_session.add(Position(
                        ticker=p["symbol"],
                        quantity=float(p.get("qty", 0.0)),
                        entry_price=float(p.get("avg_entry_price", 0.0)),
                        current_value=float(p.get("market_value", 0.0)),
                        theme_id=saved_baskets[0].id if saved_baskets else None
                    ))

        # Delete any positions that have been liquidated or are no longer in active_equity_symbols
        if active_equity_symbols:
            db_session.query(Position).filter(~Position.ticker.in_(active_equity_symbols)).delete(synchronize_session=False)
        else:
            db_session.query(Position).delete(synchronize_session=False)

        # 7. Audit DecisionLog

        action_summary = (
            f"Discovered {len(themes)} themes: [{', '.join(t.get('name', '') for t in themes)}]. "
            f"Executed {len(executed_orders)} rebalancing trades across {len(target_allocations)} target holdings."
        )

        decision_log = DecisionLog(
            timestamp=datetime.now(timezone.utc),
            layer="theme",
            input_summary={
                "headlines_analyzed": [n.get("headline") for n in news_items[:5]],
                "target_equity": total_equity,
                "equity_budget": equity_budget
            },
            reasoning=reasoning,
            action_taken=action_summary
        )
        db_session.add(decision_log)
        db_session.commit()

        return {
            "status": "success",
            "layer": "theme_portfolio",
            "themes": themes,
            "target_allocations": target_allocations,
            "executed_orders": executed_orders,
            "reasoning": reasoning,
            "action_taken": action_summary
        }

    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error executing Theme Portfolio layer: {e}")
        return {"status": "error", "layer": "theme_portfolio", "error": str(e)}

    finally:
        if should_close_db:
            db_session.close()
