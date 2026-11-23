"""概要: 公式時計差・末脚の時点、欠測、同着と確率追加を検証する。
作成日: 2026-11-22
入力: 人工的な公式成績と履歴。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_material_patterns.py
注意事項: 外部通信・DB書込みなし。
"""

import pytest
from jra_srb.jra_material_patterns import measures,feature,combine
from jra_srb.jra_research_contracts import ResearchError


def fact(rank,time,late,rid="r"):
    """必要な型付き列を持つテスト成績を返す。"""
    return {"record_id":rid,"race_key":"202610170511","values":{"finish_rank":rank,"finish_time_seconds":time,"final_3f_seconds":late},"fields":{}}


def history(day="2026-10-17",key="202610170511"):
    """対象日前の芝1600mGI履歴を返す。"""
    return {"horse_id":"h","race_date":day,"race_key":key,"race_name":"GI","grade":"A","track_code":"11","distance":1600,"status":"active","rank":2}


def test_same_race_gap_and_percentile():
    """時計差は同一レースの勝ち馬との差で、上がりは平均同順位を使う。"""
    a=fact(1,"92.0","33.0"); b=fact(2,"92.4","33.0"); c=fact(3,"93.0","34.0")
    m=measures(b,[a,b,c])
    assert m["gap_seconds"]==pytest.approx(.4)
    assert m["final3f_percentile"]==pytest.approx(.5)


def test_negative_gap_stops():
    """勝ち馬より速い後着時計は不整合として停止する。"""
    with pytest.raises(ResearchError):measures(fact(2,"91.0","33"),[fact(1,"92.0","34"),fact(2,"91.0","33")])


def test_80percent_boundary_and_missing_time():
    """80%未満は末脚を欠測とし、時計欠測を0差にしない。"""
    field=[fact(i,"92",str(32+i) if i<5 else None) for i in range(1,6)]
    assert measures(field[0],field)["final3f_percentile"] is not None
    field[3]["values"]["final_3f_seconds"]=None
    assert measures(field[0],field)["final3f_percentile"] is None
    field[1]["values"]["finish_time_seconds"]=None
    assert measures(field[1],field)["gap_seconds"] is None


def test_latest_missing_does_not_fallback():
    """直近GIの値が欠けても古い好走で代用しない。"""
    old=history("2026-06-07","202606070511"); new=history()
    f=fact(1,"92","33"); f["race_key"]=old["race_key"]
    r=feature({"race_date":"2026-11-22"},{"horse_id":"h"},[old,new],[f],[{"race_key":old["race_key"],"horse_id":"h","record_id":"r"}],[])
    assert r["values"]=={"g1_gap":None,"g1_final3f":None}
    assert r["previous"]["race_key"]==new["race_key"]


def test_future_excluded():
    """当日および将来の好走を予想入力へ使わない。"""
    r=feature({"race_date":"2026-11-22"},{"horse_id":"h"},[history("2026-11-22"),history("2027-01-01")],[],[],[])
    assert r["values"]["g1_gap"] is None and r["previous"] is None


@pytest.mark.parametrize("rank,clock,expected",[(1,"1:33.0","同時計（表示精度内）"),(2,"1:33.0",None),(1,"不明",None),(1,"0:00.0",None)])
def test_foreign_limited_evidence(rank,clock,expected):
    """海外勝利でも有効な自馬時計のない場合や後着の時計差は作らない。"""
    foreign=[{"horse_id":"h","race_date":"2026-09-06","race_name_raw":"海外GI","international_grade_raw":"GI","surface_raw":"芝","distance":1600,"rank":rank,"source_row_cells":[None]*11+[clock]}]
    r=feature({"race_date":"2026-11-22"},{"horse_id":"h"},[],[],[],foreign)
    assert r["values"]["g1_gap"]==expected
    assert r["values"]["g1_final3f"] is None


def test_neutral_added_group_preserves_probabilities():
    """欠測相当の追加0では元確率が維持される。"""
    rows=[{"horse_id":str(i),"horse_no":str(i),"probability_top3":.5} for i in range(1,7)]
    evidence=[{"horse_id":r["horse_id"],"deltas":[0,0]} for r in rows]
    new=combine({"runners":rows},evidence,"both",(0,1))
    assert [r["probability_top3"] for r in new["runners"]]==pytest.approx([.5]*6)


def test_same_display_clock_not_same_finish_rank():
    """表示時計差0の後着馬を勝利/同着と表現しない。"""
    winner=fact(1,"92.1","33.0","winner");own=fact(2,"92.1","33.1","own")
    h=history();r=feature({"race_date":"2026-11-22"},{"horse_id":"h"},[h],[winner,own],[{"race_key":h["race_key"],"horse_id":"h","record_id":"own"}],[])
    assert r["values"]["g1_gap"]=="同時計（表示精度内）"
    assert r["previous"]["rank"]==2
