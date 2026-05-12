"""Tests for shortlist_config.py — per-instance JobSubmission status configuration."""

import pytest
from bullhorn_mcp.shortlist_config import get_shortlist_status, DEFAULT_SHORTLIST_STATUS


class TestGetShortlistStatus:
    def test_default_status_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BULLHORN_SHORTLIST_STATUS", raising=False)
        assert get_shortlist_status() == DEFAULT_SHORTLIST_STATUS
        assert get_shortlist_status() == "Shortlisted"

    def test_custom_status_when_env_set(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_SHORTLIST_STATUS", "Internal Review")
        assert get_shortlist_status() == "Internal Review"

    def test_whitespace_preserved(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_SHORTLIST_STATUS", " Long-listed ")
        assert get_shortlist_status() == " Long-listed "
