# Alpaca Autonomous Options Overlay Trading Agent

An autonomous three-layer trading agent designed for the **Alpaca AI Trading Agents Hackathon**. The agent discovers thematic portfolios from market news, rebalances equity holdings over time, and overlays risk-mitigating options structures (protective puts, zero-cost collars, covered calls, and vertical spreads) with strict automated expiration management.

---

## 🏛️ System Architecture

```
                               ┌──────────────────────────────────────────────┐
                               │             FastAPI Backend REST             │
                               │  (/api/portfolio, /api/hedges, /api/status)  │
                               └──────────────────────┬───────────────────────┘
                                                      │
                       ┌──────────────────────────────┼──────────────────────────────┐
                       │                              │                              │
        ┌──────────────▼─────────────┐ ┌──────────────▼─────────────┐ ┌──────────────▼─────────────┐
        │  Layer 1: Theme Portfolio  │ │ Layer 2: Overlay Engine    │ │ Layer 3: Expiration Watchdog│
        │      (Cadence: Daily)      │ │      (Cadence: Hourly)     │ │      (Cadence: Hourly)     │
        ├────────────────────────────┤ ├────────────────────────────┤ ├────────────────────────────┤
        │ • Fetch news via Alpaca    │ │ • Held equity risk check   │ │ • Scan open Hedge records  │
        │ • Groq LLM theme clustering│ │ • News + VWAP/vol confirm  │ │ • Check DTE ≤ 5 threshold  │
        │ • Map themes to tickers    │ │ • Classify exposure shape  │ │ • Enforce ROLL or CLOSE    │
        │ • Equal-weight allocations │ │ • Place protective overlay │ │ • Zero unmanaged expiries  │
        │ • Rebalance orders         │ │ • Log rule/signal firing   │ │ • Record audit trail       │
        └──────────────┬─────────────┘ └──────────────┬─────────────┘ └──────────────┬─────────────┘
                       │                              │                              │
                       └──────────────────────────────┼──────────────────────────────┘
                                                      │
                                ┌─────────────────────▼─────────────────────┐
                                │             Alpaca Client Wrapper         │
                                │   (Paper Trading API / alpaca-py / Data)  │
                                └─────────────────────┬─────────────────────┘
                                                      │
                                ┌─────────────────────▼─────────────────────┐
                                │        SQLite Audit Trail & Models        │
                                │ (ThemeBasket, Position, Hedge, DecisionLog)│
                                └───────────────────────────────────────────┘
```

---

## 📦 Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy (SQLite), APScheduler
- **LLM Provider:** Groq API (`openai/gpt-oss-120b`) behind an abstract `LLMProvider` interface (with deterministic mock fallback)
- **Broker & Data:** Alpaca Paper Trading API via `alpaca-py` & REST market data
- **Frontend:** React 18 + Vite + Tailwind CSS + Lucide Icons (Fast-polling dashboard)

---

## ⚡ The Three Core Layers

### 1. Daily Theme & Portfolio Layer (`agent/layers/theme_portfolio.py`)
- Ingests recent financial headlines via `AlpacaClient.get_news`.
- Prompts Groq LLM to cluster catalysts into 1–2 thematic baskets (e.g. *Semiconductors & AI Hardware*, *Critical Minerals*).
- Maps themes to liquid US equity baskets and computes equal-weight target allocations.
- Computes difference against currently held positions and submits market rebalance orders.
- Writes full reasoning and trade actions to `DecisionLog`.

### 2. Hourly Derivatives Overlay Layer (`agent/layers/derivatives_overlay.py`)
- Evaluates equity delta and exposure for all held stocks.
- **News-Gating & Confirmation:** Cross-checks news catalysts with intraday VWAP divergence and elevated volume before hedging.
- **Strict Allowed Structures:**
  - `protective_put`: Downside buffer for long stock.
  - `collar`: Protective put financed by selling an OTM covered call.
  - `covered_call`: Harvests premium during range-bound conditions.
  - `vertical_spread`: Defined-risk bear put spreads.
  - *Strict Rule:* Never places standalone directional bets; disallows butterflies and iron condors.
- Submits multi-leg options orders to Alpaca and records `Hedge` records.

### 3. Hourly Expiration Watchdog (`agent/layers/expiration_watchdog.py`)
- Scans all active `Hedge` rows in SQLite.
- Computes Days-to-Expiration (DTE) against the configured threshold (`EXPIRATION_THRESHOLD_DAYS=5`).
- **Enforces Close-or-Roll:**
  - If underlying stock is still held: Closes expiring legs and rolls out to a fresh 21–30 DTE contract.
  - If underlying stock was sold: Closes option overlay completely.
- Guarantees **no options position crosses into its final week unmanaged**.

---

## 🖥️ Frontend Dashboard (4 Panels)

1. **Portfolio Overview:** Real-time equity, cash buffer, active thematic baskets, and holdings table with weights and unrealized P/L.
2. **Active Hedges:** Open options positions table with structure type, multi-leg specs, expiration dates, DTE countdown, and **visual warning flags for positions $\le 5$ DTE**.
3. **Decision Log:** Reverse-chronological audit trail of agent reasoning, LLM inputs, and trade executions backing judge reviews.
4. **Agent Status & Controls:** Cadence indicators, engine health, and **interactive manual trigger buttons** to run any layer on demand.

---

## 🚀 Quickstart Guide

### 1. Clone & Setup Python Virtual Environment
```bash
git clone <repo-url>
cd alpaca

# Create & activate venv
python3 -m venv venv
source venv/bin/activate

# Install backend dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

```ini
ALPACA_API_KEY=your_alpaca_key_id
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_PAPER=true

GROQ_API_KEY=your_groq_api_key
LLM_MODEL=openai/gpt-oss-120b
LLM_REASONING_EFFORT=medium

EXPIRATION_THRESHOLD_DAYS=5
OVERLAY_CADENCE_MINUTES=60
THEME_CADENCE_HOURS=24
DATABASE_URL=sqlite:///./trading_agent.db
```

*(Note: The agent seamlessly defaults to simulated mock mode if Alpaca or Groq keys are left blank, enabling full local testing out of the box).*

### 3. Run Backend Server
```bash
source venv/bin/activate
uvicorn agent.main:app --host 0.0.0.0 --port 8000 --reload
```
API Documentation will be available at [http://localhost:8000/docs](http://localhost:8000/docs).

### 4. Run Frontend Dashboard
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## 🧪 Running Tests
```bash
source venv/bin/activate
pytest -v
```
All unit and integration tests covering the Alpaca client wrapper, risk calculations, VWAP confirmation, LLM provider, three execution layers, and FastAPI routes run deterministically.
