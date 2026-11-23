"""概要: 不的中後研究の頭数補正・特徴境界・市場参考確率を検証する。
作成日: 2026-11-15
入力: 合成競走・既知の重み・日数。
出力: pytest結果。
実行例: uv run pytest -q tests/test_jra_miss_refinement.py
注意事項: 外部通信・実DB・モデル設定変更なし。
"""

import importlib.util
from itertools import permutations
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(SCRIPTS))
try:
    import run_jra_miss_refinement as refinement
    import run_jra_market_assistance as assistance
finally:
    sys.path.pop(0)


def race(key, n, category=None):
    """先頭3頭が好走した合成競走を作る。"""
    return dict(race_key=key,race_date=key,venue_code="08",evaluation_eligible=True,
                rows=[dict(horse_no=str(i+1),horse_id=str(i+1),horse_name="h"+str(i+1),
                           values=dict(x=category if category else ("A" if i%2==0 else "B")),
                           outcome=dict(top3=i<3)) for i in range(n)])


def test_field_size_confounding_removed():
    """小頭数と大頭数の基礎確率の違いだけなら補正後の加点は0となる。"""
    prior=[race("2020",8,"A"),race("2021",16,"B")]
    target=race("2022",8)
    config=dict(minimum_prior_races=1,groups={"group":["x"]})
    raw=refinement.adjusted_deltas(prior,target,config,0)
    adjusted=refinement.adjusted_deltas(prior,target,config,1)
    assert raw[0]["deltas"][0]>0 and raw[1]["deltas"][0]<0
    assert all(abs(h["deltas"][0])<1e-12 for h in adjusted)


def test_constant_field_size_reproduces_original():
    """全競走同じ頭数なら補正は元の加点を変更しない。"""
    prior=[race("2020",8),race("2021",8)]
    target=race("2022",8)
    config=dict(minimum_prior_races=1,groups={"group":["x"]})
    a=refinement.adjusted_deltas(prior,target,config,0)
    b=refinement.adjusted_deltas(prior,target,config,1)
    assert [h["deltas"][0] for h in a]==pytest.approx([h["deltas"][0] for h in b])


@pytest.mark.parametrize("days,label",[(28,"28日以下"),(29,"29〜56日"),(56,"29〜56日"),
                                      (57,"57〜90日"),(90,"57〜90日"),(91,"91〜149日"),
                                      (149,"91〜149日"),(150,"150日以上"),(175,"150日以上")])
def test_interval_boundaries(days,label):
    """150日以上の長期区分を含むすべての境界を検査する。"""
    assert refinement.gap_category(days)==label


def test_market_uniform_and_permutation():
    """一様重みは3/Nで、入力順を変えても対応する確率は変わらない。"""
    assert assistance.market_top3([1]*8)==pytest.approx([3/8]*8)
    original=assistance.market_top3([1,2,3,4])
    assert assistance.market_top3([4,3,2,1])==pytest.approx(original[::-1])
    assert original==sorted(original)


def test_market_exact_order_enumeration():
    """独立した上位3順序の列挙で周辺確率を照合する。"""
    weights=[1,2,4,8]
    expected=[0.]*4
    total=sum(weights)
    for a,b,c in permutations(range(4),3):
        p=weights[a]/total*weights[b]/(total-weights[a])*weights[c]/(total-weights[a]-weights[b])
        for index in (a,b,c):expected[index]+=p
    assert assistance.market_top3(weights)==pytest.approx(expected)


def test_blend_endpoints_and_sum():
    """混合の端点と合計3を保持し、確率を順位に見せ替えない。"""
    core=[.9,.8,.7,.6]
    market=assistance.market_top3([1,2,3,4])
    assert assistance.blend(core,market,0)==core
    assert assistance.blend(core,market,1)==market
    assert sum(assistance.blend(core,market,.25))==pytest.approx(3)


@pytest.mark.parametrize("weights",[[1,2,3],[1,0,2,3],[1,2,float("nan"),3]])
def test_invalid_market_rejected(weights):
    """欠けた重みや非有限値を価格0へ置換しない。"""
    with pytest.raises(ValueError):assistance.market_top3(weights)
