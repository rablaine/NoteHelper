"""
Scheduled milestone sync for NoteHelper.

Runs milestone import on a configurable daily schedule using a background
daemon thread. The sync hour is configured via the MILESTONE_SYNC_HOUR
environment variable (0-23, 24-hour format). If not set, scheduled sync
is disabled.

Usage:
    Set MILESTONE_SYNC_HOUR=3 in .env to sync daily at 3:00 AM local time.
"""
import os
import time
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_sync_thread = None
_sync_running = False


def start_scheduled_sync(app):
    """
    Start the background milestone sync scheduler if configured.

    Reads MILESTONE_SYNC_HOUR from environment. If set to a valid hour (0-23),
    starts a daemon thread that checks every 60 seconds whether it's time to
    run the daily milestone sync.

    Args:
        app: Flask application instance (needed for app context in background thread).
    """
    global _sync_thread, _sync_running

    sync_hour_str = os.environ.get('MILESTONE_SYNC_HOUR', '').strip()
    if not sync_hour_str:
        logger.info("MILESTONE_SYNC_HOUR not set — scheduled milestone sync disabled")
        return

    try:
        sync_hour = int(sync_hour_str)
        if not 0 <= sync_hour <= 23:
            raise ValueError(f"Hour must be 0-23, got {sync_hour}")
    except ValueError as e:
        logger.error(f"Invalid MILESTONE_SYNC_HOUR '{sync_hour_str}': {e}")
        return

    if _sync_running:
        logger.info("Scheduled milestone sync already running")
        return

    def _sync_loop():
        global _sync_running
        _sync_running = True
        last_sync_date = None
        logger.info(f"Scheduled milestone sync started (daily at {sync_hour:02d}:00)")

        while _sync_running:
            try:
                now = datetime.now()
                today = now.date()

                # Run once per day at the configured hour
                if now.hour == sync_hour and last_sync_date != today:
                    logger.info(f"Starting scheduled milestone sync at {now.isoformat()}")
                    last_sync_date = today

                    with app.app_context():
                        from app.models import User
                        from app.services.milestone_sync import sync_all_customer_milestones

                        # Use the first (default) user for sync
                        user = User.query.first()
                        if user:
                            result = sync_all_customer_milestones(user.id)
                            if result.get('success'):
                                logger.info(
                                    f"Scheduled sync complete: "
                                    f"{result.get('customers_synced', 0)} customers, "
                                    f"{result.get('milestones_created', 0)} new, "
                                    f"{result.get('milestones_updated', 0)} updated"
                                )
                            else:
                                logger.error(
                                    f"Scheduled sync failed: {result.get('error', 'Unknown error')}"
                                )
                        else:
                            logger.warning("No user found — skipping scheduled sync")

            except Exception as e:
                logger.error(f"Error in scheduled milestone sync: {e}")

            # Check every 60 seconds
            for _ in range(60):
                if not _sync_running:
                    break
                time.sleep(1)

        logger.info("Scheduled milestone sync stopped")

    _sync_thread = threading.Thread(target=_sync_loop, daemon=True)
    _sync_thread.start()


def stop_scheduled_sync():
    """Stop the background scheduled sync."""
    global _sync_running
    _sync_running = False
    logger.info("Scheduled milestone sync stop requested")
