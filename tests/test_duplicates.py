"""Tests for the pure match-check module: config, normalisers and profile (CR44, Sprint 42 T42.1 to T42.3).

All data is synthetic. The scorer (score_pair, rank, prior, band, to_percentage)
is covered elsewhere.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from bullhorn_mcp.duplicates import (
    MatchConfigError,
    _employers,
    default_match_config,
    employer_words,
    forename_relation,
    is_generic_mailbox,
    is_internal,
    linkedin_key,
    load_match_config,
    name_forms,
    name_key,
    normalize_email,
    normalize_employer,
    normalize_person_name,
    normalize_phone,
    phone_search_variants,
    profile_from_fields,
    profile_from_parse,
    profile_from_record,
    surname_relation,
)

EPOCH_2018_JAN_1 = 1514764800000  # 2018-01-01T00:00:00Z
EPOCH_2019_JAN_1 = 1546300800000  # 2019-01-01T00:00:00Z


@pytest.fixture(scope="module")
def config() -> dict:
    return load_match_config()


def _write(tmp_path, config: dict):
    path = tmp_path / "match_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# T42.1 config
# ---------------------------------------------------------------------------

class TestMatchConfig:
    def test_config_loads_from_package(self):
        cfg = load_match_config()
        assert cfg["bands"] == {"high": 98, "low": 20}
        assert cfg["default_country_code"] == "353"
        assert "thepanel.com" in cfg["internal_domains"]

    def test_default_match_config_matches_packaged_file(self):
        assert default_match_config() == load_match_config()

    def test_config_has_version(self):
        assert load_match_config()["version"] == "1"

    def test_valid_copy_loads_from_path(self, tmp_path, config):
        path = _write(tmp_path, config)
        assert load_match_config(path) == config

    def test_config_rejects_probability_out_of_range(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["forename"]["exact"]["m"] = 1.5
        with pytest.raises(MatchConfigError, match=re.escape("forename.exact.m")):
            load_match_config(_write(tmp_path, bad))

    @pytest.mark.parametrize(
        "path_parts, value",
        [
            (("surname", "exact", "u"), 0),
            (("identifiers", "email", "m"), 1),
            (("identifier_guard", "m"), 1.2),
            (("employer", "m"), -0.1),
            (("employer", "default_u"), 0),
        ],
    )
    def test_config_rejects_other_probabilities_naming_key(self, tmp_path, config, path_parts, value):
        bad = copy.deepcopy(config)
        node = bad
        for part in path_parts[:-1]:
            node = node[part]
        node[path_parts[-1]] = value
        with pytest.raises(MatchConfigError, match=re.escape(".".join(path_parts))):
            load_match_config(_write(tmp_path, bad))

    def test_config_rejects_unordered_thresholds(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["bands"]["low"] = 99
        bad["bands"]["high"] = 98
        with pytest.raises(MatchConfigError, match=re.escape("bands.low")):
            load_match_config(_write(tmp_path, bad))

    def test_config_rejects_equal_thresholds(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["bands"]["low"] = 98
        with pytest.raises(MatchConfigError, match="must be below 'bands.high'"):
            load_match_config(_write(tmp_path, bad))

    def test_config_rejects_missing_key(self, tmp_path, config):
        bad = copy.deepcopy(config)
        del bad["forename"]["exact"]
        with pytest.raises(MatchConfigError, match=re.escape("forename.exact")):
            load_match_config(_write(tmp_path, bad))

    @pytest.mark.parametrize("key", ["version", "internal_domains", "employer_suffixes", "forename_equivalents"])
    def test_config_rejects_missing_top_level_key(self, tmp_path, config, key):
        bad = copy.deepcopy(config)
        del bad[key]
        with pytest.raises(MatchConfigError, match=re.escape(f"'{key}'")):
            load_match_config(_write(tmp_path, bad))

    def test_name_only_cap_at_high_band_rejected(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["caps"]["name_only_percentage"] = bad["bands"]["high"]
        with pytest.raises(MatchConfigError, match=re.escape("caps.name_only_percentage")):
            load_match_config(_write(tmp_path, bad))

    def test_name_only_cap_above_high_band_rejected(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["caps"]["name_only_percentage"] = 99.5
        with pytest.raises(MatchConfigError, match=re.escape("caps.name_only_percentage")):
            load_match_config(_write(tmp_path, bad))

    def test_band_outside_percentage_range_rejected(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["bands"]["high"] = 120
        with pytest.raises(MatchConfigError, match=re.escape("bands.high")):
            load_match_config(_write(tmp_path, bad))

    def test_fallback_n_must_be_integer_above_one(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["population"]["fallback_n"] = 1
        with pytest.raises(MatchConfigError, match=re.escape("population.fallback_n")):
            load_match_config(_write(tmp_path, bad))

    def test_pi_numerator_must_be_below_n(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["population"]["pi_numerator"] = bad["population"]["fallback_n"]
        with pytest.raises(MatchConfigError, match=re.escape("population.pi_numerator")):
            load_match_config(_write(tmp_path, bad))

    def test_employer_rerun_must_not_exceed_pool_cap(self, tmp_path, config):
        """Review m1: a rerun threshold above the cap leaves totals between the two cut, not narrowed."""
        bad = copy.deepcopy(config)
        bad["retrieval"]["employer_rerun_over"] = bad["retrieval"]["pool_cap"] + 1
        with pytest.raises(MatchConfigError, match=re.escape("retrieval.employer_rerun_over")):
            load_match_config(_write(tmp_path, bad))

    def test_version_must_be_string(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["version"] = 1
        with pytest.raises(MatchConfigError, match="'version' must be a string"):
            load_match_config(_write(tmp_path, bad))

    @pytest.mark.parametrize(
        "path_parts, value",
        [
            (("forename", "exact"), {}),
            (("surname", "fuzzy"), {"m": 0.04}),
            (("identifiers", "phone"), {"u": 1e-09, "differ_points": -2}),
        ],
    )
    def test_level_without_m_and_u_rejected(self, tmp_path, config, path_parts, value):
        bad = copy.deepcopy(config)
        bad[path_parts[0]][path_parts[1]] = value
        with pytest.raises(MatchConfigError, match=re.escape(".".join(path_parts))):
            load_match_config(_write(tmp_path, bad))

    @pytest.mark.parametrize(
        "path_parts, value",
        [
            (("forename", "different", "points"), 6),
            (("surname", "different", "points"), "-5"),
            (("identifiers", "email", "differ_points"), 2),
            (("caps", "max_employers"), 0),
            (("caps", "max_employers"), 2.5),
            (("caps", "education_points"), -1),
            (("identifier_guard", "generic_min_holders"), "25"),
            (("employer", "overlap_bonus"), -1.5),
            (("employer", "title_bonus"), None),
            (("education", "school"), -1),
            (("education", "year_tolerance"), "1"),
            (("education", "year_tolerance"), True),
        ],
    )
    def test_bad_number_rejected_naming_key(self, tmp_path, config, path_parts, value):
        bad = copy.deepcopy(config)
        node = bad
        for part in path_parts[:-1]:
            node = node[part]
        node[path_parts[-1]] = value
        with pytest.raises(MatchConfigError, match=re.escape(".".join(path_parts))):
            load_match_config(_write(tmp_path, bad))

    def test_penalty_level_missing_points_rejected(self, tmp_path, config):
        bad = copy.deepcopy(config)
        bad["forename"]["different"] = {}
        with pytest.raises(MatchConfigError, match=re.escape("forename.different.points")):
            load_match_config(_write(tmp_path, bad))

    def test_invalid_json_raises_match_config_error(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(MatchConfigError, match="not valid JSON"):
            load_match_config(path)

    def test_non_object_json_rejected(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(MatchConfigError, match="must be a JSON object"):
            load_match_config(path)


# ---------------------------------------------------------------------------
# T42.2 normalisers
# ---------------------------------------------------------------------------

class TestNormalisers:
    # --- email ---------------------------------------------------------

    def test_normalize_email_trims_and_lowercases(self):
        assert normalize_email("  Aoife.Test@Example.COM ") == "aoife.test@example.com"

    @pytest.mark.parametrize("value", ["not-an-email", "@example.com", "aoife@", "", None, 42])
    def test_normalize_email_non_email_gives_none(self, value):
        assert normalize_email(value) is None

    def test_info_is_generic_mailbox(self, config):
        assert is_generic_mailbox("info@example.com", config) is True

    def test_cv_is_generic_mailbox_case_insensitive(self, config):
        assert is_generic_mailbox("CV@Example.com", config) is True

    def test_hyphenated_role_mailbox_is_generic(self, config):
        assert is_generic_mailbox("no-reply@example.com", config) is True

    def test_personal_mailbox_is_not_generic(self, config):
        assert is_generic_mailbox("aoife.test@example.com", config) is False

    def test_generic_prefix_must_match_whole_local_part(self, config):
        assert is_generic_mailbox("information@example.com", config) is False

    def test_thepanel_address_is_internal(self, config):
        assert is_internal("consultant@thepanel.com", config) is True

    def test_internal_is_case_insensitive(self, config):
        assert is_internal("Consultant@ThePanel.COM", config) is True

    def test_internal_subdomain_is_internal(self, config):
        assert is_internal("consultant@mail.thepanel.com", config) is True

    def test_lookalike_domain_is_not_internal(self, config):
        assert is_internal("someone@notthepanel.com", config) is False
        assert is_internal("someone@thepanel.com.example.org", config) is False

    # --- phone ---------------------------------------------------------

    def test_phone_national_with_spaces(self):
        assert normalize_phone("085 726 0864") == "+353857260864"

    def test_phone_dashes_dots_and_brackets_removed(self):
        assert normalize_phone("(085) 726-0864") == "+353857260864"
        assert normalize_phone("085.726.0864") == "+353857260864"

    def test_phone_bracketed_zero_removed(self):
        assert normalize_phone("+353 (0) 85 726 0864") == "+353857260864"

    def test_phone_00_prefix_becomes_plus(self):
        assert normalize_phone("00353 85 726 0864") == "+353857260864"

    def test_phone_leading_national_zero_becomes_country_code(self):
        assert normalize_phone("01 234 5678") == "+35312345678"

    def test_phone_unquoted_353_digits_get_plus(self):
        assert normalize_phone("353857260864") == "+353857260864"

    def test_phone_unquoted_353_as_integer(self):
        assert normalize_phone(353857260864) == "+353857260864"

    def test_phone_other_country_code_kept(self):
        assert normalize_phone("+44 7700 900123") == "+447700900123"

    def test_phone_trunk_zero_after_country_code_dropped(self):
        assert normalize_phone("+353 0 85 726 0864") == "+353857260864"

    def test_phone_under_seven_digits_gives_none(self):
        assert normalize_phone("123456") is None
        assert normalize_phone("ext 4321") is None

    def test_phone_exactly_seven_digits_kept(self):
        assert normalize_phone("0123456") == "+3531234" + "56"

    @pytest.mark.parametrize("value", [None, [], {}, True, 12.5])
    def test_phone_non_string_gives_none(self, value):
        assert normalize_phone(value) is None

    def test_phone_custom_country_code(self):
        assert normalize_phone("07700 900123", country_code="44") == "+447700900123"

    def test_phone_variants_for_national_number(self):
        assert phone_search_variants("085 726 0864") == ["+353857260864", "0857260864", "353857260864"]

    def test_phone_variants_for_international_form_match_national(self):
        assert phone_search_variants("+353857260864") == phone_search_variants("0857260864")

    def test_phone_variants_for_foreign_number(self):
        assert phone_search_variants("+44 7700 900123") == ["+447700900123", "447700900123"]

    def test_short_number_ignored(self):
        assert phone_search_variants("12345") == []
        assert phone_search_variants(None) == []

    # --- linkedin ------------------------------------------------------

    def test_linkedin_in_slug(self):
        assert linkedin_key("https://www.linkedin.com/in/aoife-test") == "in/aoife-test"

    def test_pub_linkedin_url_normalised(self):
        assert linkedin_key("ie.linkedin.com/pub/aoife-test/11/140/8b0") == "pub/aoife-test/11/140/8b0"

    def test_linkedin_country_subdomain(self):
        assert linkedin_key("https://ie.linkedin.com/in/aoife-test") == "in/aoife-test"

    def test_linkedin_mixed_case(self):
        assert linkedin_key("HTTPS://WWW.LinkedIn.com/IN/Aoife-Test") == "in/aoife-test"

    def test_linkedin_without_scheme(self):
        assert linkedin_key("linkedin.com/in/aoife-test") == "in/aoife-test"

    def test_linkedin_trailing_slash(self):
        assert linkedin_key("https://www.linkedin.com/in/aoife-test/") == "in/aoife-test"

    def test_linkedin_query_string_ignored(self):
        assert linkedin_key("https://www.linkedin.com/in/aoife-test?trk=public_profile&x=1") == "in/aoife-test"

    def test_linkedin_url_encoded_characters_decoded(self):
        assert linkedin_key("https://www.linkedin.com/in/aoife%2Dtest") == "in/aoife-test"
        assert linkedin_key("https://www.linkedin.com/in/s%C3%A9an-test") == "in/séan-test"

    def test_linkedin_variants_give_same_key(self):
        keys = {
            linkedin_key("https://www.linkedin.com/in/aoife-test/"),
            linkedin_key("ie.linkedin.com/in/Aoife-Test?trk=x"),
            linkedin_key("linkedin.com/in/aoife-test"),
        }
        assert keys == {"in/aoife-test"}

    def test_non_linkedin_url_gives_none(self):
        assert linkedin_key("https://example.com/in/aoife-test") is None
        assert linkedin_key("https://notlinkedin.com/in/aoife-test") is None

    def test_linkedin_root_gives_none(self):
        assert linkedin_key("https://www.linkedin.com") is None
        assert linkedin_key("https://www.linkedin.com/") is None

    def test_linkedin_company_page_gives_none(self):
        assert linkedin_key("https://www.linkedin.com/company/acme-widgets") is None

    @pytest.mark.parametrize("value", [None, "", "   ", 42])
    def test_linkedin_empty_or_non_string_gives_none(self, value):
        assert linkedin_key(value) is None

    # --- employer ------------------------------------------------------

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Acme Widgets Ltd", "acme widgets"),
            ("Acme Widgets Limited", "acme widgets"),
            ("Acme plc", "acme"),
            ("Acme DAC", "acme"),
            ("Acme Ireland Ltd", "acme"),
            ("Acme Group", "acme"),
        ],
    )
    def test_employer_suffixes_stripped(self, config, name, expected):
        assert normalize_employer(name, config) == expected

    def test_employer_leading_the_removed(self, config):
        assert normalize_employer("The Acme Group", config) == "acme"

    def test_employer_ampersand_becomes_and(self, config):
        assert normalize_employer("Smith & Jones Ltd", config) == "smith and jones"

    def test_employer_punctuation_removed(self, config):
        assert normalize_employer("A.B.C. (Dublin) Ltd.", config) == "a b c dublin"

    def test_employer_apostrophe_joined(self, config):
        assert normalize_employer("O'Neill & Sons", config) == "oneill and sons"

    def test_bank_of_ireland_not_stripped(self, config):
        assert normalize_employer("Bank of Ireland", config) == "bank of ireland"

    def test_bank_of_ireland_group_plc_keeps_ireland(self, config):
        assert normalize_employer("Bank of Ireland Group plc", config) == "bank of ireland"

    def test_employer_never_stripped_to_nothing(self, config):
        assert normalize_employer("Ireland Ltd", config) == "ireland"
        assert normalize_employer("Ltd", config) == "ltd"
        assert normalize_employer("The", config) == "the"

    @pytest.mark.parametrize("value", [None, "", "   ", "...", 7])
    def test_employer_empty_or_non_string_gives_none(self, config, value):
        assert normalize_employer(value, config) is None

    def test_employer_words_drop_stopwords_and_suffixes(self, config):
        assert employer_words("The Bank of Ireland Group", config) == ["bank", "ireland"]

    def test_employer_words_are_distinct(self, config):
        assert employer_words("Acme Acme Ltd", config) == ["acme"]

    def test_employer_words_empty_for_missing(self, config):
        assert employer_words(None, config) == []

    # --- person names --------------------------------------------------

    def test_person_name_folded_and_collapsed(self):
        assert normalize_person_name("  Seán   Ó Briain ") == "sean o briain"

    def test_person_name_keeps_apostrophe_and_hyphen(self):
        assert normalize_person_name("O'Brien-Walsh") == "o'brien-walsh"

    def test_person_name_curly_apostrophe_straightened(self):
        assert normalize_person_name("O’Brien") == "o'brien"

    @pytest.mark.parametrize("value", [None, "", "   ", 5])
    def test_person_name_empty_gives_none(self, value):
        assert normalize_person_name(value) is None

    def test_name_forms_both_apostrophe_forms(self):
        assert name_forms("O'Brien") == ["o'brien", "obrien"]

    def test_name_forms_curly_apostrophe(self):
        assert name_forms("O’Brien") == ["o'brien", "obrien"]

    def test_name_forms_single_when_no_apostrophe(self):
        assert name_forms("Murphy") == ["murphy"]

    def test_name_forms_empty(self):
        assert name_forms(None) == []

    def test_name_key_drops_apostrophes_hyphens_dots_spaces(self):
        assert name_key("O'Brien") == "obrien"
        assert name_key("Mary-Kate") == "marykate"
        assert name_key("J. R.") == "jr"
        assert name_key("Ó Briain") == "obriain"

    def test_name_key_empty_gives_none(self):
        assert name_key("  ") is None
        assert name_key("...") is None
        assert name_key(None) is None

    def test_fada_folds(self):
        assert name_key("Pádraig") == name_key("Padraig") == "padraig"
        assert name_key("Seán") == name_key("Sean") == "sean"

    # --- forename relation --------------------------------------------

    def test_forename_exact(self, config):
        assert forename_relation("Aoife", "aoife", config) == "exact"

    def test_forename_exact_across_fada(self, config):
        assert forename_relation("Seán", "Sean", config) == "exact"

    @pytest.mark.parametrize(
        "a, b",
        [("Seán", "John"), ("Liam", "William"), ("Bill", "William"), ("Siobhán", "Joan"), ("Pat", "Patrick")],
    )
    def test_forename_equivalent(self, config, a, b):
        assert forename_relation(a, b, config) == "equivalent"
        assert forename_relation(b, a, config) == "equivalent"

    def test_forename_initial(self, config):
        assert forename_relation("A.", "Aoife", config) == "initial"
        assert forename_relation("Aoife", "A", config) == "initial"

    def test_forename_wrong_initial_is_different(self, config):
        assert forename_relation("B", "Aoife", config) == "different"

    def test_forename_typo(self, config):
        assert forename_relation("Aoife", "Aoifa", config) == "typo"

    def test_forename_adjacent_swap_is_typo(self, config):
        assert forename_relation("Brian", "Brain", config) == "typo"

    def test_forename_short_names_one_edit_apart_are_different(self, config):
        assert forename_relation("Tom", "Tim", config) == "different"

    def test_forename_different(self, config):
        assert forename_relation("Aoife", "Niamh", config) == "different"

    @pytest.mark.parametrize("a, b", [(None, "Aoife"), ("Aoife", None), ("", "Aoife"), ("Aoife", "  "), (None, None)])
    def test_forename_missing(self, config, a, b):
        assert forename_relation(a, b, config) == "missing"

    def test_forename_compound_matches_first_name(self, config):
        assert forename_relation("Mary Kate", "Mary", config) == "exact"
        assert forename_relation("Mary-Kate", "Mary", config) == "exact"

    def test_forename_compound_equivalent_on_first_token(self, config):
        assert forename_relation("Mary Kate", "Maire", config) == "equivalent"

    # --- surname relation ---------------------------------------------

    def test_surname_exact(self):
        assert surname_relation("Murphy", "MURPHY") == "exact"

    def test_surname_apostrophe_forms_are_exact(self):
        assert surname_relation("O'Brien", "OBrien") == "exact"
        assert surname_relation("O Brien", "O'Brien") == "exact"

    def test_surname_fada_is_exact(self):
        assert surname_relation("Ó Briain", "O Briain") == "exact"

    def test_surname_one_edit_is_fuzzy(self):
        assert surname_relation("Murphy", "Murphey") == "fuzzy"
        assert surname_relation("Smith", "Smyth") == "fuzzy"

    def test_surname_one_edit_needs_four_letters(self):
        assert surname_relation("Lee", "Lea") == "different"

    def test_mc_mac_is_fuzzy_surname(self):
        assert surname_relation("McCarthy", "MacCarthy") == "fuzzy"
        assert surname_relation("MacCarthy", "McCarthy") == "fuzzy"

    def test_dropped_o_prefix_is_fuzzy(self):
        assert surname_relation("O'Brien", "Brien") == "fuzzy"
        assert surname_relation("Brien", "O'Brien") == "fuzzy"

    def test_double_barrelled_shared_part_fuzzy(self):
        assert surname_relation("Murphy-Walsh", "Walsh-Byrne") == "fuzzy"

    def test_double_barrelled_single_part_is_fuzzy(self):
        # A married name that adds a surname to the maiden name is the common case.
        assert surname_relation("Smith-Jones", "Jones") == "fuzzy"
        assert surname_relation("Jones", "Smith-Jones") == "fuzzy"

    def test_surname_different(self):
        assert surname_relation("Murphy", "Walsh") == "different"

    @pytest.mark.parametrize("a, b", [(None, "Murphy"), ("Murphy", ""), ("  ", "Murphy")])
    def test_surname_missing(self, a, b):
        assert surname_relation(a, b) == "missing"


# ---------------------------------------------------------------------------
# T42.3 profile
# ---------------------------------------------------------------------------

class TestProfile:
    def test_profile_from_fields(self):
        fields = {
            "id": 4242,
            "firstName": " Aoife ",
            "lastName": "Testova",
            "email": "aoife@example.com",
            "mobile": "085 726 0864",
            "companyURL": "https://www.linkedin.com/in/aoife-testova",
            "companyName": "Acme Widgets Ltd",
        }
        work = [{"companyName": "Globex", "title": "Analyst", "startDate": EPOCH_2018_JAN_1, "endDate": EPOCH_2019_JAN_1}]
        edu = [{"school": "Testford University", "degree": "BSc", "graduationDate": EPOCH_2018_JAN_1}]
        profile = profile_from_fields(fields, work, edu)
        assert profile.candidate_id == 4242
        assert profile.first_name == "Aoife"
        assert profile.last_name == "Testova"
        assert profile.display_name == "Aoife Testova"
        assert profile.emails == ["aoife@example.com"]
        assert profile.phones == ["085 726 0864"]
        assert profile.linkedin_url == "https://www.linkedin.com/in/aoife-testova"
        assert profile.current_company == "Acme Widgets Ltd"
        assert [(w.company, w.title, w.start_year, w.end_year) for w in profile.work_history] == [
            ("Globex", "Analyst", 2018, 2019)
        ]
        assert [(e.school, e.degree, e.year) for e in profile.education] == [("Testford University", "BSc", 2018)]

    def test_profile_from_fields_empty_inputs(self):
        profile = profile_from_fields(None)
        assert profile.first_name is None
        assert profile.emails == []
        assert profile.phones == []
        assert profile.work_history == []
        assert profile.education == []
        assert profile.candidate_id is None
        assert profile.display_name == ""

    def test_blank_strings_become_none(self):
        profile = profile_from_fields({"firstName": "  ", "lastName": "", "email": "  "})
        assert profile.first_name is None
        assert profile.last_name is None
        assert profile.emails == []

    def test_non_integer_id_ignored(self):
        assert profile_from_fields({"id": "4242"}).candidate_id is None
        assert profile_from_fields({"id": True}).candidate_id is None

    def test_profile_from_parse_applies_corrections(self):
        parsed = {
            "candidate": {"firstName": "Aoife", "lastName": "Testova", "email": "parsed@example.com"},
            "candidateWorkHistory": [{"companyName": "Parsed Co", "title": "Clerk"}],
            "candidateEducation": [{"school": "Parsed College", "degree": "BA"}],
        }
        corrections = {
            "fields_override": {"lastName": "Testerson", "email": "fixed@example.com"},
            "work_history": [{"companyName": "Globex", "title": "Analyst"}],
            "education": [{"school": "Testford University", "degree": "BSc"}],
        }
        profile = profile_from_parse(parsed, corrections)
        assert profile.first_name == "Aoife"
        assert profile.last_name == "Testerson"
        assert profile.emails == ["fixed@example.com"]
        assert [w.company for w in profile.work_history] == ["Globex"]
        assert [e.school for e in profile.education] == ["Testford University"]

    def test_profile_from_parse_omitted_lists_use_the_parse(self):
        parsed = {
            "candidate": {"firstName": "Aoife", "lastName": "Testova"},
            "candidateWorkHistory": [{"companyName": "Parsed Co", "title": "Clerk"}],
            "candidateEducation": [{"school": "Parsed College", "degree": "BA"}],
        }
        profile = profile_from_parse(parsed, {"fields_override": {"firstName": "Aoibhinn"}})
        assert profile.first_name == "Aoibhinn"
        assert [w.company for w in profile.work_history] == ["Parsed Co"]
        assert [e.school for e in profile.education] == ["Parsed College"]

    def test_profile_from_parse_without_corrections(self):
        parsed = {"candidate": {"firstName": "Aoife"}, "candidateWorkHistory": [{"companyName": "Parsed Co"}]}
        for corrections in (None, {}):
            profile = profile_from_parse(parsed, corrections)
            assert profile.first_name == "Aoife"
            assert [w.company for w in profile.work_history] == ["Parsed Co"]
            assert profile.education == []

    def test_profile_from_parse_empty_correction_list_replaces_parse(self):
        parsed = {"candidate": {}, "candidateWorkHistory": [{"companyName": "Parsed Co"}]}
        profile = profile_from_parse(parsed, {"work_history": []})
        assert profile.work_history == []

    def test_profile_from_parse_does_not_mutate_input(self):
        parsed = {"candidate": {"firstName": "Aoife"}}
        profile_from_parse(parsed, {"fields_override": {"firstName": "Niamh"}})
        assert parsed == {"candidate": {"firstName": "Aoife"}}

    def test_profile_from_parse_handles_empty_parse(self):
        profile = profile_from_parse({}, None)
        assert profile.first_name is None
        assert profile.work_history == []

    def test_profile_from_record_collects_all_email_and_phone_fields(self):
        candidate = {
            "id": 99,
            "firstName": "Niamh",
            "lastName": "Testington",
            "email": "one@example.com",
            "email2": "two@example.com",
            "email3": "three@example.com",
            "mobile": "085 111 2222",
            "phone": "01 234 5678",
            "workPhone": "01 876 5432",
            "phone2": "086 333 4444",
            "phone3": "087 555 6666",
        }
        profile = profile_from_record(candidate, [], [])
        assert profile.candidate_id == 99
        assert profile.emails == ["one@example.com", "two@example.com", "three@example.com"]
        assert profile.phones == [
            "085 111 2222",
            "01 234 5678",
            "01 876 5432",
            "086 333 4444",
            "087 555 6666",
        ]

    def test_profile_from_record_skips_missing_contact_fields(self):
        profile = profile_from_record({"email3": "three@example.com", "phone2": "086 333 4444"}, None, None)
        assert profile.emails == ["three@example.com"]
        assert profile.phones == ["086 333 4444"]

    def test_soft_deleted_rows_skipped(self):
        work = [
            {"companyName": "Live Co", "isDeleted": False},
            {"companyName": "Deleted Co", "isDeleted": True},
        ]
        edu = [
            {"school": "Live School", "isDeleted": False},
            {"school": "Deleted School", "isDeleted": True},
        ]
        profile = profile_from_record({"firstName": "Niamh"}, work, edu)
        assert [w.company for w in profile.work_history] == ["Live Co"]
        assert [e.school for e in profile.education] == ["Live School"]

    def test_non_dict_rows_skipped(self):
        profile = profile_from_fields({}, ["junk", None, {"companyName": "Live Co"}], [None, 5])
        assert [w.company for w in profile.work_history] == ["Live Co"]
        assert profile.education == []

    def test_epoch_ms_dates_converted_to_utc_year(self):
        profile = profile_from_fields(
            {},
            [{"companyName": "Acme", "startDate": EPOCH_2018_JAN_1, "endDate": EPOCH_2019_JAN_1}],
        )
        assert profile.work_history[0].start_year == 2018
        assert profile.work_history[0].end_year == 2019

    def test_year_only_date_stored_on_first_or_second_january(self):
        # Year-only dates are stored as 1 or 2 January UTC (P8); the year must survive.
        jan_2 = EPOCH_2018_JAN_1 + 86_400_000
        profile = profile_from_fields(
            {},
            [
                {"companyName": "Acme", "startDate": EPOCH_2018_JAN_1},
                {"companyName": "Globex", "startDate": jan_2},
            ],
        )
        assert [w.start_year for w in profile.work_history] == [2018, 2018]

    def test_last_instant_of_year_stays_in_that_year(self):
        profile = profile_from_fields({}, [{"companyName": "Acme", "startDate": EPOCH_2019_JAN_1 - 1}])
        assert profile.work_history[0].start_year == 2018

    def test_string_dates_give_year(self):
        profile = profile_from_fields(
            {},
            [{"companyName": "Acme", "startDate": "2016-03-01", "endDate": str(EPOCH_2018_JAN_1)}],
        )
        assert profile.work_history[0].start_year == 2016
        assert profile.work_history[0].end_year == 2018

    def test_missing_and_invalid_dates_give_none(self):
        profile = profile_from_fields({}, [{"companyName": "Acme", "startDate": None, "endDate": True}])
        assert profile.work_history[0].start_year is None
        assert profile.work_history[0].end_year is None

    def test_certification_used_as_degree_when_degree_empty(self):
        edu = [{"school": "Testford Institute", "degree": "", "certification": "ACCA"}]
        profile = profile_from_fields({}, [], edu)
        assert profile.education[0].degree == "ACCA"

    def test_degree_preferred_over_certification(self):
        edu = [{"school": "Testford Institute", "degree": "BSc", "certification": "ACCA"}]
        assert profile_from_fields({}, [], edu).education[0].degree == "BSc"

    def test_certification_alone_keeps_the_row(self):
        profile = profile_from_fields({}, [], [{"certification": "CPA"}])
        assert [(e.school, e.degree) for e in profile.education] == [(None, "CPA")]

    def test_education_year_falls_back_to_end_date(self):
        edu = [{"school": "Testford", "endDate": EPOCH_2019_JAN_1}]
        assert profile_from_fields({}, [], edu).education[0].year == 2019

    def test_education_graduation_date_preferred_over_end_date(self):
        edu = [{"school": "Testford", "graduationDate": EPOCH_2018_JAN_1, "endDate": EPOCH_2019_JAN_1}]
        assert profile_from_fields({}, [], edu).education[0].year == 2018

    def test_education_row_without_school_or_degree_dropped(self):
        profile = profile_from_fields({}, [], [{"graduationDate": EPOCH_2018_JAN_1}, {"school": "Testford"}])
        assert [e.school for e in profile.education] == ["Testford"]

    def test_work_row_with_neither_company_nor_title_dropped(self):
        work = [
            {"startDate": EPOCH_2018_JAN_1},
            {"companyName": "  ", "title": ""},
            {"companyName": "Acme"},
        ]
        profile = profile_from_fields({}, work)
        assert [w.company for w in profile.work_history] == ["Acme"]

    def test_work_row_with_title_only_is_kept(self):
        profile = profile_from_fields({}, [{"title": "Analyst at Globex"}])
        assert [(w.company, w.title) for w in profile.work_history] == [(None, "Analyst at Globex")]

    def test_profile_echo_is_normalised(self, config):
        fields = {
            "firstName": "Seán",
            "lastName": "  Ó Briain ",
            "email": "Sean@Example.COM",
            "email2": "sean@example.com",
            "mobile": "085 726 0864",
            "phone": "+353 (0) 85 726 0864",
            "workPhone": "123",
            "companyURL": "ie.linkedin.com/in/Sean-Test/",
        }
        work = [{"companyName": "The Acme Widgets Ltd", "title": "Analyst"}]
        edu = [{"school": "The University of Testford Ltd", "degree": "B.Sc. (Hons)", "graduationDate": EPOCH_2018_JAN_1}]
        echo = profile_from_fields(fields, work, edu).to_echo(config)
        assert echo == {
            "first_name": "sean",
            "last_name": "o briain",
            "emails": ["sean@example.com"],
            "phones": ["+353857260864"],
            "linkedin": "in/sean-test",
            "employers": ["acme widgets"],
            "education": [{"school": "university of testford", "degree": "b sc hons", "year": 2018}],
        }

    def test_profile_echo_defaults_to_packaged_config(self):
        echo = profile_from_fields({"mobile": "085 726 0864"}).to_echo()
        assert echo["phones"] == ["+353857260864"]

    def test_profile_echo_of_empty_profile(self, config):
        assert profile_from_fields(None).to_echo(config) == {
            "first_name": None,
            "last_name": None,
            "emails": [],
            "phones": [],
            "linkedin": None,
            "employers": [],
            "education": [],
        }

    def test_current_company_is_extra_undated_employer(self, config):
        fields = {"companyName": "Globex Ltd"}
        work = [{"companyName": "Acme Ltd", "title": "Analyst", "startDate": EPOCH_2018_JAN_1}]
        profile = profile_from_fields(fields, work)
        assert profile.to_echo(config)["employers"] == ["acme", "globex"]
        employers = _employers(profile, config)
        assert employers["globex"].spans == []
        assert employers["globex"].titles == []
        assert employers["acme"].spans == [(2018, None)]

    def test_current_company_not_duplicated_when_in_work_history(self, config):
        fields = {"companyName": "Acme Limited"}
        work = [{"companyName": "ACME Ltd", "startDate": EPOCH_2018_JAN_1}]
        profile = profile_from_fields(fields, work)
        assert profile.to_echo(config)["employers"] == ["acme"]
        assert _employers(profile, config)["acme"].spans == [(2018, None)]

    def test_key_variants_of_one_employer_merged_under_shorter_key(self, config):
        work = [
            {"companyName": "Corporate with Quillon Brewer", "title": "Analyst", "startDate": EPOCH_2018_JAN_1},
            {"companyName": "Quillon Brewer Ltd", "title": "Manager", "startDate": EPOCH_2019_JAN_1},
        ]
        profile = profile_from_fields({"companyName": "Glenmoor Foods"}, work)
        employers = _employers(profile, config)
        assert list(employers) == ["quillon brewer", "glenmoor foods"]
        assert employers["quillon brewer"].display == "Quillon Brewer Ltd"
        assert employers["quillon brewer"].spans == [(2018, None), (2019, None)]
        assert employers["quillon brewer"].titles == ["Analyst", "Manager"]

    def test_current_company_variant_merged_into_work_history(self, config):
        work = [{"companyName": "Quillon Brewer", "startDate": EPOCH_2018_JAN_1}]
        profile = profile_from_fields({"companyName": "Corporate with Quillon Brewer"}, work)
        assert profile.to_echo(config)["employers"] == ["quillon brewer"]
        assert _employers(profile, config)["quillon brewer"].spans == [(2018, None)]

    def test_repeated_employer_rows_counted_once(self, config):
        work = [
            {"companyName": "Acme Ltd", "title": "Analyst", "startDate": EPOCH_2018_JAN_1},
            {"companyName": "Acme", "title": "Senior Analyst", "startDate": EPOCH_2019_JAN_1},
        ]
        profile = profile_from_fields({}, work)
        assert profile.to_echo(config)["employers"] == ["acme"]
        assert _employers(profile, config)["acme"].titles == ["Analyst", "Senior Analyst"]
