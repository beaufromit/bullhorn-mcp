"""CR49 Sprint 45 tests: JobOrder startDate is stored the way the Bullhorn UI stores it.

The UI stores a picked date as midnight America/New_York (04:00 UTC in summer, 05:00 UTC
in winter). create_job and update_job normalise startDate to that; "today" and the calendar
day of an epoch value are read in Europe/Dublin. Expected epochs are hard-coded literals,
checked independently of the implementation.
"""

import json
from datetime import datetime, timezone
from unittest.mock import Mock, PropertyMock, patch

import httpx
import pytest
import respx

from bullhorn_mcp import server
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient
from bullhorn_mcp.metadata import BullhornMetadata

# Literal epoch-ms values (midnight New York unless noted).
NOV_20_2026 = 1795150800000        # 20 Nov 2026 05:00 UTC (EST)
NOV_20_2026_MIDNIGHT_UTC = 1795132800000   # job 51533's bad value
NOV_20_2026_DUBLIN_0030 = 1795134600000    # 00:30 UTC = 00:30 Dublin; NY still 19 Nov
NOV_21_2026 = 1795237200000
FEB_01_2027 = 1801458000000
MAR_01_2027 = 1803877200000
JUL_15_2026 = 1784088000000        # 04:00 UTC (EDT)
JUL_15_2026_MIDNIGHT_UTC = 1784073600000
JUL_15_2026_MIDNIGHT_DUBLIN = 1784070000000  # 14 Jul 23:00 UTC = 00:00 IST on 15 Jul
OCT_28_2026 = 1793160000000        # EU back (25 Oct), US not yet (1 Nov): NY EDT, Dublin GMT
OCT_28_2026_MIDNIGHT_UTC = 1793145600000
MAR_17_2027 = 1805256000000        # US forward (14 Mar), EU not yet (28 Mar): NY EDT, Dublin GMT
MAR_17_2027_MIDNIGHT_UTC = 1805241600000
DEC_25_2026 = 1798174800000


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- pure helper


class TestJobStartDateMs:
    def test_time_zones_load(self):
        assert server._BULLHORN_DATE_TZ.key == "America/New_York"
        assert server._CONSULTANT_TZ.key == "Europe/Dublin"

    def test_none_and_blank_default_to_today_dublin(self):
        now = _utc(2026, 11, 20, 12, 0)
        assert server._job_start_date_ms(None, now=now) == NOV_20_2026
        assert server._job_start_date_ms("", now=now) == NOV_20_2026

    def test_just_after_midnight_dublin_uses_dublin_date(self):
        # 00:30 UTC on 20 Nov = 00:30 Dublin, but 19:30 on 19 Nov in New York.
        now = _utc(2026, 11, 20, 0, 30)
        assert server._job_start_date_ms(None, now=now) == NOV_20_2026
        assert server._job_start_date_ms("", now=now) == NOV_20_2026

    def test_just_after_midnight_dublin_summer_uses_dublin_date(self):
        # 23:30 UTC on 14 Jul = 00:30 IST on 15 Jul.
        now = _utc(2026, 7, 14, 23, 30)
        assert server._job_start_date_ms(None, now=now) == JUL_15_2026

    def test_iso_date_winter_is_0500_utc(self):
        assert server._job_start_date_ms("2026-11-20") == NOV_20_2026
        assert server._job_start_date_ms("2027-02-01") == FEB_01_2027

    def test_iso_date_summer_is_0400_utc(self):
        assert server._job_start_date_ms("2026-07-15") == JUL_15_2026

    def test_gap_weeks(self):
        # Between the EU change (25 Oct 2026) and the US change (1 Nov 2026).
        assert server._job_start_date_ms("2026-10-28") == OCT_28_2026
        assert server._job_start_date_ms(OCT_28_2026) == OCT_28_2026        # 04:00 UTC reads as 28 Oct
        assert server._job_start_date_ms(OCT_28_2026_MIDNIGHT_UTC) == OCT_28_2026
        # Between the US change (14 Mar 2027) and the EU change (28 Mar 2027).
        assert server._job_start_date_ms("2027-03-17") == MAR_17_2027
        assert server._job_start_date_ms(MAR_17_2027) == MAR_17_2027
        assert server._job_start_date_ms(MAR_17_2027_MIDNIGHT_UTC) == MAR_17_2027

    def test_midnight_utc_epoch_is_corrected(self):
        assert server._job_start_date_ms(NOV_20_2026_MIDNIGHT_UTC) == NOV_20_2026
        assert server._job_start_date_ms(JUL_15_2026_MIDNIGHT_UTC) == JUL_15_2026

    def test_midnight_dublin_summer_epoch_keeps_date(self):
        # 23:00 UTC the day before is midnight in Dublin; the date is 15 Jul, not 14 Jul.
        assert server._job_start_date_ms(JUL_15_2026_MIDNIGHT_DUBLIN) == JUL_15_2026

    def test_dublin_0030_epoch_keeps_dublin_date(self):
        assert server._job_start_date_ms(NOV_20_2026_DUBLIN_0030) == NOV_20_2026

    @pytest.mark.parametrize("value, expected", [
        (NOV_20_2026, NOV_20_2026),
        (JUL_15_2026, JUL_15_2026),
        (float(NOV_20_2026), NOV_20_2026),
        (float(JUL_15_2026), JUL_15_2026),
    ])
    def test_already_correct_value_is_unchanged(self, value, expected):
        assert server._job_start_date_ms(value) == expected

    def test_result_is_int(self):
        assert type(server._job_start_date_ms(float(NOV_20_2026))) is int

    @pytest.mark.parametrize("value", [
        "2026-11-20T00:00:00Z",
        "2026-11-20T00:00:00",
        "ASAP",
        "2026-02-30",
        "20261120",
        " 2026-11-20",
        "2026-11-20 ",
        "2026-11-20\n",
        "2026-1-5",
        True,
        False,
        {"a": 1},
        ["2026-11-20"],
    ])
    def test_rejects_datetime_string_bool_and_junk(self, value):
        with pytest.raises(ValueError):
            server._job_start_date_ms(value)

    @pytest.mark.parametrize("value", [
        float("nan"),
        float("inf"),
        float("-inf"),
        1e30,
        -1e30,
        10**25,
    ])
    def test_rejects_nan_inf_and_out_of_range_numbers(self, value):
        with pytest.raises(ValueError):
            server._job_start_date_ms(value)

    def test_default_now_uses_now_utc_seam(self):
        with patch("bullhorn_mcp.server._now_utc", return_value=_utc(2026, 11, 20, 0, 30)) as seam:
            assert server._job_start_date_ms(None) == NOV_20_2026
        seam.assert_called_once()

    def test_explicit_value_does_not_read_the_clock(self):
        with patch("bullhorn_mcp.server._now_utc") as seam:
            server._job_start_date_ms("2026-11-20")
            server._job_start_date_ms(NOV_20_2026)
        seam.assert_not_called()

    def test_now_utc_is_timezone_aware_utc(self):
        now = server._now_utc()
        assert now.tzinfo is not None and now.utcoffset().total_seconds() == 0


# --------------------------------------------------------------------------- tool level


@pytest.fixture(autouse=True)
def _clean_joborder_env(monkeypatch):
    monkeypatch.delenv("BULLHORN_JOBORDER_DEFAULTS", raising=False)
    monkeypatch.delenv("BULLHORN_JOBORDER_REQUIRED", raising=False)


@pytest.fixture
def mock_auth(mock_session):
    auth = Mock(spec=BullhornAuth)
    type(auth).session = PropertyMock(return_value=mock_session)
    return auth


class _Env:
    """Real client + metadata over respx; records the PUT (create) and POST (update) bodies."""

    def __init__(self, mock_auth, mock_session):
        self.base = mock_session.rest_url
        self.client = BullhornClient(mock_auth)
        self.metadata = BullhornMetadata(self.client)
        self.bodies = []
        self.requests = []

    def _record(self, request, status_body):
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json=status_body)

    def run(self, tool, *args, **kwargs):
        meta_fields = [
            {"name": "startDate", "label": "Start Date", "type": "TIMESTAMP"},
            {"name": "title", "label": "Job Title", "type": "STRING"},
        ]
        with respx.mock:
            meta = respx.get(f"{self.base}/meta/JobOrder").mock(
                return_value=httpx.Response(200, json={"entity": "JobOrder", "fields": meta_fields})
            )
            put = respx.put(f"{self.base}/entity/JobOrder").mock(
                side_effect=lambda r: self._record(r, {"changedEntityId": 1, "changeType": "INSERT"})
            )
            post = respx.post(f"{self.base}/entity/JobOrder/51533").mock(
                side_effect=lambda r: self._record(r, {"changedEntityId": 51533, "changeType": "UPDATE"})
            )
            respx.get(f"{self.base}/entity/JobOrder/1").mock(
                return_value=httpx.Response(200, json={"data": {"id": 1}})
            )
            respx.get(f"{self.base}/entity/JobOrder/51533").mock(
                return_value=httpx.Response(200, json={"data": {"id": 51533}})
            )
            with patch.object(server, "get_client", return_value=self.client), \
                 patch.object(server, "get_metadata", return_value=self.metadata), \
                 patch.object(server, "resolve_caller", return_value={"id": 42}):
                result = tool(*args, **kwargs)
            self.put_calls = put.call_count
            self.post_calls = post.call_count
            self.meta_calls = meta.call_count
        return json.loads(result)

    @property
    def body(self):
        assert len(self.bodies) == 1, self.bodies
        return self.bodies[0]


@pytest.fixture
def env(mock_auth, mock_session):
    return _Env(mock_auth, mock_session)


def _create(env, fields=None, now=_utc(2026, 11, 20, 12, 0)):
    with patch("bullhorn_mcp.server._now_utc", return_value=now):
        return env.run(
            server.create_job,
            clientCorporation={"id": 1},
            clientContact={"id": 2},
            title="Engineer",
            fields=fields,
        )


class TestCreateJobStartDate:
    def test_create_job_omitted_start_date_sends_today(self, env):
        data = _create(env)

        assert data["changedEntityId"] == 1
        assert env.body["startDate"] == NOV_20_2026
        assert env.body["owner"] == {"id": 42}

    def test_create_job_blank_or_null_start_date_sends_today(self, env):
        _create(env, fields={"startDate": ""})
        _create(env, fields={"startDate": None})

        assert [b["startDate"] for b in env.bodies] == [NOV_20_2026, NOV_20_2026]

    def test_create_job_iso_start_date_is_normalised(self, env):
        _create(env, fields={"startDate": "2026-07-15"})

        assert env.body["startDate"] == JUL_15_2026

    def test_create_job_epoch_start_date_is_corrected(self, env):
        _create(env, fields={"startDate": NOV_20_2026_MIDNIGHT_UTC})

        assert env.body["startDate"] == NOV_20_2026

    def test_create_job_label_start_date_is_normalised(self, env):
        _create(env, fields={"Start Date": "2027-02-01"})

        assert env.body["startDate"] == FEB_01_2027
        assert "Start Date" not in env.body

    def test_create_job_env_default_start_date_used_and_caller_wins(self, env, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_DEFAULTS", '{"startDate": "2027-03-01"}')

        _create(env)
        _create(env, fields={"startDate": "2027-02-01"})

        assert [b["startDate"] for b in env.bodies] == [MAR_01_2027, FEB_01_2027]

    def test_create_job_env_default_label_start_date_used(self, env, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_DEFAULTS", '{"Start Date": "2027-03-01"}')

        _create(env)

        assert env.body["startDate"] == MAR_01_2027

    def test_create_job_invalid_start_date_returns_error_no_api_call(self, env):
        data = _create(env, fields={"startDate": "ASAP"})

        assert data["error"] == "invalid_start_date"
        assert "ASAP" in data["message"]
        assert "YYYY-MM-DD" in data["hint"]
        assert env.put_calls == 0
        assert env.bodies == []

    def test_create_job_invalid_start_date_is_not_owner_not_found(self, env):
        data = _create(env, fields={"startDate": "2026-02-30"})

        assert data["error"] != "owner_not_found"
        assert data["error"] == "invalid_start_date"

    @pytest.mark.parametrize("bad", [True, "2026-11-20T00:00:00Z", "20261120", float("nan"), {"a": 1}])
    def test_create_job_rejects_other_junk(self, env, bad):
        data = _create(env, fields={"startDate": bad})

        assert data["error"] == "invalid_start_date"
        assert env.put_calls == 0

    def test_create_job_invalid_env_default_start_date_returns_error(self, env, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_DEFAULTS", '{"startDate": "soon"}')

        data = _create(env)

        assert data["error"] == "invalid_start_date"
        assert env.put_calls == 0

    def test_create_job_start_date_satisfies_required_config(self, env, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", '["startDate"]')

        data = _create(env)

        assert data.get("error") is None
        assert data["changedEntityId"] == 1
        assert env.body["startDate"] == NOV_20_2026

    def test_create_job_other_required_field_still_enforced(self, env, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", '["startDate", "title", "salary"]')

        data = _create(env)

        assert data["error"] == "required_fields_missing"
        assert data["fields"] == ["salary"]
        assert env.put_calls == 0

    def test_create_job_invalid_date_reported_before_required_check(self, env, monkeypatch):
        monkeypatch.setenv("BULLHORN_JOBORDER_REQUIRED", '["salary"]')

        data = _create(env, fields={"startDate": "nope"})

        assert data["error"] == "invalid_start_date"


class TestUpdateJobStartDate:
    def _update(self, env, fields, now=_utc(2026, 11, 20, 12, 0)):
        with patch("bullhorn_mcp.server._now_utc", return_value=now):
            return env.run(server.update_job, 51533, fields)

    def test_update_job_start_date_normalised(self, env):
        data = self._update(env, {"startDate": NOV_20_2026_MIDNIGHT_UTC})

        assert data["changedEntityId"] == 51533
        assert env.body == {"startDate": NOV_20_2026}

    def test_update_job_iso_and_label_start_date_normalised(self, env):
        self._update(env, {"startDate": "2026-07-15"})
        self._update(env, {"Start Date": "2027-02-01"})

        assert env.bodies == [{"startDate": JUL_15_2026}, {"startDate": FEB_01_2027}]

    def test_update_job_without_start_date_does_not_add_one(self, env):
        self._update(env, {"title": "Senior Engineer"})

        assert env.body == {"title": "Senior Engineer"}
        assert "startDate" not in env.body

    def test_update_job_null_and_blank_start_date_default_to_today(self, env):
        self._update(env, {"startDate": None})
        self._update(env, {"startDate": ""})

        assert env.bodies == [{"startDate": NOV_20_2026}, {"startDate": NOV_20_2026}]

    def test_update_job_invalid_start_date_returns_error_no_api_call(self, env):
        data = self._update(env, {"startDate": "2026-13-01", "title": "X"})

        assert data["error"] == "invalid_start_date"
        assert "YYYY-MM-DD" in data["hint"]
        assert env.post_calls == 0
        assert env.bodies == []

    @pytest.mark.parametrize("bad", [False, "20261120", float("inf"), ["x"]])
    def test_update_job_rejects_other_junk(self, env, bad):
        data = self._update(env, {"startDate": bad})

        assert data["error"] == "invalid_start_date"
        assert env.post_calls == 0


class TestStartDateEndToEnd:
    def test_create_job_just_after_midnight_dublin_sends_dublin_today_at_0500_utc(self, env):
        # 00:30 UTC on 21 Nov: Dublin is already 21 Nov, New York still 20 Nov (19:30).
        data = _create(env, now=_utc(2026, 11, 21, 0, 30))

        assert data["changedEntityId"] == 1
        assert env.body["startDate"] == NOV_21_2026
        assert datetime.fromtimestamp(env.body["startDate"] / 1000, tz=timezone.utc) == _utc(2026, 11, 21, 5, 0)
        assert env.body["clientCorporation"] == {"id": 1}
        assert env.body["clientContact"] == {"id": 2}
        assert env.body["title"] == "Engineer"

    def test_update_job_midnight_utc_epoch_writes_corrected_value(self, env):
        # Job 51533's shape: 20 Nov 2026 stored as midnight UTC.
        data = env.run(server.update_job, 51533, {"startDate": NOV_20_2026_MIDNIGHT_UTC})

        assert data["changeType"] == "UPDATE"
        assert env.body == {"startDate": 1795150800000}
        assert datetime.fromtimestamp(env.body["startDate"] / 1000, tz=timezone.utc) == _utc(2026, 11, 20, 5, 0)

    def test_update_job_read_back_value_round_trips_unchanged(self, env):
        env.run(server.update_job, 51533, {"startDate": NOV_20_2026})

        assert env.body == {"startDate": NOV_20_2026}


# --------------------------------------------------------------------------- interface

class TestStartDateArgsReachAgent:
    """P4: the startDate sentence lives in the `fields` Args entry, which FastMCP turns
    into that parameter's schema description (not the tool description)."""

    @pytest.mark.parametrize("tool_name, needle", [
        ("create_job", "today when left out"),
        ("update_job", "an empty one sets today"),
    ])
    def test_fields_schema_mentions_start_date(self, tool_name, needle):
        import asyncio
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == tool_name)
        desc = tool.parameters["properties"]["fields"]["description"]
        assert "startDate" in desc and "YYYY-MM-DD" in desc and needle in desc
