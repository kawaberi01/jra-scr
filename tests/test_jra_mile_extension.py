"""概要: マイル専用追加比較の未来遮断・海外接続・選択条件を検証する。
作成日: 2026-11-21
入力: 人工的な競走と公式相当の非JRAレコード。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_mile_extension.py
注意事項: 外部通信・DB書込みなし。
"""

from copy import deepcopy
import pytest

from jra_srb.jra_mile_extension import options, choose, foreign_overlay, combine, live_targets


def fixture():
    """海外実前走・国内なしの3歳馬と必要な最小構造を返す。"""
    race = {"race_key":"202611220811","race_date":"2026-11-22","venue_code":"08","distance":1600,"track_code":"18","race_name":"マイルチャンピオンシップ"}
    runner = {"horse_id":"2023190001","horse_no":"01","horse_name":"海外馬","age":3,"frame_no":1,"sex":"3","weight_carried":57.}
    foreign = {"horse_id":runner["horse_id"],"race_date":"2026-09-06","race_name_raw":"ムーラン・ド","international_grade_raw":"GI","jpn_grade_raw":None,"rank":1,"distance":1600,"surface_raw":"芝","weight_carried":56.5}
    return race,runner,foreign


def test_options_fixed():
    """基準2種×追加8種の16候補が重複しない。"""
    assert len(options()) == len({o["pattern"] for o in options()}) == 16


def test_foreign_actual_previous_without_fake_domestic_identity():
    """国内走がない場合も77日と国際GI勝利を接続し、国内実績なしと断定しない。"""
    race,r,f = fixture(); sp,ge = {"values":{}},{"values":{}}
    note = foreign_overlay(race,r,[],[f],sp,ge)
    assert note["previous_change"]["interval_days"] == 77
    assert sp["values"]["layoff"] == "57〜112日"
    assert sp["values"]["mile_g1"] == "勝利"
    assert sp["previous"]["jra_race_key"] is None
    assert sp["values"]["same_stage"] is None
    assert ge["values"]["weight_change"] == "増"
    assert ge["values"]["previous_symbol"] is None


@pytest.mark.parametrize("grade",[None,"JpnI"])
def test_unknown_or_jpn_grade_not_gi(grade):
    """国際格不明やJpnは国際GIへ変換しない。"""
    race,r,f = fixture(); f["international_grade_raw"] = grade
    f["weight_carried"] = None
    sp,ge = {"values":{}},{"values":{}}
    foreign_overlay(race,r,[],[f],sp,ge)
    assert sp["values"]["prep_grade"] is None
    assert ge["values"]["weight_change"] is None
    assert "mile_g1" not in sp["values"]


def test_foreign_future_excluded():
    """当日以後の海外成績を実前走に使わない。"""
    race,r,f = fixture(); f["race_date"] = race["race_date"]
    sp,ge = {"values":{}},{"values":{}}
    assert foreign_overlay(race,r,[],[f],sp,ge) == {"used":False}
    assert sp == {"values":{}}


def test_choose_excludes_confirmation_and_capture_regression():
    """確認年の良さや開発捕捉が低い最小Brierで選択を変えない。"""
    annual = []
    for o in options():
        for year in (2008,2009,2021):
            p = o["pattern"]
            b = .01 if p == "N+H" else .1 if p == "N+C" else .2
            annual.append({"pattern":p,"race_date":f"{year}-11-20","brier":b if year != 2021 else 0 if p == "G+W" else 1,
                "logloss":.4,"top1_top3_hit":0,"top3_captured":0 if p == "N+H" else 1,"top6_captured":2})
    selected = choose(annual,{"development":[2008,2009]})
    assert selected["selected"]["pattern"] == "N+C"
    assert "N+H" not in selected["eligible"]


def test_combine_missing_addition_neutral_and_sum_three():
    """欠測相当の差分0を追加しても確率を変えず、合計3を維持する。"""
    rows = [{"horse_id":str(i),"horse_no":str(i),"horse_name":str(i),"deltas":[i/100]*5} for i in range(1,7)]
    ev = {"G":rows,"N":rows,**{g:[{**r,"deltas":[0]} for r in rows] for g in ("H","C","W")}}
    race = {"race_key":"202611220811","race_date":"2026-11-22","venue_code":"08"}
    a = combine(race,ev,{"base":"N","mask":0,"pattern":"N"},.5)
    b = combine(race,ev,{"base":"N","mask":7,"pattern":"N+H+C+W"},.5)
    assert a["runners"] == b["runners"]
    assert sum(r["probability_top3"] for r in a["runners"]) == pytest.approx(3)


def test_live_c_uses_foreign_previous_and_h_keeps_missing():
    """海外実前走のCを接続し、国内対戦のないHは欠測にする。"""
    race,r,f = fixture(); card = {**race,"runners":[{**r,"status":"active"}]}
    targets,notes = live_targets(card,[],[f],{"lookback_days":730,"distance_tolerance_m":200,"weight_band_kg":1},True)
    assert targets["C"]["rows"][0]["values"]["class_rank"] == "A|1着"
    assert targets["H"]["rows"][0]["values"]["h2h_all_turf"] is None
