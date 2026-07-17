
from jra_srb.extractors import parse_jra_meeting_coordinates
from jra_srb.jra_day_race_scout import (
    build_shadow_decision,
    grade_scout_entry,
    sort_scout_entries,
)
from jra_srb.models import JraDayRaceScoutEntry, JraScoutConfidenceSignal, JraScoutValueSignal


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
