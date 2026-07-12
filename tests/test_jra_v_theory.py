from datetime import date
import sqlite3
from types import SimpleNamespace

from jra_srb.jra_v_theory import build_three_way_consensus, build_v_theory_prediction


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
    assert result["betting_status"] == "not_final"
    assert len(result["ranking"]) == 6


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
