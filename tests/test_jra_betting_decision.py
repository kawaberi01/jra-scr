from datetime import UTC, datetime

from jra_srb.jra_betting_decision import build_win_ev_decision
from jra_srb.models import OddsEntry, RaceOdds


def _odds(values: dict[str, str]) -> RaceOdds:
    return RaceOdds(
        race_id="202607110301",
        odds={"win": [OddsEntry(bet_type="win", combination=[horse_no], odds=odds) for horse_no, odds in values.items()]},
        fetched_at=datetime.now(UTC),
        source="test",
    )


def test_recommends_win_only_when_ev_and_market_edge_pass_thresholds():
    decision = build_win_ev_decision(
        [
            {"horse_no": "1", "horse_name": "本命", "win_probability_race_normalized": 0.5},
            {"horse_no": "2", "horse_name": "相手", "win_probability_race_normalized": 0.5},
        ],
        _odds({"1": "3.0", "2": "2.0"}),
    )
    assert decision["status"] == "recommended"
    assert decision["tickets"] == [{"bet_type": "win", "selection": "1", "amount": 1000, "reason": "期待回収倍率 1.500"}]


def test_returns_no_bet_when_no_candidate_passes_thresholds():
    decision = build_win_ev_decision(
        [{"horse_no": "1", "horse_name": "本命", "win_probability_race_normalized": 1.0}],
        _odds({"1": "1.5"}),
    )
    assert decision["status"] == "no_bet"
    assert decision["tickets"] == []


def test_returns_unavailable_without_win_odds():
    odds = RaceOdds(race_id="202607110301", fetched_at=datetime.now(UTC), source="test")
    decision = build_win_ev_decision([], odds)
    assert decision["status"] == "unavailable"
