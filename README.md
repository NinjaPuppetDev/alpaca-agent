# Alpaca Options Overlay Trading Agent

A FastAPI and React application for thematic equity allocation, risk-managed options overlays, and automated expiration handling through Alpaca Paper Trading. It includes a deterministic offline mode for local development and tests.

> **Trading safety:** Live trading is not supported. Alpaca credentials, when supplied, are used only with `paper=true`. Autonomous execution is opt-in and defaults to paused.

## What It Does

The agent runs three scheduled layers:

1. **Theme portfolio (`agent/layers/theme_portfolio.py`)** runs daily. It reads Alpaca news, asks the configured LLM to identify one or two themes, maps them to a predefined liquid-stock universe, calculates equal-weight allocations, and submits guarded rebalance orders.
2. **Derivatives overlay (`agent/layers/derivatives_overlay.py`)** runs hourly. It evaluates held equities using news, VWAP, volume, and exposure signals before selecting an allowed protective structure: `protective_put`, `collar`, `covered_call`, or `vertical_spread`.
3. **Expiration watchdog (`agent/layers/expiration_watchdog.py`)** runs on the overlay cadence. Open hedges at or below `EXPIRATION_THRESHOLD_DAYS` are closed and rolled when the underlying remains held, or closed completely when it has been sold.

Every layer records reasoning and actions in the SQLite `DecisionLog` audit trail. The assistant reasoning layer and shared execution pipeline add VWAP chase protection, partial take-profit evaluation, large-allocation hedge checks, and option-leg validation before routing orders.

## Architecture

```text
FastAPI (agent/main.py)
  - REST API (agent/api/routes.py)
  - APScheduler (agent/scheduler.py)
  - Theme, overlay, and watchdog layers
  - Shared execution and risk guardrails
  - AlpacaClient (paper API or deterministic mock)
  - SQLite state and audit trail

React/Vite dashboard (frontend/src)
  - Portfolio and account state
  - Hedges and expiration warnings
  - Decision log
  - Agent status, kill switch, liquidation, and manual triggers
```

## Technology

- Python 3.12+, FastAPI, SQLAlchemy, APScheduler, and pytest
- Alpaca Paper Trading through `alpaca-py`
- Groq LLM provider with a deterministic mock fallback
- SQLite database, defaulting to `trading_agent.db`
- React 18, Vite, Tailwind CSS, and Lucide React

## Project Structure

```text
agent/
  main.py                         FastAPI app and lifecycle management
  config.py                       Typed environment settings
  scheduler.py                    Scheduled jobs and autonomous-mode switch
  execution_pipeline.py           Shared order guardrails
  api/routes.py                   Dashboard and trading endpoints
  data/{db,models}.py             SQLite setup and ORM models
  layers/
    theme_portfolio.py            News to themes to equity rebalance
    derivatives_overlay.py        Equity risk to options overlay
    expiration_watchdog.py        Close or roll near-expiry hedges
    assisted_reasoning_layer.py   Pre-routing trade approval checks
  llm/provider.py                 LLM abstraction and providers
  risk/vwap_guard.py              VWAP and take-profit guardrails
  trading/                        Alpaca wrapper and trading risk helpers
frontend/src/                     React dashboard and UI components
tests/                            Unit and API/integration tests
docs/                             Position consistency documentation
```

## Setup

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

The default `.env.example` values start the system in mock, paused mode:

```ini
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_PAPER=true
AUTONOMOUS_MODE=false
GROQ_API_KEY=
LLM_MODEL=openai/gpt-oss-120b
LLM_REASONING_EFFORT=medium
EXPIRATION_THRESHOLD_DAYS=5
OVERLAY_CADENCE_MINUTES=60
THEME_CADENCE_HOURS=24
DATABASE_URL=sqlite:///./trading_agent.db
```

Blank Alpaca credentials select the simulated client. Mock positions persist in SQLite across restarts. A configured Groq key enables the remote provider; otherwise the application uses its deterministic fallback behavior.

Start the backend from the repository root:

```bash
source .venv/bin/activate
uvicorn agent.main:app --host 0.0.0.0 --port 8000 --reload
```

The API is documented at [http://localhost:8000/docs](http://localhost:8000/docs). At startup, the application initializes the database. It only seeds state and starts APScheduler when `AUTONOMOUS_MODE=true`; otherwise it remains paused.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The Vite development server proxies API requests to the backend according to `frontend/vite.config.js`.

For a production frontend bundle:

```bash
npm run build
```

When `frontend/dist` exists, FastAPI serves it from `/`.

## API Surface

All routes below use the `/api` prefix:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/portfolio` | Account, equity holdings, themes, and option positions |
| GET | `/hedges` | Open or historical hedges with DTE and warning flags |
| GET | `/decisions` | Reverse-chronological audit log; supports `layer` and `limit` |
| GET | `/status` | Scheduler state, cadences, providers, and layer health |
| GET/POST | `/autonomous-mode` | Read or toggle the autonomous execution kill switch |
| POST | `/trigger/{layer_name}` | Run `theme`, `overlay`, `watchdog`, or `all` when enabled |
| GET | `/account/summary` | Account cash, equity, buying power, and status |
| GET | `/account/positions` | Broker-synchronized equity and option positions |
| POST | `/positions/liquidate-smart` | Sell losing equity positions only |
| POST | `/positions/liquidate-all` | Liquidate all equity positions |
| POST | `/options/liquidate-smart` | Close losing option positions |
| POST | `/options/liquidate-all` | Close all option positions |
| POST | `/proposals/{proposal_id}/approve` | Approve a stored trade proposal |

The dashboard polls portfolio, hedges, decisions, and status every eight seconds. Manual layer triggers are blocked while the kill switch is active. Toggling autonomous mode pauses or resumes scheduled execution without removing existing holdings or hedges.

## Tests

```bash
source .venv/bin/activate
pytest -v
```

The test suite isolates Alpaca access, uses a temporary SQLite database, and covers the client wrapper, API routes, scheduler kill switch, LLM behavior, trading layers, consistency rules, and VWAP/risk guardrails.
