
import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace

from jra_srb.extractors import parse_jra_meeting_coordinates
import jra_srb.jra_day_race_scout as scout_module
from jra_srb.jra_day_race_scout import (
    JraDayRaceScout,
    build_shadow_decision,
    grade_scout_entry,
    sort_scout_entries,
)
from jra_srb.models import (
    JraDayRaceScoutEntry,
    JraScoutConfidenceSignal,
    JraScoutValueSignal,
    RaceCard,
    Runner,
)


def test_parse_jra_meeting_coordinates_from_official_cname():
    html = """
    <a href="/JRADB/accessD.html?CNAME=pw01dde0103202602060920260712/16">9R</a>
    """
    assert parse_jra_meeting_coordinates(html) == (2, 6)


def test_grade_scout_entry_requires_all_s_conditions_and_maps_v_to_provisional():
    materials = [{"horse_no": "5"}, {"horse_no": "2"}, {"horse_no": "7"}]
    history = [
        {"horse_no": "5", "win_probability_race_normalized": 0.20},
        {"horse_no": "7", "win_probability_race_normalized": 0.14},
        {"horse_no": "9", "win_probability_race_normalized": 0.10},
    ]
    decision = {
        "status": "recommended",
        "selection": {"horse_no": "5", "expected_return": 1.18, "market_edge": 0.062},
        "tickets": [{"bet_type": "win"}],
    }

    grade, signals, confidence, value = grade_scout_entry(materials, history, decision)

    assert grade == "A"
    assert signals == ["S", "V"]
    assert confidence.history_probability_gap == 0.06
    assert value is not None and value.status == "provisional_value"
    assert "ticket" not in value.model_dump()


def test_sort_scout_entries_uses_grade_value_gap_time_and_race_id():
    def entry(race_id, grade, value, gap, start):
        return JraDayRaceScoutEntry(
            race_id=race_id, course="fukushima", race_no=1, grade=grade, start_time=start,
            confidence_signal=JraScoutConfidenceSignal(history_probability_gap=gap),
            value_signal=JraScoutValueSignal(status="provisional_value", expected_return=value),
        )

    entries = [
        entry("3", "B", 2.0, 0.2, "10:00"),
        entry("2", "A", 1.1, 0.1, "11:00"),
        entry("1", "A", 1.2, 0.05, "12:00"),
    ]

    assert [item.race_id for item in sort_scout_entries(entries)] == ["1", "2", "3"]


def test_build_shadow_decision_removes_tickets_without_mutating_source():
    decision = {
        "status": "recommended",
        "ticket_status": "recommended",
        "policy_version": "policy-v1",
        "tickets": [{"bet_type": "win", "amount": 1000}],
        "candidates": [{"horse_no": "5"}],
    }

    shadow = build_shadow_decision(decision)

    assert shadow["source_status"] == "recommended"
    assert shadow["status"] == "shadow_only"
    assert shadow["ticket_status"] == "shadow_only"
    assert shadow["tickets"] == []
    assert shadow["candidates"] == [{"horse_no": "5"}]
    assert decision["tickets"] == [{"bet_type": "win", "amount": 1000}]


def test_run_prefers_local_pre_race_snapshots_when_they_cover_all_meeting_races(monkeypatch):
    race = SimpleNamespace(race_id="202607190301")
    meeting = SimpleNamespace(races=[race])

    class Store:
        def list_pre_race_race_ids(self, target_date):
            assert target_date == date(2026, 7, 19)
            return ["202607190301"]

    scout = JraDayRaceScout(
        jra_service=SimpleNamespace(
            get_meetings_for_date=lambda _target_date: _async_result([meeting])
        ),
        prediction_service=object(), store=Store(),
        analysis_db_path="unused.sqlite", history_model_path="unused.json",
    )
    expected = object()

    def local_run(target_date, run_id, observed_at, race_ids, max_candidates):
        assert target_date == date(2026, 7, 19)
        assert race_ids == ["202607190301"]
        assert max_candidates == 5
        return expected

    monkeypatch.setattr(scout, "_run_from_local_snapshots", local_run)

    assert asyncio.run(scout.run(date(2026, 7, 19))) is expected


def test_run_does_not_limit_scout_to_incomplete_local_snapshots(monkeypatch):
    target_date = date(2026, 8, 9)
    first = SimpleNamespace(race_id="202608090401", race_no=1, race_name="first", start_time="10:00")
    second = SimpleNamespace(race_id="202608090402", race_no=2, race_name="second", start_time="10:30")
    meeting = SimpleNamespace(course="niigata", meeting_no=1, meeting_day=1, races=[first, second])

    class Store:
        def list_pre_race_race_ids(self, _target_date):
            return [first.race_id]

        def save_jra_scout_result(self, result, observations=None):
            self.result = result

    class JraService:
        async def get_meetings_for_date(self, _target_date):
            return [meeting]

        async def get_race_card_by_number(self, _date, _course, race_no, **_kwargs):
            race = first if race_no == 1 else second
            return RaceCard(
                race_id=race.race_id, race_name=race.race_name, course="niigata",
                start_time=race.start_time,
                runners=[Runner(horse_no="1", horse_name="test horse", odds="3.5")],
                fetched_at=datetime.now(UTC), source="test",
            )

    monkeypatch.setattr(scout_module, "_has_started", lambda *_args: False)
    monkeypatch.setattr(scout_module, "load_model_artifact", lambda _path: {"trained_through": "2026-08-08"})
    monkeypatch.setattr(scout_module, "build_artifact_live_records", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        scout_module, "score_live_records",
        lambda *_args: [{"horse_no": "1", "win_probability_race_normalized": 0.2}],
    )
    monkeypatch.setattr(
        scout_module, "build_win_betting_decision",
        lambda *_args: {"status": "not_recommended", "reason": "test"},
    )
    store = Store()
    scout = JraDayRaceScout(
        jra_service=JraService(), prediction_service=object(), store=store,
        analysis_db_path="unused.sqlite", history_model_path="unused.json",
    )

    result = asyncio.run(scout.run(target_date, mode="quick", time_budget_seconds=1))

    assert result.race_count == 2
    assert result.analyzed_count == 2
    assert {entry.race_id for entry in result.entries} == {first.race_id, second.race_id}


async def _async_result(value):
    return value


def test_quick_scout_uses_card_odds_without_loading_public_prediction_materials(monkeypatch):
    target_date = date(2026, 8, 9)
    race = SimpleNamespace(race_id="202608090401", race_no=1, race_name="test", start_time="10時00分")
    meeting = SimpleNamespace(course="niigata", meeting_no=1, meeting_day=1, races=[race])

    class Store:
        def list_pre_race_race_ids(self, _target_date):
            return []

        def save_jra_scout_result(self, result, observations=None):
            self.result = result

    class JraService:
        async def get_meetings_for_date(self, _target_date):
            return [meeting]

        async def get_race_card_by_number(self, *_args, **_kwargs):
            return RaceCard(
                race_id=race.race_id,
                race_name=race.race_name,
                course="niigata",
                start_time=race.start_time,
                runners=[Runner(horse_no="1", horse_name="test horse", odds="3.5")],
                fetched_at=datetime.now(UTC),
                source="test",
            )

    class PredictionService:
        async def get_prediction_bundle(self, *_args, **_kwargs):
            raise AssertionError("quick scout must not load public prediction materials")

    monkeypatch.setattr(scout_module, "_has_started", lambda *_args: False)
    monkeypatch.setattr(scout_module, "load_model_artifact", lambda _path: {"trained_through": "2026-08-08"})
    monkeypatch.setattr(scout_module, "build_artifact_live_records", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        scout_module,
        "score_live_records",
        lambda *_args: [{"horse_no": "1", "win_probability_race_normalized": 0.2}],
    )
    monkeypatch.setattr(
        scout_module,
        "build_win_betting_decision",
        lambda *_args: {"status": "not_recommended", "reason": "test"},
    )
    store = Store()
    scout = JraDayRaceScout(
        jra_service=JraService(), prediction_service=PredictionService(), store=store,
        analysis_db_path="unused.sqlite", history_model_path="unused.json",
    )

    result = asyncio.run(scout.run(target_date, mode="quick", time_budget_seconds=1))

    assert result.status == "completed"
    assert result.analyzed_count == 1
    assert result.entries[0].component_status["odds"] == "card_odds"
    assert result.entries[0].component_status["public_analysis"] == "not_loaded"


def test_quick_scout_returns_partial_result_when_time_budget_is_exceeded(monkeypatch):
    target_date = date(2026, 8, 9)
    race = SimpleNamespace(race_id="202608090401", race_no=1, race_name="test", start_time="10時00分")
    meeting = SimpleNamespace(course="niigata", meeting_no=1, meeting_day=1, races=[race])

    class Store:
        def list_pre_race_race_ids(self, _target_date):
            return []

        def save_jra_scout_result(self, result, observations=None):
            self.result = result

    class JraService:
        async def get_meetings_for_date(self, _target_date):
            return [meeting]

        async def get_race_card_by_number(self, *_args, **_kwargs):
            await asyncio.sleep(1)
            raise AssertionError("task should be cancelled before the card is returned")

    monkeypatch.setattr(scout_module, "_has_started", lambda *_args: False)
    monkeypatch.setattr(scout_module, "load_model_artifact", lambda _path: {"trained_through": "2026-08-08"})
    scout = JraDayRaceScout(
        jra_service=JraService(), prediction_service=object(), store=Store(),
        analysis_db_path="unused.sqlite", history_model_path="unused.json",
    )

    result = asyncio.run(scout.run(target_date, mode="quick", time_budget_seconds=0.01))

    assert result.status == "partial"
    assert result.analyzed_count == 0
    assert result.entries[0].reasons == ["time_budget_exceeded"]
    assert result.errors[-1]["error_type"] == "time_budget_exceeded"
