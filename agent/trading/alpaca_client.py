"""Alpaca Trading Client Wrapper.

Provides a unified interface for interacting with Alpaca's Paper Trading API,
covering Account status, Positions, Orders (Equity & Options), News, and Market Data.
Falls back to deterministic Mock state if credentials are missing or in simulated environments.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging
from agent.config import settings

logger = logging.getLogger(__name__)


class AlpacaClient:
    """Wrapper around alpaca-py and Alpaca REST APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: Optional[bool] = None
    ):
        self.api_key = settings.ALPACA_API_KEY if api_key is None else api_key
        self.secret_key = settings.ALPACA_SECRET_KEY if secret_key is None else secret_key
        configured_paper = settings.ALPACA_PAPER if paper is None else paper
        if paper is False:
            raise RuntimeError("Live trading is not supported; paper must be true.")
        self.paper = bool(configured_paper)
        has_credentials = bool(self.api_key and self.secret_key and len(self.api_key.strip()) > 5)
        self._is_live = bool(self.paper and has_credentials)

        self._trading_client = None
        self._stock_data_client = None
        self._mock_positions: Dict[str, Dict[str, Any]] = {}
        self._mock_cash = 100000.0

        if self._is_live:
            try:
                from alpaca.trading.client import TradingClient
                from alpaca.data.historical import StockHistoricalDataClient

                self._trading_client = TradingClient(
                    api_key=self.api_key,
                    secret_key=self.secret_key,
                    paper=True
                )
                self._stock_data_client = StockHistoricalDataClient(
                    api_key=self.api_key,
                    secret_key=self.secret_key
                )
                logger.info(f"Initialized live AlpacaClient (paper={self.paper}).")
            except Exception as e:
                logger.warning(f"Failed to initialize Alpaca SDK clients: {e}. Using simulated client.")
                self._is_live = False

        if not self._is_live:
            self._hydrate_mock_from_db()

    def _hydrate_mock_from_db(self):
        """Hydrates mock state from SQLite database so positions persist across restarts."""
        try:
            from agent.data.db import SessionLocal
            from agent.data.models import Position as PositionModel
            db = SessionLocal()
            positions = db.query(PositionModel).filter(PositionModel.quantity > 0).all()
            for p in positions:
                cur_px = self.get_latest_price(p.ticker)
                mkt_val = round(float(p.quantity) * cur_px, 2)
                self._mock_positions[p.ticker] = {
                    "symbol": p.ticker,
                    "qty": float(p.quantity),
                    "avg_entry_price": float(p.entry_price),
                    "current_price": cur_px,
                    "market_value": mkt_val,
                    "unrealized_pl": round((cur_px - float(p.entry_price)) * float(p.quantity), 2),
                    "asset_class": "us_equity",
                    "side": "long"
                }
            if self._mock_positions:
                total_pos_val = sum(p["market_value"] for p in self._mock_positions.values())
                self._mock_cash = max(10000.0, 100000.0 - total_pos_val)
            db.close()
        except Exception as e:
            logger.debug(f"Could not hydrate mock positions from DB: {e}")

    @property
    def is_live(self) -> bool:
        """Returns True if connected to live/paper Alpaca credentials."""
        return self._is_live

    def get_account(self) -> Dict[str, Any]:
        """Fetch account balance, cash, buying power, and portfolio value.

        Returns:
            Dict containing cash, equity, buying_power, and currency.
        """
        if self._is_live and self._trading_client:
            try:
                account = self._trading_client.get_account()
                return {
                    "id": account.id,
                    "cash": float(account.cash),
                    "equity": float(account.equity),
                    "buying_power": float(account.buying_power),
                    "portfolio_value": float(account.portfolio_value),
                    "currency": account.currency,
                    "status": account.status.value if hasattr(account.status, 'value') else str(account.status)
                }
            except Exception as e:
                logger.error(f"Error fetching Alpaca account: {e}")
                raise RuntimeError("Live Alpaca account sync failed.") from e

        # Simulated fallback - ensure hydration if empty
        if not self._mock_positions:
            self._hydrate_mock_from_db()

        total_pos_val = sum(p["market_value"] for p in self._mock_positions.values())
        equity = self._mock_cash + total_pos_val
        return {
            "id": "mock-account-001",
            "cash": self._mock_cash,
            "equity": equity,
            "buying_power": self._mock_cash * 2.0,
            "portfolio_value": equity,
            "currency": "USD",
            "status": "ACTIVE"
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch all held positions (equities and active options).

        Returns:
            List of position dicts with ticker, qty, avg_entry_price, market_value, asset_class.
        """
        if self._is_live and self._trading_client:
            try:
                positions = self._trading_client.get_all_positions()
                result = []
                for p in positions:
                    result.append({
                        "symbol": p.symbol,
                        "qty": float(p.qty),
                        "avg_entry_price": float(p.avg_entry_price),
                        "current_price": float(p.current_price) if p.current_price else float(p.avg_entry_price),
                        "market_value": float(p.market_value),
                        "unrealized_pl": float(p.unrealized_pl),
                        "asset_class": getattr(p, "asset_class", "us_equity"),
                        "side": getattr(p, "side", "long")
                    })
                if result:
                    return result
            except Exception as e:
                logger.error(f"Error fetching Alpaca positions: {e}")
                raise RuntimeError("Live Alpaca positions sync failed.") from e

        # Simulated fallback - ensure hydration if empty
        if not self._mock_positions:
            self._hydrate_mock_from_db()

        # Update current market value on get_positions
        for sym, pos in self._mock_positions.items():
            if pos.get("asset_class") != "us_option":
                cur_px = self.get_latest_price(sym)
                pos["current_price"] = cur_px
                pos["market_value"] = round(pos["qty"] * cur_px, 2)
                pos["unrealized_pl"] = round((cur_px - pos["avg_entry_price"]) * pos["qty"], 2)

        return list(self._mock_positions.values())



    def get_latest_price(self, symbol: str) -> float:
        """Fetch latest market price for a given ticker or option contract.

        Args:
            symbol: Ticker symbol (e.g. 'NVDA', 'FCX')

        Returns:
            Latest price as float.
        """
        if self._is_live and self._stock_data_client:
            try:
                from alpaca.data.requests import StockLatestQuoteRequest
                req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                quote = self._stock_data_client.get_stock_latest_quote(req)
                if symbol in quote:
                    ask = quote[symbol].ask_price
                    bid = quote[symbol].bid_price
                    if ask and bid:
                        return (float(ask) + float(bid)) / 2.0
                    return float(ask or bid or 100.0)
            except Exception as e:
                logger.warning(f"Failed to fetch live quote for {symbol}: {e}")

        # Default realistic baseline prices for mock/offline testing
        mock_prices = {
            "NVDA": 128.50,
            "AMD": 154.20,
            "TSM": 172.80,
            "AVGO": 165.00,
            "FCX": 44.80,
            "CCJ": 52.10,
            "ALB": 86.40,
            "NEE": 76.50,
            "AAPL": 225.00,
            "MSFT": 418.00,
            "AMZN": 178.50,
            "GOOGL": 164.20
        }
        return mock_prices.get(symbol.upper(), 100.0)

    def get_bars(self, symbol: str, timeframe_str: str = "1Hour", limit: int = 30) -> List[Dict[str, Any]]:
        """Fetch historical price and volume bars.

        Args:
            symbol: Stock symbol.
            timeframe_str: '1Hour', '1Day', etc.
            limit: Number of bars.

        Returns:
            List of bar dicts with close, vwap, volume, timestamp.
        """
        if self._is_live and self._stock_data_client:
            try:
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
                
                tf = TimeFrame.Hour if timeframe_str == "1Hour" else TimeFrame.Day
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(days=10)
                req = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=tf,
                    start=start_dt,
                    limit=limit
                )
                bars_response = self._stock_data_client.get_stock_bars(req)
                if symbol in bars_response:
                    return [
                        {
                            "timestamp": b.timestamp.isoformat(),
                            "open": float(b.open),
                            "high": float(b.high),
                            "low": float(b.low),
                            "close": float(b.close),
                            "volume": float(b.volume),
                            "vwap": float(b.vwap) if b.vwap else float(b.close)
                        }
                        for b in bars_response[symbol]
                    ]
            except Exception as e:
                logger.warning(f"Error fetching bars for {symbol}: {e}")

        # Simulated fallback bars
        base = self.get_latest_price(symbol)
        now = datetime.now(timezone.utc)
        sim_bars = []
        for i in range(limit, 0, -1):
            ts = now - timedelta(hours=i)
            # small downward trend for risk simulation
            drift = (i - limit / 2) * 0.05
            p = round(base - drift, 2)
            sim_bars.append({
                "timestamp": ts.isoformat(),
                "open": p - 0.2,
                "high": p + 0.5,
                "low": p - 0.6,
                "close": p,
                "volume": 150000.0 + (limit - i) * 5000.0,
                "vwap": round(p + 0.35, 2)  # price slightly below VWAP -> bearish confirmation
            })
        return sim_bars

    def get_news(self, symbols: Optional[List[str]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent financial news articles via Alpaca News.

        Args:
            symbols: Optional list of ticker symbols to filter by.
            limit: Maximum articles to fetch.

        Returns:
            List of news article dicts with headline, summary, symbols, created_at.
        """
        if self._is_live:
            try:
                import httpx
                headers = {
                    "APCA-API-KEY-ID": self.api_key,
                    "APCA-API-SECRET-KEY": self.secret_key
                }
                params: Dict[str, Any] = {"limit": limit}
                if symbols:
                    params["symbols"] = ",".join(symbols)
                url = "https://data.alpaca.markets/v1beta1/news"
                resp = httpx.get(url, headers=headers, params=params, timeout=10.0)
                if resp.status_code == 200:
                    news_data = resp.json().get("news", [])
                    return [
                        {
                            "id": item.get("id"),
                            "headline": item.get("headline"),
                            "summary": item.get("summary", ""),
                            "symbols": item.get("symbols", []),
                            "created_at": item.get("created_at"),
                            "url": item.get("url", "")
                        }
                        for item in news_data
                    ]
            except Exception as e:
                logger.warning(f"Error fetching news from Alpaca: {e}")

        # Simulated high-quality market news fallback
        now = datetime.now(timezone.utc)
        if symbols:
            return [
                {
                    "id": f"news-{s}-01",
                    "headline": f"{s} Faces Supply Chain Headwinds and Valuation Scrutiny in Latest Tech Survey",
                    "summary": f"Analysts flag margin compression and export license revisions affecting {s}.",
                    "symbols": [s],
                    "created_at": (now - timedelta(minutes=45)).isoformat(),
                    "url": "https://example.com/news"
                }
                for s in symbols[:limit]
            ]

        return [
            {
                "id": "news-macro-1",
                "headline": "Semiconductor CapEx Surges as AI Hyperscalers Double Down on Custom Accelerators",
                "summary": "Nvidia, AMD, and TSMC lead broad rally across hardware and fab suppliers.",
                "symbols": ["NVDA", "AMD", "TSM", "AVGO"],
                "created_at": (now - timedelta(hours=2)).isoformat(),
                "url": "https://example.com/news/1"
            },
            {
                "id": "news-macro-2",
                "headline": "Critical Minerals and Copper Demand Accelerate with Global Grid Upgrades",
                "summary": "Freeport-McMoRan and Cameco benefit from rising power transmission and nuclear infrastructure buildouts.",
                "symbols": ["FCX", "CCJ", "ALB"],
                "created_at": (now - timedelta(hours=3)).isoformat(),
                "url": "https://example.com/news/2"
            },
            {
                "id": "news-macro-3",
                "headline": "Tech Sector Earnings Preview: Focus Shifts to Free Cash Flow and Enterprise Software Spend",
                "summary": "Cloud giants navigate macro uncertainty while maintaining strong balance sheets.",
                "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN"],
                "created_at": (now - timedelta(hours=5)).isoformat(),
                "url": "https://example.com/news/3"
            }
        ]

    def get_option_contracts(
        self,
        underlying_symbol: str,
        expiration_date_gte: Optional[str] = None,
        expiration_date_lte: Optional[str] = None,
        option_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch available option contracts for an underlying ticker.

        Args:
            underlying_symbol: Ticker symbol (e.g. 'NVDA').
            expiration_date_gte: Start expiration date (YYYY-MM-DD).
            expiration_date_lte: End expiration date (YYYY-MM-DD).
            option_type: 'call' or 'put'.
            limit: Max contracts to return.

        Returns:
            List of option contract dicts.
        """
        if self._is_live and self._trading_client:
            try:
                from alpaca.trading.requests import GetOptionContractsRequest
                from alpaca.trading.enums import ContractType

                c_type = None
                if option_type == "call":
                    c_type = ContractType.CALL
                elif option_type == "put":
                    c_type = ContractType.PUT

                req = GetOptionContractsRequest(
                    underlying_symbols=[underlying_symbol],
                    expiration_date_gte=expiration_date_gte,
                    expiration_date_lte=expiration_date_lte,
                    type=c_type,
                    limit=limit
                )
                contracts_response = self._trading_client.get_option_contracts(req)
                contracts = contracts_response.option_contracts if hasattr(contracts_response, 'option_contracts') else contracts_response
                return [
                    {
                        "symbol": c.symbol,
                        "underlying_symbol": c.underlying_symbol,
                        "type": c.type.value if hasattr(c.type, 'value') else str(c.type),
                        "strike_price": float(c.strike_price),
                        "expiration_date": str(c.expiration_date),
                        "open_interest": int(c.open_interest or 0),
                        "close_price": float(c.close_price or 0.0),
                        # Contract metadata alone is not enough to prove liquidity. If
                        # Alpaca does not provide a usable market, risk selection rejects it.
                        "bid_price": float(getattr(c, "bid_price", 0.0) or 0.0),
                        "ask_price": float(getattr(c, "ask_price", 0.0) or 0.0)
                    }
                    for c in contracts
                ]
            except Exception as e:
                logger.warning(f"Error fetching option contracts for {underlying_symbol}: {e}")

        # Simulated option chain generator
        cur_price = self.get_latest_price(underlying_symbol)
        now = datetime.now(timezone.utc)
        target_exp = (now + timedelta(days=21)).strftime("%Y-%m-%d")
        exp_date_str = expiration_date_gte or target_exp

        contracts = []
        strikes = [
            round(cur_price * 0.90, 1),
            round(cur_price * 0.95, 1),
            round(cur_price * 1.00, 1),
            round(cur_price * 1.05, 1),
            round(cur_price * 1.10, 1)
        ]

        types = [option_type] if option_type else ["put", "call"]
        for t in types:
            for strike in strikes:
                # Alpaca Option Symbol standard format: e.g. NVDA240920P00125000
                exp_compact = exp_date_str.replace("-", "")[2:]
                strike_formatted = f"{int(strike * 1000):08d}"
                type_letter = "P" if t == "put" else "C"
                sym = f"{underlying_symbol}{exp_compact}{type_letter}{strike_formatted}"
                contracts.append({
                    "symbol": sym,
                    "underlying_symbol": underlying_symbol,
                    "type": t,
                    "strike_price": strike,
                    "expiration_date": exp_date_str,
                    "open_interest": 450,
                    "close_price": round(cur_price * 0.035, 2),
                    "bid_price": round(cur_price * 0.03, 2),
                    "ask_price": round(cur_price * 0.04, 2)
                })
        return contracts[:limit]

    def submit_stock_order(
        self,
        symbol: str,
        qty: float,
        side: str = "buy",
        order_type: str = "market",
        time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """Submit a stock order (buy/sell).

        Args:
            symbol: Ticker symbol.
            qty: Number of shares.
            side: 'buy' or 'sell'.
            order_type: 'market' or 'limit'.
            time_in_force: 'day' or 'gtc'.

        Returns:
            Order confirmation dict.
        """
        if qty <= 0:
            return {"status": "skipped", "reason": "Quantity must be > 0"}

        px = self.get_latest_price(symbol)
        if self._is_live and self._trading_client:
            try:
                from alpaca.trading.requests import MarketOrderRequest, OrderSide, TimeInForce
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                order = self._trading_client.submit_order(req)
                return {
                    "id": str(order.id),
                    "symbol": order.symbol,
                    "qty": float(order.qty),
                    "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                    "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                    "filled_avg_price": float(order.filled_avg_price or px)
                }
            except Exception as e:
                logger.error(f"Error submitting stock order for {symbol}: {e}")
                return {"status": "FAILED_BROKER_REJECT", "symbol": symbol, "error": str(e)}

        # Only the explicit offline simulator mutates simulated state. A failed live
        # submission must never fall through to a fabricated fill.
        cost = px * qty
        if side.lower() == "buy":
            self._mock_cash -= cost
            if symbol in self._mock_positions:
                old_qty = self._mock_positions[symbol]["qty"]
                old_cost = self._mock_positions[symbol]["avg_entry_price"] * old_qty
                new_qty = old_qty + qty
                self._mock_positions[symbol] = {"symbol": symbol, "qty": new_qty, "avg_entry_price": round((old_cost + cost) / new_qty, 2), "current_price": px, "market_value": round(new_qty * px, 2), "unrealized_pl": round((px - (old_cost + cost) / new_qty) * new_qty, 2), "asset_class": "us_equity", "side": "long"}
            else:
                self._mock_positions[symbol] = {"symbol": symbol, "qty": qty, "avg_entry_price": px, "current_price": px, "market_value": round(qty * px, 2), "unrealized_pl": 0.0, "asset_class": "us_equity", "side": "long"}
        elif symbol in self._mock_positions:
            cur_qty = self._mock_positions[symbol]["qty"]
            sell_qty = min(qty, cur_qty)
            self._mock_cash += sell_qty * px
            remaining = cur_qty - sell_qty
            if remaining > 0:
                self._mock_positions[symbol]["qty"] = remaining
                self._mock_positions[symbol]["market_value"] = round(remaining * px, 2)
            else:
                del self._mock_positions[symbol]

        return {
            "id": f"sim-order-{symbol}-{int(datetime.now().timestamp())}",
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "status": "filled",
            "filled_avg_price": px
        }


    def place_option_order(
        self,
        symbol: str,
        qty: int,
        side: str = "buy",
        order_type: str = "market",
        time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """Submit a single-leg option contract order.

        Args:
            symbol: Full OCC Option Symbol (e.g. 'NVDA240920P00125000').
            qty: Number of contracts.
            side: 'buy' or 'sell'.
            order_type: 'market' or 'limit'.
            time_in_force: 'day'.

        Returns:
            Order confirmation dict.
        """
        if self._is_live and self._trading_client:
            try:
                from alpaca.trading.requests import MarketOrderRequest, OrderSide, TimeInForce
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                order = self._trading_client.submit_order(req)
                return {
                    "id": str(order.id),
                    "symbol": order.symbol,
                    "qty": float(order.qty),
                    "side": str(order.side),
                    "status": str(order.status)
                }
            except Exception as e:
                logger.error(f"Error submitting option order {symbol}: {e}")
                return {"status": "FAILED_BROKER_REJECT", "symbol": symbol, "error": str(e)}

        # Simulated option order
        est_price = 3.50
        cost = est_price * 100 * qty
        if side.lower() == "buy":
            self._mock_cash -= cost
            self._mock_positions[symbol] = {
                "symbol": symbol,
                "qty": qty,
                "avg_entry_price": est_price,
                "current_price": est_price,
                "market_value": round(cost, 2),
                "unrealized_pl": 0.0,
                "asset_class": "us_option",
                "side": "long"
            }
        else:
            self._mock_cash += cost
            self._mock_positions[symbol] = {
                "symbol": symbol,
                "qty": qty,
                "avg_entry_price": est_price,
                "current_price": est_price,
                "market_value": -round(cost, 2),
                "unrealized_pl": 0.0,
                "asset_class": "us_option",
                "side": "short"
            }

        return {
            "id": f"sim-opt-{symbol}-{int(datetime.now().timestamp())}",
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "status": "filled",
            "filled_avg_price": est_price
        }

    def place_multi_leg_option_order(
        self,
        legs: List[Dict[str, Any]],
        order_type: str = "market",
        time_in_force: str = "day"
    ) -> List[Dict[str, Any]]:
        """Submit multi-leg option orders (collars, vertical spreads).

        Args:
            legs: List of leg dicts with {'symbol': str, 'qty': int, 'side': 'buy'|'sell'}

        Returns:
            List of order confirmations.
        """
        results = []
        for leg in legs:
            res = self.place_option_order(
                symbol=leg["symbol"],
                qty=int(leg.get("qty", 1)),
                side=leg.get("side", "buy"),
                order_type=order_type,
                time_in_force=time_in_force
            )
            results.append(res)
        return results

    def close_position(self, symbol: str) -> Dict[str, Any]:
        """Close an open position (equity or option).

        Args:
            symbol: Ticker symbol or option contract symbol.

        Returns:
            Close order confirmation.
        """
        if self._is_live and self._trading_client:
            try:
                res = self._trading_client.close_position(symbol)
                return {
                    "symbol": symbol,
                    "status": "closed",
                    "order_id": str(getattr(res, "id", ""))
                }
            except Exception as e:
                logger.error(f"Error closing position {symbol}: {e}")
                return {"symbol": symbol, "status": "FAILED_BROKER_REJECT", "error": str(e)}

        # Simulated close
        if symbol in self._mock_positions:
            pos = self._mock_positions.pop(symbol)
            qty = pos["qty"]
            side = pos.get("side", "long")
            px = pos.get("current_price", 100.0)
            multiplier = 100.0 if pos.get("asset_class") == "us_option" else 1.0
            if side == "long":
                self._mock_cash += qty * px * multiplier
            else:
                self._mock_cash -= qty * px * multiplier
            return {"symbol": symbol, "status": "closed", "qty": qty}

        return {"symbol": symbol, "status": "closed_noop", "reason": "Not found in mock positions"}


_alpaca_client_instance: Optional[AlpacaClient] = None


def get_alpaca_client() -> AlpacaClient:
    """Singleton getter for AlpacaClient."""
    global _alpaca_client_instance
    if _alpaca_client_instance is None:
        _alpaca_client_instance = AlpacaClient()
    return _alpaca_client_instance
