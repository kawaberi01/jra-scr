from datetime import UTC, date, datetime
import sqlite3
from types import SimpleNamespace

from jra_srb.jra_v_theory import (
    build_three_way_consensus,
    build_v_theory_prediction,
    build_v_theory_prediction_record,
)


def _database(path):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            create table races (race_id text primary key, race_date text, surface text, distance text, source text);
            create table runners (race_id text, horse_no text, horse_name text, jockey text, trainer text);
            create table result_entries (race_id text, horse_no text, rank integer);
            create table payouts (race_id text);
        """)
        for race_id, race_date in (("202401050501", "2024-01-05"), ("202401120501", "2024-01-12")):
            conn.execute("insert into races values (?,?,?,?,?)", (race_id, race_date, "芝", "1,600", "https://www.jra.go.jp/JRADB/accessS.html"))
            for number in range(1, 7):
                conn.execute("insert into runners values (?,?,?,?,?)", (race_id, str(number), f"馬{number}", f"騎手{number}", f"厩舎{number}"))
                conn.execute("insert into result_entries values (?,?,?)", (race_id, str(number), number))
            conn.execute("insert into payouts values (?)", (race_id,))


def test_main_venue_v89_returns_shadow_ranking(tmp_path):
    db = tmp_path / "analysis.sqlite"
    _database(db)
    runners = [
        SimpleNamespace(horse_no=str(number), horse_name=f"馬{number}", jockey=f"騎手{number}", trainer=f"厩舎{number}", odds=str(number + 1), popularity=str(number), horse_weight_diff="0")
        for number in range(1, 7)
    ]
    card = SimpleNamespace(race_id="202401190505", runners=runners, surface="芝", distance="1,600")
    result = build_v_theory_prediction(db, target_date=date(2024, 1, 19), course="tokyo", card=card, win_odds={str(number): float(number + 1) for number in range(1, 7)})
    assert result["status"] == "available"
    assert result["theory_version"] == "v89"
    assert result["betting_status"] == "shadow_only"
    assert result["model_status"] == "shadow"
    assert result["application"] == "autumn_2026_shadow"
    assert len(result["ranking"]) == 6
    assert len(result["head_candidates"]) == 3
    assert result["ticket_candidates"] == []
    assert build_v_theory_prediction(
        db, target_date=date(2024, 1, 19), course="tokyo", card=card,
        win_odds={str(number): float(number + 1) for number in range(1, 7)},
    ) == result
    summer = build_v_theory_prediction(
        db, target_date=date(2024, 1, 19), course="fukushima", card=card,
        win_odds={str(number): float(number + 1) for number in range(1, 7)},
    )
    assert summer["theory_version"] == "v90"
    assert summer["application"] == "summer_shadow"


def test_summer_route_and_consensus_are_explicit():
    card = SimpleNamespace(race_id="202401010701", runners=[], surface="芝", distance="1,200")
    # Route selection occurs before DB access.
    unavailable = build_v_theory_prediction("missing.sqlite", target_date=date(2024, 1, 1), course="chukyo", card=card, win_odds={})
    assert unavailable["reason"] == "chukyo_v_branch_rejected"
    consensus = build_three_way_consensus(
        [{"horse_no": "1", "horse_name": "A"}], [{"horse_no": "1", "horse_name": "A"}],
        {"status": "available", "ranking": [{"horse_no": "2", "horse_name": "B"}]},
    )
    assert consensus["status"] == "three_way_reference"
    assert consensus["ranking"][0]["horse_no"] == "1"


def test_v89_requires_actual_wide_odds_for_shadow_ticket(tmp_path):
    db = tmp_path / "analysis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            create table races (race_id text primary key, race_date text, surface text, distance text, source text);
            create table runners (race_id text, horse_no text, horse_name text, jockey text, trainer text);
            create table result_entries (race_id text, horse_no text, rank integer);
            create table payouts (race_id text);
        """)
        for race_id, race_date in (("202401050501", "2024-01-05"), ("202401120501", "2024-01-12")):
            conn.execute("insert into races values (?,?,?,?,?)", (race_id, race_date, "芝", "1,600", "https://www.jra.go.jp/JRADB/accessS.html"))
            for number in range(1, 15):
                rank = number
                conn.execute("insert into runners values (?,?,?,?,?)", (race_id, str(number), f"馬{number}", f"騎手{number}", f"厩舎{number}"))
                conn.execute("insert into result_entries values (?,?,?)", (race_id, str(number), rank))
            conn.execute("insert into payouts values (?)", (race_id,))
    runners = [
        SimpleNamespace(
            horse_no=str(number), horse_name=f"馬{number}", jockey=f"騎手{number}", trainer=f"厩舎{number}",
            odds="2.0" if number == 1 else "10.0" if number == 4 else "12.0" if number == 5 else "30.0",
            popularity=str(number), horse_weight_diff="0",
        )
        for number in range(1, 15)
    ]
    card = SimpleNamespace(race_id="202401190505", race_name="一般戦", runners=runners, surface="芝", distance="1,600", start_time="15時00分")
    win_odds = {runner.horse_no: float(runner.odds) for runner in runners}
    no_market = build_v_theory_prediction(db, target_date=date(2024, 1, 19), course="tokyo", card=card, win_odds=win_odds)
    assert no_market["ticket_candidates"] == []
    race_odds = SimpleNamespace(
        odds={
            "win": [
                SimpleNamespace(combination=[runner.horse_no], odds=runner.odds, odds_min=None, odds_max=None)
                for runner in runners
            ],
            "wide": [
                SimpleNamespace(combination=["1", "4"], odds=None, odds_min="5.0", odds_max="6.0"),
                SimpleNamespace(combination=["1", "5"], odds=None, odds_min="7.0", odds_max="8.0"),
            ]
        },
        entries=[], bet_type=None, fetched_at=datetime(2024, 1, 19, 5, tzinfo=UTC),
    )
    with_market = build_v_theory_prediction(
        db, target_date=date(2024, 1, 19), course="tokyo", card=card,
        win_odds=win_odds, race_odds=race_odds,
    )
    assert with_market["ticket_status"] == "shadow_only"
    assert with_market["ticket_candidates"]
    assert all(ticket["odds_as_of"] == "2024-01-19T05:00:00+00:00" for ticket in with_market["ticket_candidates"])
    bundle = SimpleNamespace(
        race_id=card.race_id, date=date(2024, 1, 19), course="tokyo", race_no=5,
        card=card, odds_summary=race_odds, model_dump=lambda mode: {"race_id": card.race_id, "mode": mode},
    )
    record = build_v_theory_prediction_record(db, bundle)
    assert record["theory_version"] == "v89_autumn_2026_shadow"
    assert record["mode"] == "paper_validation"
    assert record["prediction_tickets"]
    assert record["prediction_json"]["promotion_target_tickets"] == 30

    race_odds.fetched_at = datetime(2024, 1, 19, 7, tzinfo=UTC)
    post_start = build_v_theory_prediction(
        db, target_date=date(2024, 1, 19), course="tokyo", card=card,
        win_odds=win_odds, race_odds=race_odds,
    )
    assert post_start["market_as_of_valid"] is False
    assert post_start["ticket_candidates"] == []


def test_v89_history_excludes_target_day_and_future_results(tmp_path):
    db = tmp_path / "analysis.sqlite"
    _database(db)
    runners = [
        SimpleNamespace(horse_no=str(number), horse_name=f"馬{number}", jockey=f"騎手{number}", trainer=f"厩舎{number}", odds=str(number + 1), popularity=str(number), horse_weight_diff="0")
        for number in range(1, 7)
    ]
    card = SimpleNamespace(race_id="202401190505", race_name="一般戦", runners=runners, surface="芝", distance="1,600")
    kwargs = dict(target_date=date(2024, 1, 19), course="tokyo", card=card, win_odds={str(number): float(number + 1) for number in range(1, 7)})
    before = build_v_theory_prediction(db, **kwargs)
    with sqlite3.connect(db) as conn:
        for race_id, race_date in (("202401190501", "2024-01-19"), ("202401260501", "2024-01-26")):
            conn.execute("insert into races values (?,?,?,?,?)", (race_id, race_date, "芝", "1,600", "https://www.jra.go.jp/JRADB/accessS.html"))
            for number in range(1, 7):
                conn.execute("insert into runners values (?,?,?,?,?)", (race_id, str(number), f"馬{number}", f"騎手{number}", f"厩舎{number}"))
                conn.execute("insert into result_entries values (?,?,?)", (race_id, str(number), 7 - number))
            conn.execute("insert into payouts values (?)", (race_id,))
    after = build_v_theory_prediction(db, **kwargs)
    assert before["ranking"] == after["ranking"]


def test_v89_separates_newcomer_and_obstacle_without_db_access():
    for race_name, surface, expected in (("メイクデビュー東京", "芝", "newcomer"), ("障害3歳以上未勝利", "障害", "obstacle")):
        card = SimpleNamespace(race_id="202409010505", race_name=race_name, runners=[], surface=surface, distance="1,600")
        result = build_v_theory_prediction("missing.sqlite", target_date=date(2024, 9, 1), course="tokyo", card=card, win_odds={})
        assert result["status"] == "excluded"
        assert result["reason"] == f"separate_race_category:{expected}"
