"""概要: 条件統合の欠測伝播・過去時点・救済・成績集計を検証する。
作成日: 2026-11-22
入力: 外部接続を持たない最小の競走・過去走データ。
出力: pytestの判定。
実行例: uv run python -m pytest tests/test_jra_mile_rule_integration.py -q
注意事項: 外部通信・DB書込みなし。
"""

import pytest
from jra_srb.jra_mile_rule_integration import expression, rules, features, counts, combine, select


@pytest.mark.parametrize("op,args,expected", [("and", [True, None], None), ("and", [False, None], False),
    ("or", [False, None], None), ("or", [True, None], True), ("not", [None], None)])
def test_unknown_logic(op, args, expected):
    """欠測を偽へ置き換えず、確定した否定/肯定だけが短絡する。"""
    assert expression({"op": op, "children": [{"atom": str(i)} for i in range(len(args))]}, {str(i): v for i, v in enumerate(args)}) is expected


def test_scope_and_exact_top2():
    """GI3着を連対へ混ぜず、当日の勝利も過去実績へ混入させない。"""
    race = {"race_date": "2026-11-22"}
    runner = {"horse_id": "x", "age": 6}
    history = [{"horse_id": "x", "race_date": d, "race_key": d, "status": "active", "grade": "A", "track_code": "18", "distance": 1600, "rank": r, "race_name": "安田記念"}
               for d, r in (("2026-06-01", 3), ("2026-11-22", 1))]
    f = features(race, runner, history, [])
    assert f["atoms"]["mile_g1_top2"] is False
    assert f["references"]["history_count"] == 1
    assert f["references"]["previous"]["race_date"] == "2026-06-01"


def test_age_rescue_and_empty_history():
    """高齢馬を富士好走で救済し、履歴欠落では判定を保留する。"""
    race, runner = {"race_date": "2026-11-22"}, {"horse_id": "x", "age": 7}
    f = features(race, runner, [], [])
    assert f["matches"]["rescue_age"] is None
    history = [{"horse_id": "x", "race_key": "a", "race_date": "2026-10-20", "race_name": "富士ステークス", "rank": 2, "status": "active"}]
    f = features(race, runner, history, [])
    assert f["rescue"]["rescue_age"]["status"] == "救済"
    assert f["matches"]["rescue_age"] is True


def test_latest_foreign_not_domestic_substitute():
    """海外実前走を接続し国内好走へ都合よく戻らない。"""
    race, runner = {"race_date": "2026-11-22"}, {"horse_id": "x", "age": 4}
    domestic = [{"horse_id": "x", "race_key": "a", "race_date": "2026-06-01", "rank": 1, "status": "active", "race_name": "安田記念"}]
    foreign = [{"horse_id": "x", "race_date": "2026-08-01", "rank": 10, "race_name_raw": "海外GI"}]
    f = features(race, runner, domestic, foreign)
    assert f["atoms"]["previous5"] is False
    assert f["references"]["previous"]["foreign"] is True


def test_counts_and_no_sample():
    """四区分の定義と空集合を検査し、未確定結果を着外にしない。"""
    c = counts([{"finish_rank": n} for n in (1, 2, 3, 8)])
    assert c["record"] == "1-1-1-1" and c["top3_rate"] == .75
    assert counts([])["record"] == "0-0-0-0" and counts([])["top3_rate"] is None
    with pytest.raises(Exception):
        counts([{"finish_rank": None}])


def test_fixed_candidates_and_baseline():
    """25候補が一意で、基準方式の数値と順序は変更しない。"""
    assert len(rules()) == len({r["id"] for r in rules()}) == 25
    base = {"runners": [{"horse_no": "01", "horse_id": "x", "probability_top3": .2}], "pattern": "N+C+W"}
    assert combine(base, [], 0, "baseline")["runners"] == base["runners"]


def test_selection_does_not_use_confirmation():
    """確認年だけを極端に悪化させても、開発年の選択は変えない。"""
    names = ("baseline", "integrated:age34")
    annual = []
    for year in range(2008, 2026):
        for name in names:
            annual.append({"pattern": name, "race_date": f"{year}-11-20", "brier": .2 if name == "baseline" else .19 if year <= 2020 else .99,
                "logloss": .5, "top1_top3_hit": .5, "top3_captured": 1., "top6_captured": 2.})
    sets = [{"race_key": str(i), "race_date": f"{2003+i}-11-20", "rows": [{"matches": {r["id"]: True for r in rules()}} for _ in range(4)]} for i in range(5)]
    selected = select(annual, sets)
    assert selected["pattern"] == "integrated:age34" and selected["selection_through"] == 2020
