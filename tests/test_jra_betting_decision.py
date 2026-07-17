from datetime import UTC, datetime

from jra_srb.jra_betting_decision import build_win_betting_decision, build_win_ev_decision
from jra_srb.models import OddsEntry, RaceOdds


def _odds(values: dict[str, str]) -> RaceOdds:
    return RaceOdds(
        race_id="202607110301",
        odds={"win": [OddsEntry(bet_type="win", combination=[horse_no], odds=odds) for horse_no, odds in values.items()]},
        fetched_at=datetime.now(UTC),
        source="test",
    )


def test_history_win_ev_is_shadow_only_even_when_legacy_thresholds_pass():
    decision = build_win_ev_decision(
        [
            {"horse_no": "1", "horse_name": "本命", "win_probability_race_normalized": 0.5},
            {"horse_no": "2", "horse_name": "相手", "win_probability_race_normalized": 0.5},
        ],
        _odds({"1": "3.0", "2": "2.0"}),
    )
    assert decision["status"] == "shadow_only"
    assert decision["strategy"] == "history_win_ev"
    assert decision["ticket_status"] == "shadow_only"
    assert decision["selection"]["horse_no"] == "1"
    assert decision["tickets"] == []
    assert "未校正・購入非推奨" in decision["reason"]


def test_returns_no_bet_when_no_candidate_passes_thresholds():
    decision = build_win_ev_decision(
        [{"horse_no": "1", "horse_name": "本命", "win_probability_race_normalized": 1.0}],
        _odds({"1": "1.5"}),
    )
    assert decision["status"] == "shadow_only"
    assert decision["selection"] is None
    assert decision["tickets"] == []


def test_returns_unavailable_without_win_odds():
    odds = RaceOdds(race_id="202607110301", fetched_at=datetime.now(UTC), source="test")
    decision = build_win_ev_decision([], odds)
    assert decision["status"] == "unavailable"


def test_newcomer_uses_public_and_market_consensus_instead_of_history_ev():
    decision = build_win_betting_decision(
        "メイクデビュー函館",
        [{"horse_no": "3", "horse_name": "大穴", "win_probability_race_normalized": 0.2}],
        [
            {"horse_no": "5", "horse_name": "指数首位"},
            {"horse_no": "3", "horse_name": "大穴"},
        ],
        _odds({"3": "65.3", "5": "1.9"}),
    )
    assert decision["status"] == "recommended"
    assert decision["strategy"] == "newcomer_public_market_consensus"
    assert decision["tickets"] == [{"bet_type": "win", "selection": "5", "amount": 1000, "reason": "公開材料1位かつ単勝支持上位"}]


def test_newcomer_returns_no_bet_without_public_and_market_consensus():
    decision = build_win_betting_decision(
        "2歳新馬",
        [],
        [{"horse_no": "4", "horse_name": "指数首位"}],
        _odds({"1": "2.0", "2": "3.0", "3": "5.0", "4": "8.0"}),
    )
    assert decision["status"] == "no_bet"
    assert decision["strategy"] == "newcomer_public_market_consensus"
    assert decision["tickets"] == []
