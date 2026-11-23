"""概要: 直接対決の時点・条件・欠測・相手別直近化と追加スコアを検証する。
作成日: 2026-11-21
入力: 合成した出走馬と過去対戦。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_head_to_head.py
注意事項: 外部通信・SQL・当日結果・保存研究データを参照しない。
"""

from datetime import date, timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jra_srb.jra_head_to_head import features, add_scores
from jra_srb.jra_race_conditions import probabilities
from jra_srb.jra_research_contracts import ResearchError

CONFIG = dict(lookback_days=730, distance_tolerance_m=200)
RACE = dict(race_date="2025-11-16", race_key="202511160311", venue_code="03", distance=2000)
RUNNERS = [dict(horse_id=h, horse_name=h, horse_no=str(i+1)) for i, h in enumerate(["A", "B", "C", "D"])]


def meeting(day="2025-10-01", distance=2000, ranks=(1, 2), **changes):
    """2頭が同一競走へ出走した履歴を生成する。"""
    return [dict(dict(horse_id=h, race_date=day, race_key=day+"0311", venue_code="03", distance=distance,
                      track_code="17", status="active", rank=rank, weight_carried=weight), **changes)
            for h, rank, weight in zip(["A", "B"], ranks, [58., 56.])]


def test_no_meeting_is_unknown_not_a_loss():
    """未対戦の馬を後着とせず欠測にする。"""
    output = features(RACE, RUNNERS, meeting(), CONFIG)
    assert output["A"]["values"]["h2h_all_turf"] == "先着優勢"
    assert output["B"]["values"]["h2h_all_turf"] == "後着多い"
    assert all(v is None for v in output["C"]["values"].values())
    assert output["A"]["meetings"]["h2h_all_turf"][0]["weight_difference"] == 2


def test_latest_per_opponent_and_distance_are_selected_separately():
    """相手別直近に限定し、全芝と近距離で別の対戦を採用できる。"""
    history = meeting(day="2025-08-01", ranks=(1,2)) + meeting(day="2025-10-01", distance=1600, ranks=(3,1))
    output = features(RACE, RUNNERS, history, CONFIG)["A"]
    assert output["values"] == {"h2h_all_turf":"後着多い", "h2h_near_distance":"先着優勢"}
    assert len(output["meetings"]["h2h_all_turf"]) == 1


def test_future_and_same_day_do_not_change_any_features():
    """対象日・未来の対戦順位を特徴へ取り込まない。"""
    expected = features(RACE,RUNNERS,meeting(),CONFIG)
    more = meeting()+meeting(day=RACE["race_date"],ranks=(18,1))+meeting(day="2026-01-01")
    assert features(RACE,RUNNERS,more,CONFIG) == expected


@pytest.mark.parametrize("days,eligible", [(730,True),(731,False)])
def test_lookback_boundary(days,eligible):
    """固定730日を含め、範囲外を除く。"""
    day=(date.fromisoformat(RACE["race_date"])-timedelta(days=days)).isoformat()
    values=features(RACE,RUNNERS,meeting(day=day),CONFIG)["A"]["values"]
    assert (values["h2h_all_turf"] is not None) == eligible


@pytest.mark.parametrize("distance,near", [(1800,True),(2200,True),(1799,False),(2201,False)])
def test_distance_boundary(distance,near):
    """今回距離±200mの境界を固定どおり判定する。"""
    values=features(RACE,RUNNERS,meeting(distance=distance),CONFIG)["A"]["values"]
    assert (values["h2h_near_distance"] is not None) == near


def test_draw_invalid_ranks_withdrawal_and_dirt():
    """同着は均衡、中止・取消・ダートは優劣集計に入れない。"""
    assert features(RACE,RUNNERS,meeting(ranks=(2,2)),CONFIG)["A"]["values"]["h2h_all_turf"] == "均衡"
    for history in [meeting(ranks=(None,1)),meeting(status="excluded"),meeting(track_code="24")]:
        assert features(RACE,RUNNERS,history,CONFIG)["A"]["values"]["h2h_all_turf"] is None


def test_unrelated_horse_and_conflicting_conditions():
    """今回不出走の馬を相手に数えず、同一競走の条件矛盾を拒否する。"""
    assert all(v is None for v in features(RACE,RUNNERS[:1],meeting(),CONFIG)["A"]["values"].values())
    h=meeting(); h[1]["distance"]=1800
    with pytest.raises(ResearchError,match="h2h_race_condition_conflict"):
        features(RACE,RUNNERS,h,CONFIG)


def test_missing_effect_does_not_shrink_to_uniform():
    """対戦差分0なら既存スコアを保ち、一律確率混合による減点をしない。"""
    base=[{**r,"deltas":[float(i),float(i)/2]} for i,r in enumerate(RUNNERS)]
    added=[{**r,"deltas":[0.]} for r in RUNNERS]
    p=add_scores(base,added,RACE,"test",.5,None)
    expected=dict(zip([r["horse_id"] for r in RUNNERS],probabilities([sum(r["deltas"])/2 for r in base])))
    assert all(r["probability_top3"] == expected[r["horse_id"]] for r in p["runners"])
    assert sum(r["probability_top3"] for r in p["runners"]) == pytest.approx(3)
