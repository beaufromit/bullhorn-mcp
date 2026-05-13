"""Per-instance Candidate configuration loaded from environment variables.

Three optional env vars control instance-specific Candidate behaviour:
  BULLHORN_CANDIDATE_ALIASES  - JSON object of {alias_lowercase: api_field_name}
  BULLHORN_CANDIDATE_REQUIRED - JSON array of additional required field names/aliases
  BULLHORN_CANDIDATE_DEFAULTS - JSON object of {field_name_or_alias: default_value}

Invalid JSON logs a warning and falls back to the empty default so the server
still starts with a misconfigured value.
"""

import json
import logging
import os

_logger = logging.getLogger(__name__)


def _load_json_env(var_name: str, default):
    """Load a JSON-encoded env var. Returns default on missing or invalid JSON."""
    raw = os.environ.get(var_name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _logger.warning("Invalid JSON in %s, falling back to default. Error: %s", var_name, e)
        return default


def get_candidate_aliases() -> dict[str, str]:
    """Return env-defined Candidate aliases keyed by lowercased alias."""
    raw = _load_json_env("BULLHORN_CANDIDATE_ALIASES", {})
    if not isinstance(raw, dict):
        return {}
    return {k.lower(): v for k, v in raw.items()}


def get_candidate_required() -> list[str]:
    """Return env-defined additional required Candidate field names."""
    raw = _load_json_env("BULLHORN_CANDIDATE_REQUIRED", [])
    return list(raw) if isinstance(raw, list) else []


def get_candidate_defaults() -> dict:
    """Return env-defined default values for Candidate fields."""
    raw = _load_json_env("BULLHORN_CANDIDATE_DEFAULTS", {})
    return dict(raw) if isinstance(raw, dict) else {}
