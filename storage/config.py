"""Configuration for BaseMem, read from environment variables."""

import os


def get_session_timeout_hours() -> int:
    """Return the configured session timeout in hours (default 24)."""
    raw = os.environ.get("BASEMEM_SESSION_TIMEOUT_HOURS", "24")
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        return 24
