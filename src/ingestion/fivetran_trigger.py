import logging
import time

import requests

from src.utils.config import config

logger = logging.getLogger(__name__)

_FIVETRAN_BASE = "https://api.fivetran.com/v1"
_POLL_INTERVAL_SECONDS = 10

# Fivetran sync_state values that mean the sync is done (successfully or not).
_TERMINAL_SUCCESS = {"scheduled", "rescheduled"}
_TERMINAL_FAILURE = {"broken", "paused"}


def _auth() -> tuple[str, str]:
    return (config.FIVETRAN_API_KEY, config.FIVETRAN_API_SECRET)


def trigger_sync() -> None:
    """POST to Fivetran to kick off a sync for the configured connector."""
    url = f"{_FIVETRAN_BASE}/connectors/{config.FIVETRAN_CONNECTOR_ID}/sync"
    logger.info("Triggering Fivetran sync for connector %s", config.FIVETRAN_CONNECTOR_ID)
    resp = requests.post(url, auth=_auth(), timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Fivetran trigger failed: HTTP {resp.status_code} — {resp.text[:500]}"
        )
    logger.info("Sync triggered: %s", resp.json().get("message", "OK"))


def poll_sync_status(timeout_seconds: int = 300) -> None:
    """Poll Fivetran connector status until sync completes or timeout is exceeded.

    Fivetran sync is async — callers must wait for sync_state to leave "syncing"
    before reading from BigQuery or the table may have stale / partial data.
    """
    url = f"{_FIVETRAN_BASE}/connectors/{config.FIVETRAN_CONNECTOR_ID}"
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        resp = requests.get(url, auth=_auth(), timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Fivetran status check failed: HTTP {resp.status_code} — {resp.text[:500]}"
            )

        sync_state = resp.json().get("data", {}).get("status", {}).get("sync_state", "")
        logger.info("Fivetran sync_state: %s", sync_state)

        if sync_state in _TERMINAL_SUCCESS:
            logger.info("Sync completed successfully (state=%s)", sync_state)
            return

        if sync_state in _TERMINAL_FAILURE:
            raise RuntimeError(
                f"Fivetran connector entered terminal state '{sync_state}' "
                f"for connector {config.FIVETRAN_CONNECTOR_ID}. Check the Fivetran dashboard."
            )

        time.sleep(_POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Fivetran sync did not complete within {timeout_seconds}s "
        f"for connector {config.FIVETRAN_CONNECTOR_ID}"
    )
