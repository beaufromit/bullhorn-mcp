"""Tests for fuzzy string matching and confidence scoring."""

import pytest
from bullhorn_mcp.fuzzy import normalize, score_company_match, categorize_score, score_contact_match


class TestNormalize:
    def test_normalize_strips_ltd(self):
        assert normalize("Acme Ltd") == "acme"

    def test_normalize_strips_incorporated(self):
        assert normalize("Acme Incorporated") == "acme"

    def test_normalize_case_insensitive(self):
        assert normalize("ACME CORP") == "acme"

    def test_normalize_strips_punctuation(self):
        assert normalize("Acme, Inc.") == "acme"

    def test_normalize_strips_limited(self):
        assert normalize("Acme Limited") == "acme"

    def test_normalize_strips_plc(self):
        assert normalize("Acme PLC") == "acme"

    def test_normalize_strips_llc(self):
        assert normalize("Acme LLC") == "acme"

    def test_normalize_preserves_meaningful_words(self):
        result = normalize("Bank of New York Mellon")
        assert "bank" in result
        assert "new" in result
        assert "york" in result
        assert "mellon" in result


class TestScoreCompanyMatch:
    def test_score_exact_match(self):
        score = score_company_match("Acme Holdings Ltd", "Acme Holdings Ltd")
        assert score >= 0.95

    def test_score_suffix_variation(self):
        """'Acme Ltd' vs 'Acme Limited' should both normalize to 'acme' → exact."""
        score = score_company_match("Acme Ltd", "Acme Limited")
        assert score >= 0.95

    def test_score_acronym_match(self):
        """'BNY' vs 'Bank of New York Mellon' → likely match."""
        score = score_company_match("BNY", "Bank of New York Mellon")
        assert 0.75 <= score <= 0.95

    def test_score_unrelated(self):
        score = score_company_match("Acme", "Globex")
        assert score < 0.50

    def test_score_possible_match(self):
        score = score_company_match("Acme Holdings", "Acme Group")
        assert 0.50 <= score < 0.95

    def test_score_case_insensitive(self):
        score1 = score_company_match("acme corp", "ACME CORPORATION")
        score2 = score_company_match("ACME CORP", "Acme Corporation")
        assert abs(score1 - score2) < 0.01

    def test_score_empty_query_returns_zero(self):
        assert score_company_match("", "Acme") == 0.0

    def test_score_clamped_to_one(self):
        score = score_company_match("Acme", "Acme")
        assert score <= 1.0


class TestCategorizeScore:
    def test_categorize_exact(self):
        assert categorize_score(0.95) == "exact"
        assert categorize_score(1.0) == "exact"

    def test_categorize_likely(self):
        assert categorize_score(0.75) == "likely"
        assert categorize_score(0.94) == "likely"

    def test_categorize_possible(self):
        assert categorize_score(0.50) == "possible"
        assert categorize_score(0.74) == "possible"

    def test_categorize_none(self):
        assert categorize_score(0.49) == "none"
        assert categorize_score(0.0) == "none"

    def test_categorize_score_thresholds(self):
        """Verify boundary values across all four categories."""
        assert categorize_score(1.00) == "exact"
        assert categorize_score(0.95) == "exact"
        assert categorize_score(0.94) == "likely"
        assert categorize_score(0.75) == "likely"
        assert categorize_score(0.74) == "possible"
        assert categorize_score(0.50) == "possible"
        assert categorize_score(0.49) == "none"
        assert categorize_score(0.00) == "none"


class TestScoreContactMatch:
    def test_contact_exact_match(self):
        score = score_contact_match("John", "Smith", {"firstName": "John", "lastName": "Smith"})
        assert score >= 0.95

    def test_contact_partial_match(self):
        """Same name, different email — score is high (partial flagging is caller's job)."""
        score = score_contact_match("John", "Smith", {"firstName": "John", "lastName": "Smith", "email": "other@co.com"})
        assert score >= 0.95

    def test_contact_no_match(self):
        score = score_contact_match("Jane", "Doe", {"firstName": "Bob", "lastName": "Jones"})
        assert score < 0.50

    def test_contact_case_insensitive(self):
        score = score_contact_match("john", "smith", {"firstName": "JOHN", "lastName": "SMITH"})
        assert score >= 0.95

    def test_contact_missing_fields(self):
        score = score_contact_match("John", "Smith", {})
        assert score == 0.0


class TestSprint5E2E:
    def test_sprint5_e2e_company_duplicate_detection(self):
        """BNY vs Bank of New York Mellon → likely, confidence in [0.75, 0.95], not exact."""
        score = score_company_match("BNY", "Bank of New York Mellon")
        category = categorize_score(score)
        assert category == "likely"
        assert 0.75 <= score < 0.95

    def test_sprint5_e2e_exact_match_detection(self):
        """Identical names → exact category."""
        score = score_company_match("Acme Holdings Ltd", "Acme Holdings Ltd")
        assert categorize_score(score) == "exact"

    def test_sprint5_e2e_no_match(self):
        """Completely unrelated names → none category."""
        score = score_company_match("Globex", "Initech Solutions")
        assert categorize_score(score) == "none"
