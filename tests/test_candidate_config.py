"""Tests for per-instance Candidate env configuration loaders."""

import json
import logging
import pytest
from bullhorn_mcp.candidate_config import (
    get_candidate_aliases,
    get_candidate_defaults,
    get_candidate_required,
)


class TestGetCandidateAliases:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BULLHORN_CANDIDATE_ALIASES", raising=False)
        assert get_candidate_aliases() == {}

    def test_valid_json_object_lowercases_keys(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_CANDIDATE_ALIASES", '{"Source": "source", "Vertical": "customText1"}')
        result = get_candidate_aliases()
        assert result == {"source": "source", "vertical": "customText1"}

    def test_invalid_json_returns_empty_and_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("BULLHORN_CANDIDATE_ALIASES", "not-valid-json")
        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.candidate_config"):
            result = get_candidate_aliases()
        assert result == {}
        assert "BULLHORN_CANDIDATE_ALIASES" in caplog.text

    def test_wrong_type_json_array_returns_empty(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_CANDIDATE_ALIASES", '["source", "vertical"]')
        assert get_candidate_aliases() == {}


class TestGetCandidateRequired:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BULLHORN_CANDIDATE_REQUIRED", raising=False)
        assert get_candidate_required() == []

    def test_valid_json_array(self, monkeypatch):
        monkeypatch.setenv("BULLHORN_CANDIDATE_REQUIRED", '["source", "status"]')
        assert get_candidate_required() == ["source", "status"]

    def test_invalid_json_returns_empty_and_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("BULLHORN_CANDIDATE_REQUIRED", "{bad json}")
        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.candidate_config"):
            result = get_candidate_required()
        assert result == []
        assert "BULLHORN_CANDIDATE_REQUIRED" in caplog.text


class TestGetCandidateDefaults:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BULLHORN_CANDIDATE_DEFAULTS", raising=False)
        assert get_candidate_defaults() == {}

    def test_valid_json_object(self, monkeypatch):
        monkeypatch.setenv(
            "BULLHORN_CANDIDATE_DEFAULTS",
            '{"status": "Active", "source": "LinkedIn", "isDeleted": false}',
        )
        result = get_candidate_defaults()
        assert result == {"status": "Active", "source": "LinkedIn", "isDeleted": False}

    def test_invalid_json_returns_empty_and_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("BULLHORN_CANDIDATE_DEFAULTS", "not json at all")
        with caplog.at_level(logging.WARNING, logger="bullhorn_mcp.candidate_config"):
            result = get_candidate_defaults()
        assert result == {}
        assert "BULLHORN_CANDIDATE_DEFAULTS" in caplog.text
