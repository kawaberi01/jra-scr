"""概要: 全資料監査の同一走人気結合、三値判定、対象年境界を検証する。
作成日: 2026-11-22
入力: 外部接続しない最小競走と公式成績リンク。
出力: pytest判定。
実行例: uv run python -m pytest tests/test_mile_raw_materials.py -q
注意事項: 通信・DB更新なし。
"""

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from audit_mile_raw_materials import RULES, catalogue, rule_features, summarize


def fixture_data():
    """実績と人気が異なる二つのGI過去走を用意する。"""
    race={"race_key":"target","race_date":"2026-11-22"}
    runner={"horse_id":"x","age":5,"sex":"1","frame_no":8}
    history=[{"horse_id":"x","race_key":key,"race_date":day,"race_name":"安田記念","rank":rank,"status":"active","grade":"A","distance":1600,"track_code":"11","venue_code":"05"}
             for key,day,rank in (("win","2025-06-01",1),("loss","2026-06-01",2))]
    links={("win","x"):"w",("loss","x"):"l"}
    facts={"w":{"record_id":"w","values":{"popularity":8}},"l":{"record_id":"l","values":{"popularity":1}}}
    return race,runner,history,links,facts


def test_popularity_must_belong_to_winning_g1():
    """別の走の人気をGI勝利条件へ結合しない。"""
    race,runner,h,links,facts=fixture_data()
    f=rule_features(race,runner,h,[],links,facts,{"popularity":1,"win_odds":3.})
    assert f["conditions"]["specified_g1_win5_male6"] is False
    facts['w']['values']['popularity']=2
    assert rule_features(race,runner,h,[],links,facts,{})['conditions']['specified_g1_win5_male6'] is True


def test_unknown_g1_popularity_and_sex_constraint():
    """勝利時人気欠測は不明、牝馬なら複合条件は明示的に非該当となる。"""
    race,runner,h,links,facts=fixture_data()
    facts['w']['values']['popularity']=None
    assert rule_features(race,runner,h,[],links,facts,{})['conditions']['specified_g1_win5_male6'] is None
    runner['sex']='2'
    assert rule_features(race,runner,h,[],links,facts,{})['conditions']['specified_g1_win5_male6'] is False


def test_outer_threshold_and_future_exclusion():
    """19.9境界を固定し、対象当日のGI勝利を実績へ入れない。"""
    race,runner,h,links,facts=fixture_data()
    h.append({**h[0],'race_key':'today','race_date':'2026-11-22'})
    a=rule_features(race,runner,h,[],links,facts,{'win_odds':19.9})
    b=rule_features(race,runner,h,[],links,facts,{'win_odds':20.0})
    assert a['conditions']['outer_price'] is True and b['conditions']['outer_price'] is False
    assert a['previous']['race_key']=='loss'


def test_catalog_all_files_and_rule_links():
    """4資料すべてが台帳にあり、未実装救済を検証済みとしない。"""
    rows=catalogue()
    assert {r['file'] for r in rows}=={'MC条件1.txt','MC条件2.txt','MC条件3.txt','MC条件ゆっくり.txt'}
    assert {r['rule_id'] for r in rows if r['rule_id']}=={r[0] for r in RULES}
    breeder=[r for r in rows if '社台系' in r['claim']]
    assert breeder and all(r['rule_id']=='g2_breeder_rescue' for r in breeder)


def test_breeder_rescue_preserves_unknown():
    """親群の前走GII勝利でも生産者不明なら救済/割引を断定しない。"""
    race,runner,h,links,facts=fixture_data()
    h=[{**h[0],'race_key':'g2','race_date':'2026-10-01','grade':'B','venue_code':'08','race_name':'スワンステークス'}]
    f=rule_features(race,runner,h,[],links,facts,{})
    assert f['conditions']['g2_breeder_rescue'] is None
    assert f['conditions']['outside_after_breeder_rescue'] is None
    g=rule_features(race,runner,h,[],links,facts,{}, {'x':{'breeder':'追分ファーム'}})
    assert g['conditions']['g2_breeder_rescue'] is True
    assert g['conditions']['outside_after_breeder_rescue'] is False
