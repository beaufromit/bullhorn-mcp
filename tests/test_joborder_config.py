"""Tests for per-instance JobOrder env configuration loaders."""

import json
import logging
import pytest
from bullhorn_mcp.joborder_config import (
    get_joborder_aliases,
    get_joborder_defaults,
    get_joborder_required,
)


class TestGetJoborderAliases:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BULLHORN_JOBORDER_ALIASES", raising=False)
        assert get_joborder_aliases() == {}

    def test_valid_json_object_lowercases_keys(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_ALIASES", '{"Sector": "customText1", "Fee": "feeArrangement"}')
        result = get_joborder_aliases()
        assert result == {"sector": "customText1", "fee": "feeArrangement"}

    def test_invalid_json_returns_empty_and_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("BULLHORN_JOBORDER_ALIASES", "not-valid-json")
        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.joborder_config"):
            result = get_joborder_aliases()
        assert result == {}
        assert "BULLHORN_JOBORDER_ALIASES" in caplog.text

    def test_wrong_type_json_array_returns_empty(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_ALIASES", '["sector", "fee"]')
        assert get_joborder_aliases() == {}


class TestGetJoborderRequired:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BULLHORN_JOBORDER_REQUIRED", raising=False)
        assert get_joborder_required() == []

    def test_valid_json_array(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", '["source", "salary"]')
        assert get_joborder_required() == ["source", "salary"]

    def test_invalid_json_returns_empty_and_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", "{bad json}")
        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.joborder_config"):
            result = get_joborder_required()
        assert result == []
        assert "BULLHORN_JOBORDER_REQUIRED" in caplog.text


class TestGetJoborderDefaults:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BULLHORN_JOBORDER_DEFAULTS", raising=False)
        assert get_joborder_defaults() == {}

    def test_valid_json_object(self, monkeypatch):
        monkeypatch.setenv(
            "BULLHORN_JOBORDER_DEFAULTS",
            '{"status": "Accepting Candidates", "isOpen": true, "customText12": 0}',
        )
        result = get_joborder_defaults()
        assert result == {"status": "Accepting Candidates", "isOpen": True, "customText12": 0}

    def test_invalid_json_returns_empty_and_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("BULLHORN_JOBORDER_DEFAULTS", "not json at all")
        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.joborder_config"):
            result = get_joborder_defaults()
        assert result == {}
        assert "BULLHORN_JOBORDER_DEFAULTS" in caplog.text
