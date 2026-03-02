"""
Update checker service for NoteHelper.

Periodically checks if new commits are available on the remote main branch
and caches the result. Used to show an update notification in the UI.
"""
import subprocess
import threading
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Cached update state (module-level singleton)
_update_state = {
    'available': False,
    'local_commit': None,
    'remote_commit': None,
    'commits_behind': 0,
    'last_checked': None,
    'error': None,
}
_lock = threading.Lock()


def get_update_state() -> dict:
    """Return the current cached update state."""
    with _lock:
        return dict(_update_state)


def check_for_updates() -> dict:
    """
    Run git fetch and compare local HEAD to origin/main.
    Updates the cached state and returns it.
    """
    try:
        # git fetch origin main (quiet, timeout after 15 seconds)
        subprocess.run(
            ['git', 'fetch', 'origin', 'main', '--quiet'],
            capture_output=True, text=True, timeout=15,
            cwd=_get_repo_root()
        )

        repo_root = _get_repo_root()

        # Get local HEAD commit
        local = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=5, cwd=repo_root
        ).stdout.strip()

        # Get remote commit
        remote = subprocess.run(
            ['git', 'rev-parse', 'origin/main'],
            capture_output=True, text=True, timeout=5, cwd=repo_root
        ).stdout.strip()

        # Count commits behind
        behind = 0
        if local != remote:
            result = subprocess.run(
                ['git', 'rev-list', '--count', f'{local}..{remote}'],
                capture_output=True, text=True, timeout=5, cwd=repo_root
            )
            behind = int(result.stdout.strip()) if result.stdout.strip() else 0

        with _lock:
            _update_state['available'] = local != remote and behind > 0
            _update_state['local_commit'] = local[:7] if local else None
            _update_state['remote_commit'] = remote[:7] if remote else None
            _update_state['commits_behind'] = behind
            _update_state['last_checked'] = datetime.now(timezone.utc).isoformat()
            _update_state['error'] = None

    except subprocess.TimeoutExpired:
        logger.warning("Update check timed out (git fetch)")
        with _lock:
            _update_state['error'] = 'timeout'
            _update_state['last_checked'] = datetime.now(timezone.utc).isoformat()
    except FileNotFoundError:
        logger.warning("Git not found -- update checking disabled")
        with _lock:
            _update_state['error'] = 'git_not_found'
            _update_state['last_checked'] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.warning(f"Update check failed: {e}")
        with _lock:
            _update_state['error'] = str(e)
            _update_state['last_checked'] = datetime.now(timezone.utc).isoformat()

    return get_update_state()


def _get_repo_root() -> str:
    """Get the repository root directory."""
    import os
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _check_loop(interval_seconds: int) -> None:
    """Background loop that checks for updates periodically."""
    # Initial delay to let the app finish starting up
    time.sleep(30)
    while True:
        try:
            check_for_updates()
        except Exception as e:
            logger.error(f"Update check loop error: {e}")
        time.sleep(interval_seconds)


def start_update_checker(interval_seconds: int = 43200) -> None:
    """
    Start the background update checker thread.

    Args:
        interval_seconds: How often to check (default: 43200 = 12 hours)
    """
    thread = threading.Thread(
        target=_check_loop,
        args=(interval_seconds,),
        daemon=True,
        name='update-checker'
    )
    thread.start()
    logger.info(f"Update checker started (every {interval_seconds // 3600}h)")
