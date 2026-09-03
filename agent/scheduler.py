"""APScheduler task scheduler registering three trading agent jobs at their cadences,
with an operator kill switch for autonomous execution.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from agent.config import settings
from agent.layers.theme_portfolio import run_theme_portfolio_layer
from agent.layers.derivatives_overlay import run_derivatives_overlay_layer
from agent.layers.expiration_watchdog import run_expiration_watchdog_layer
from agent.data.db import SessionLocal
from agent.data.models import DecisionLog

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Global state for Autonomous Mode (Kill Switch)
_autonomous_mode_active: bool = settings.AUTONOMOUS_MODE


def is_autonomous_mode_active() -> bool:
    """Returns True if autonomous scheduling and order execution is active."""
    return _autonomous_mode_active


def is_kill_switch_active() -> bool:
    """The kill switch blocks both scheduled and manually requested execution."""
    return not _autonomous_mode_active


def set_autonomous_mode(enabled: bool, db: Optional[Session] = None) -> Dict[str, Any]:
    """Toggles autonomous mode on or off.

    When OFF:
    - Pauses scheduler execution.
    - Blocks all layer runs.
    - Leaves existing positions/hedges intact.
    - Logs operator pause event to DecisionLog audit trail.

    When ON:
    - Resumes scheduler execution on normal cadence without immediate catch-up.
    - Logs operator resume event to DecisionLog audit trail.
    """
    global _autonomous_mode_active
    _autonomous_mode_active = bool(enabled)

    db_session = db or SessionLocal()
    should_close_db = db is None

    try:
        now = datetime.now(timezone.utc)
        if _autonomous_mode_active:
            if scheduler.running and scheduler.state == 2:  # STATE_PAUSED
                scheduler.resume()
            elif not scheduler.running:
                start_scheduler()
            logger.info("Autonomous mode RESUMED by operator.")

            action_text = "Autonomous Mode RESUMED by operator"
            reason_text = (
                "Operator enabled Autonomous Mode. Background scheduled cadences (daily theme rebalancing, "
                "hourly derivatives overlay, hourly expiration watchdog) have resumed normal execution."
            )
            input_summary = {"action": "resume", "source": "operator_switch"}
        else:
            if scheduler.running and scheduler.state == 1:  # STATE_RUNNING
                scheduler.pause()
            logger.info("Autonomous mode PAUSED by operator (Kill switch active).")

            action_text = "Autonomous Mode PAUSED by operator (Kill Switch active)"
            reason_text = (
                "Operator disabled Autonomous Mode. Background scheduler runs and automated trading decisions "
                "are suspended. All existing portfolio holdings and open derivative hedges remain intact."
            )
            input_summary = {"action": "pause", "source": "operator_switch"}

        log_entry = DecisionLog(
            timestamp=now,
            layer="system",
            input_summary=input_summary,
            reasoning=reason_text,
            action_taken=action_text
        )
        db_session.add(log_entry)
        db_session.commit()

        return {
            "autonomous_mode": _autonomous_mode_active,
            "status": "running" if _autonomous_mode_active else "paused",
            "message": action_text
        }

    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error toggling autonomous mode: {e}")
        return {
            "autonomous_mode": _autonomous_mode_active,
            "status": "error",
            "error": str(e)
        }
    finally:
        if should_close_db:
            db_session.close()


def job_theme_portfolio():
    """Daily theme discovery and portfolio rebalancing job."""
    if not is_autonomous_mode_active():
        logger.info("Autonomous mode is PAUSED. Skipping scheduled Theme Portfolio run.")
        return

    logger.info("Starting scheduled Theme + Portfolio layer run...")
    try:
        from agent.api.routes import layer_run_stats
        res = run_theme_portfolio_layer()
        layer_run_stats["theme"]["last_run"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Theme Portfolio layer completed: {res.get('status')}")
    except Exception as e:
        logger.exception(f"Scheduled Theme Portfolio job failed: {e}")


def job_derivatives_overlay():
    """Hourly derivatives overlay risk-check and hedging job."""
    if not is_autonomous_mode_active():
        logger.info("Autonomous mode is PAUSED. Skipping scheduled Derivatives Overlay run.")
        return

    logger.info("Starting scheduled Derivatives Overlay layer run...")
    try:
        from agent.api.routes import layer_run_stats
        res = run_derivatives_overlay_layer()
        layer_run_stats["overlay"]["last_run"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Derivatives Overlay layer completed: {res.get('status')}")
    except Exception as e:
        logger.exception(f"Scheduled Derivatives Overlay job failed: {e}")


def job_expiration_watchdog():
    """Hourly expiration watchdog position monitoring and roll/close enforcement job."""
    if not is_autonomous_mode_active():
        logger.info("Autonomous mode is PAUSED. Skipping scheduled Expiration Watchdog run.")
        return

    logger.info("Starting scheduled Expiration Watchdog layer run...")
    try:
        from agent.api.routes import layer_run_stats
        res = run_expiration_watchdog_layer()
        layer_run_stats["watchdog"]["last_run"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Expiration Watchdog layer completed: {res.get('status')}")
    except Exception as e:
        logger.exception(f"Scheduled Expiration Watchdog job failed: {e}")


def start_scheduler():
    """Initializes and starts the background scheduler with the three job cadences."""
    if not scheduler.running:
        # 1. Theme Portfolio (Daily)
        scheduler.add_job(
            job_theme_portfolio,
            trigger=IntervalTrigger(hours=settings.THEME_CADENCE_HOURS),
            id="theme_portfolio_job",
            name="Theme Discovery & Rebalance",
            replace_existing=True
        )

        # 2. Derivatives Overlay (Hourly)
        scheduler.add_job(
            job_derivatives_overlay,
            trigger=IntervalTrigger(minutes=settings.OVERLAY_CADENCE_MINUTES),
            id="derivatives_overlay_job",
            name="Derivatives Risk Overlay",
            replace_existing=True
        )

        # 3. Expiration Watchdog (Runs alongside overlay)
        scheduler.add_job(
            job_expiration_watchdog,
            trigger=IntervalTrigger(minutes=settings.OVERLAY_CADENCE_MINUTES),
            id="expiration_watchdog_job",
            name="Expiration Watchdog",
            replace_existing=True
        )

        scheduler.start()
        logger.info("APScheduler initialized and started with 3 jobs.")


def stop_scheduler():
    """Shuts down the background scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
