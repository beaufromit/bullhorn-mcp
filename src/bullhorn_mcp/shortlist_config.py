"""Per-instance JobSubmission configuration loaded from environment variables."""

import os

DEFAULT_SHORTLIST_STATUS = "Shortlisted"


def get_shortlist_status() -> str:
    """Return the configured JobSubmission status for shortlisting.

    Reads BULLHORN_SHORTLIST_STATUS; falls back to DEFAULT_SHORTLIST_STATUS.
    """
    return os.environ.get("BULLHORN_SHORTLIST_STATUS", DEFAULT_SHORTLIST_STATUS)
