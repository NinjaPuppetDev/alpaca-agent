"""FastAPI entrypoint for the Alpaca Options Overlay Trading Agent backend."""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.config import settings
from agent.data.db import init_db, SessionLocal
from agent.data.models import ThemeBasket, Position, Hedge, DecisionLog
from agent.api.routes import router as api_router
from agent.scheduler import start_scheduler, stop_scheduler
from agent.layers.theme_portfolio import run_theme_portfolio_layer
from agent.layers.derivatives_overlay import run_derivatives_overlay_layer
from agent.execution_pipeline import run_execution_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def seed_initial_state_if_empty():
    """Seeds initial baseline theme & positions on clean database startup if none exist."""
    db = SessionLocal()
    try:
        theme_count = db.query(ThemeBasket).count()
        if theme_count == 0:
            logger.info("Empty database detected. Running initial Theme & Overlay pass to bootstrap demo state...")
            run_theme_portfolio_layer(db=db)
            run_derivatives_overlay_layer(db=db)
    except Exception as e:
        logger.warning(f"Initial state bootstrap notice: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle manager."""
    logger.info("Initializing Alpaca Options Overlay Agent...")
    init_db()
    # Never bootstrap or schedule trading unless the operator explicitly opts in.
    if settings.AUTONOMOUS_MODE:
        seed_initial_state_if_empty()
        start_scheduler()
    else:
        logger.warning("AUTONOMOUS_MODE is not enabled; skipping bootstrap and scheduler startup.")
    yield
    logger.info("Shutting down agent services...")
    stop_scheduler()


app = FastAPI(
    title="Alpaca Options Overlay Trading Agent API",
    description="Autonomous 3-layer thematic & risk-managed options overlay trading agent for Alpaca Paper Trading.",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=True,
)

# Enable CORS before registering API routes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Mount frontend build if available
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/")
    def root():
        """Health & root landing."""
        return {
            "name": "Alpaca Options Overlay Trading Agent",
            "status": "online",
            "docs": "/docs",
            "api": "/api/status"
        }



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent.main:app", host="0.0.0.0", port=8000, reload=True)
