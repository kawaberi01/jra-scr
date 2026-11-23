"""概要: 格×着順と再対戦斤量の符号・欠測・未来遮断・追加計算を検証する。
作成日: 2026-11-21
入力: 合成前走・合成対戦・固定パーツ設定。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_context_interactions.py
注意事項: SQL・外部通信・当日結果・保存研究データに依存しない。
"""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from jra_srb.jra_context_interactions import class_rank, rematch_weight, weight_band, variants, prediction
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_race_conditions import probabilities

RACE=dict(race_date="2025-11-16",race_key="202511160311",venue_code="03",distance=2000)
RUNNER=dict(horse_id="A",weight_carried=56.)
ROSTER=[RUNNER,dict(horse_id="B",weight_carried=56.),dict(horse_id="C",weight_carried=57.)]
CONFIG=dict(weight_band_kg=1.)


def past(**changes):
    """対象日前の確認済み前走を生成する。"""
    return dict(dict(horse_id="A",race_date="2025-10-01",race_key="202510010311",status="active",rank=5,grade="B",ra_verified=True),**changes)


def meeting(**changes):
    """過去に相手Bへ後着し、自馬が2kg重かった対戦を生成する。"""
    return dict(dict(opponent_id="B",own_weight=58.,opponent_weight=56.,comparison=-1,race_key="202510010311"),**changes)


@pytest.mark.parametrize("grade,rank,label",[("A",1,"A|1着"),("B",3,"B|2〜3着"),("C",5,"C|4〜5着"),("",10,"非ABC|6着以下")])
def test_grade_and_rank_are_joint_categories(grade,rank,label):
    """同じ順位でも格により異なる結合カテゴリを作る。"""
    assert class_rank(RACE,RUNNER,[past(grade=grade,rank=rank)])["values"]["class_rank"]==label


@pytest.mark.parametrize("changes",[{"grade":None},{"ra_verified":False},{"rank":None},{"rank":0},{"status":"excluded"}])
def test_unconfirmed_class_and_rank_are_missing(changes):
    """不明や取消を非重賞・凡走へ置換しない。"""
    assert class_rank(RACE,RUNNER,[past(**changes)])["values"]["class_rank"] is None


def test_class_does_not_read_same_day_or_future_or_other_horse():
    """同日・未来の好走や別馬の成績で前走を上書きしない。"""
    expected=class_rank(RACE,RUNNER,[past()])
    h=[past(),past(race_date=RACE["race_date"],rank=1,grade="A"),past(race_date="2026-01-01",rank=1),past(horse_id="B",race_date="2025-11-01")]
    assert class_rank(RACE,{**RUNNER,"rank":18},h)==expected
    assert class_rank(RACE,RUNNER,[])["values"]["class_rank"] is None


@pytest.mark.parametrize("value,label",[(-1.0,"相対軽化"),(-.5,"概ね同じ"),(0.,"概ね同じ"),(.5,"概ね同じ"),(1.,"相対重化"),(None,None)])
def test_weight_band_boundaries(value,label):
    """±1kgの境界と欠測を区別する。"""
    assert weight_band(value,1.)==label


def test_relative_weight_uses_both_horses_and_correct_sign():
    """自馬の絶対斤量変化でなく、相手との差の変化で軽化を判定する。"""
    before=deepcopy(ROSTER)
    result=rematch_weight(RUNNER,ROSTER,[meeting()],CONFIG)
    assert result["relative_change_means"]["lost_relative_weight"]==-2.
    assert result["values"]["lost_relative_weight"]=="相対軽化"
    assert result["values"]["won_relative_weight"] is None
    evidence=result["weight_meetings"]["lost_relative_weight"][0]
    assert evidence["relative_before"]==2. and evidence["relative_now"]==0.
    assert ROSTER==before
    changed=[dict(horse_id="A",weight_carried=56.),dict(horse_id="B",weight_carried=53.)]
    assert rematch_weight(RUNNER,changed,[meeting()],CONFIG)["values"]["lost_relative_weight"]=="相対重化"


def test_wins_losses_and_ties_are_separate():
    """先着・後着を分けて相手を等配分し、同着は混ぜない。"""
    history=[meeting(),meeting(opponent_id="C",comparison=1,own_weight=56.,opponent_weight=56.)]
    r=rematch_weight(RUNNER,ROSTER,history,CONFIG)
    assert r["values"]=={"lost_relative_weight":"相対軽化","won_relative_weight":"相対軽化"}
    r=rematch_weight(RUNNER,ROSTER,[meeting(comparison=0)],CONFIG)
    assert all(v is None for v in r["values"].values()) and r["ignored_meetings"][0]["reason"]=="past_tie"


@pytest.mark.parametrize("changes",[{"own_weight":None},{"opponent_weight":0},{"own_weight":float('nan')},{"opponent_id":"absent"}])
def test_missing_past_or_current_weight_is_not_zero(changes):
    """不明な斤量や今回不出走の相手を0kg扱いしない。"""
    r=rematch_weight(RUNNER,ROSTER,[meeting(**changes)],CONFIG)
    assert all(v is None for v in r["values"].values())


def test_latest_opponents_are_unique():
    """相手別直近の契約に反した重複入力を拒否する。"""
    with pytest.raises(ResearchError,match="interaction_duplicate_opponent"):
        rematch_weight(RUNNER,ROSTER,[meeting(),meeting()],CONFIG)


def test_all_eight_variants_keep_neutral_scores_and_probability_sum():
    """新パーツ差分0なら8方式すべてが既存一般評価を保つ。"""
    runners=[dict(horse_id=str(i),horse_no=str(i),horse_name=str(i),deltas=[i/10]*5) for i in range(1,7)]
    zero=[dict(horse_id=r["horse_id"],deltas=[0.]) for r in runners]
    evidence=dict(general=runners,h2h=zero,weight=zero,**{"class":zero})
    expected=dict(zip([r["horse_id"] for r in runners],probabilities([i/10 for i in range(1,7)])))
    options=variants()
    assert len(options)==8 and len({o["pattern"] for o in options})==8
    for option in options:
        p=prediction(evidence,RACE,option,.5)
        assert sum(r["probability_top3"] for r in p["runners"])==pytest.approx(3)
        assert all(r["probability_top3"]==pytest.approx(expected[r["horse_id"]]) for r in p["runners"])
