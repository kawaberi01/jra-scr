"""概要: 重賞専用パーツの欠測・時点境界・候補選択・順位評価を検証する。
作成日: 2026-11-20
入力: 合成履歴と固定設定。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_specific_patterns.py
注意事項: DB・外部通信・当日結果参照なし。
"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_specific_patterns import (candidates, capture, mean_metrics, predict,
                                         route_name, select_candidate, specific_features, make_examples)
from jra_srb.jra_research_contracts import ResearchError

CONFIG = json.loads((ROOT / "configs/research/graded_specific_patterns_v1.json").read_text(encoding="utf-8"))
RACE = dict(race_date="2020-11-15", venue_code="08", distance=1600, track_code="18")
RUNNER = dict(horse_id="2020100001", weight_carried=56.)


def history(**changes):
    """境界テスト用に必要な走歴属性を生成する。"""
    return dict(dict(horse_id=RUNNER["horse_id"], race_key="202010180811", race_date="2020-10-18", status="active",
                     venue_code="08", distance=1600, track_code="18", rank=1, grade="A", ra_verified=True,
                     race_name="富士ステークス", weight_carried=57.), **changes)


def test_future_and_target_results_do_not_enter_features():
    """同日・未来の成績と当該順位を変えても事前特徴は不変。"""
    old = history()
    expected = specific_features("mile", RACE, RUNNER, [old])
    more = [old, history(race_date="2020-11-15", rank=18), history(race_date="2021-01-01", rank=1)]
    assert specific_features("mile", {**RACE, "rank": 18}, {**RUNNER, "rank": 18}, more) == expected


def test_unknown_is_not_no_achievement_and_other_horse_is_excluded():
    """履歴なしは実績なしとせず、別馬履歴を取り込まない。"""
    values = specific_features("mile", RACE, RUNNER, [history(horse_id="9999999999")])["values"]
    assert all(v is None for v in values.values())
    uncertain = history(rank=8, ra_verified=False, grade=None)
    values = specific_features("mile", RACE, RUNNER, [uncertain])["values"]
    assert values["mile_graded"] is None and values["mile_g1"] is None
    assert specific_features("mile", RACE, RUNNER, [uncertain, history(race_date="2019-10-01")])["values"]["mile_g1"] == "勝利"


@pytest.mark.parametrize("distance,label", [(1200,"1200以下"),(1400,"1400"),(1600,"1600"),(1800,"1800"),(2000,"2000以上")])
def test_mile_distance_separates_sprint_and_mile(distance, label):
    """距離区分が短距離・マイル・中距離を分離する。"""
    assert specific_features("mile", RACE, RUNNER, [history(distance=distance)])["values"]["prep_distance"] == label


def test_stage_and_surface_and_name_alias():
    """代替場・ダートを同舞台実績へ混ぜず、正式名だけを対応させる。"""
    vals = specific_features("mile", RACE, RUNNER, [history(venue_code="09")])["values"]
    assert vals["same_stage"] == "収録内確認なし"
    vals = specific_features("mile", RACE, RUNNER, [history(track_code="24")])["values"]
    assert vals["prep_distance"] == "ダート" and vals["mile_g1"] == "収録内確認なし"
    assert route_name(" 富士Ｓ ") == "富士S"
    assert route_name("ＭＢＳ賞スワンステークス") == "スワンS"
    assert route_name("毎日放送賞　スワンステークス") == "スワンS"
    assert route_name("天皇賞（秋）") == "天皇賞秋"
    assert route_name("天皇賞（春）") == "その他"
    assert route_name("") is None


@pytest.mark.parametrize("weight,label", [(53,"53以下"),(53.5,"53超55以下"),(55,"53超55以下"),(55.5,"55超57以下"),(57,"55超57以下"),(57.5,"57超")])
def test_handicap_boundaries(weight, label):
    """斤量の境界と前走なしの欠測を確認する。"""
    v = specific_features("fukushima", RACE, {**RUNNER, "weight_carried":weight}, [])["values"]
    assert v["handicap"] == label and v["handicap_change"] is None


def test_change_and_gap_boundaries_and_unknown_weight():
    """減量境界・28日境界と不正斤量の欠測を確認する。"""
    values = specific_features("fukushima", RACE, RUNNER, [history()])["values"]
    assert values["handicap_change"] == "-1以下" and values["layoff"] == "1〜28日"
    values = specific_features("fukushima", RACE, RUNNER, [history(race_date="2020-10-17", weight_carried=0)])["values"]
    assert values["handicap_change"] is None and values["layoff"] == "29〜56日"
    with pytest.raises(ResearchError, match="specific_same_day_history_conflict"):
        specific_features("mile", RACE, RUNNER, [history(), history(race_key="202010180911")])


def test_selection_ignores_confirmation_and_resolves_ties():
    """確認年の成績を極端に変えても開発選択は不変。"""
    options = candidates(CONFIG, "mile")
    assert len(options) == 30 and len({c["mask"] for c in options}) == 15
    annual = [{"pattern":c["pattern"],"race_date":f"{year}-11-15","brier":.2} for c in options for year in range(2008,2021)]
    expected = select_candidate(annual, options, CONFIG)
    assert expected["candidate"]["pattern"] == "S01-only"
    annual += [{"pattern":c["pattern"],"race_date":"2025-11-15","brier":0 if c["mask"]==15 else 1} for c in options]
    assert select_candidate(annual, options, CONFIG) == expected


def test_tie_capture_is_fair_and_mean_is_race_weighted():
    """同率の並べ方に依存せず、頭数の異なる開催も均等に集計する。"""
    rows = [dict(horse_no=str(i), probability_top3=.3) for i in range(10)]
    truth = {str(i):int(i<3) for i in range(10)}
    assert capture(rows,truth,3) == pytest.approx(.9)
    assert capture(list(reversed(rows)),truth,6) == pytest.approx(1.8)
    metrics = [dict(brier=x,logloss=x,top1_top3_hit=0,top3_captured=0,top6_captured=0,runners=n) for x,n in [(.1,10),(.3,18)]]
    assert mean_metrics(metrics)["brier"] == pytest.approx(.2)


def test_prediction_does_not_read_target_outcomes():
    """当該の正解を変えても予測確率は変わらず合計3を維持する。"""
    cfg = {"minimum_prior_races":5,"groups":{"part":["x"]}}
    def example(day):
        """集計器の時点検査用の合成競走を作る。"""
        return dict(race_date=day,race_key=day,venue_code="08",evaluation_eligible=True,
                    rows=[dict(horse_no=str(i),horse_id=str(i),horse_name=str(i),values={"x":str(i%2)},outcome={"top3":i<=3}) for i in range(1,7)])
    prior = [example(f"{year}-11-15") for year in range(2010,2015)]
    target = example("2020-11-15")
    c = dict(pattern="test",family="specific",weights=[1],scale=1)
    before = predict(target,prior,cfg,c)[0]
    changed=deepcopy(target)
    for row in changed["rows"]: row["outcome"]["top3"] = not row["outcome"]["top3"]
    assert predict(changed,prior+[example("2021-11-15")],cfg,c)[0] == before
    assert sum(r["probability_top3"] for r in before["runners"]) == pytest.approx(3)


def test_other_series_data_is_rejected_before_scoring():
    """別重賞のデータを流用して固有候補を選ぶ処理を拒否する。"""
    data = {"history":[], "target_rows":[], "targets":[], "race_conditions":{}}
    for year in range(2003,2026):
        key = f"{year}11150811"
        data["targets"].append(dict(race_key=key,race_date=f"{year}-11-15",venue_code="08",
                                    metadata=json.dumps(dict(race_name="マイルチャンピオンシップ",distance_raw="1600",track_code="18"))))
        data["race_conditions"][key] = dict(grade="A",weight_rule="4")
    with pytest.raises(ResearchError, match="specific_target_scope"):
        make_examples(data,"fukushima",CONFIG)
