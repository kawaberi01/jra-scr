"""概要: 東スポ杯の未来遮断・欠測・経路分類・固定候補数を検査する。
作成日: 2026-11-22
入力: 人工の競走と事前履歴。
出力: pytestの検査結果。
実行例: uv run python -m pytest -q tests/test_jra_tokyo_sports_patterns.py
注意事項: 外部通信・DB書込・実購入なし。
"""

from jra_srb.jra_tokyo_sports_patterns import features, race_class, rule_catalogue, rule_value, tri_and, tri_or, options


def sample() -> tuple[dict,dict,list[dict]]:
    """新馬勝利を一走だけ持つ人工馬を返す。"""
    race={'race_date':'2026-11-23'};runner={'horse_id':'2024100001'}
    history=[{'horse_id':runner['horse_id'],'race_key':'202609010505','race_date':'2026-09-01','status':'active',
        'conditions_verified':True,'condition_code':'701','race_name':'','grade':'','distance':1800,'track_code':'11','rank':1,'venue_code':'05'}]
    return race,runner,history


def test_future_and_same_day_results_do_not_change_features():
    """対象日と未来の結果が特徴へ入らないことを確認する。"""
    race,r,h=sample();base=features(race,r,h)
    for day in ('2026-11-23','2026-12-01'):
        assert features(race,r,h+[dict(h[0],race_date=day,rank=18)])==base


def test_withdrawal_is_not_a_career_start():
    """取消・除外をキャリアと全勝の実績へ混入させない。"""
    race,r,h=sample();f=features(race,r,h+[dict(h[0],race_date='2026-10-01',status='excluded',rank=None)])
    assert f['career_count_observed']==1 and f['atoms']['all_wins'] is True


def test_incomplete_first_history_is_unknown():
    """初走不明の収録を全キャリアと断定しない。"""
    race,r,h=sample();h[0]['condition_code']='703'
    f=features(race,r,h);assert f['atoms']['career_le3'] is None and f['atoms']['never_below3'] is None


def test_abnormal_finish_does_not_prove_all_top3():
    """中止等の着順欠測は全走好走の肯定材料にしない。"""
    race,r,h=sample();h.append(dict(h[0],race_key='202610010505',race_date='2026-10-01',rank=None))
    assert features(race,r,h)['atoms']['never_below3'] is None


def test_zero_preserving_three_value_conditions():
    """ANDと救済ORの真偽を欠測から区別する。"""
    assert tri_and([True,None]) is None and tri_and([False,None]) is False
    assert tri_or([False,None]) is None and tri_or([True,None]) is True


def test_verified_debut_and_unwon_class_codes():
    """空の競走名とメイクデビュー表記でも根拠付き分類が一致する。"""
    assert race_class({'conditions_verified':True,'condition_code':'701'})=='新馬'
    assert race_class({'conditions_verified':True,'condition_code':'703'})=='未勝利'
    assert race_class({'conditions_verified':True,'race_name':'メイクデビュー京都'})=='新馬'
    assert race_class({'conditions_verified':False,'condition_code':'701'}) is None


def test_fixed_rules_and_candidates():
    """固定28条件と32候補が重複せず、交差条件が真になることを確認する。"""
    rules=rule_catalogue();assert len(rules)==len({r['id'] for r in rules})==28
    assert len(options())==len({r['pattern'] for r in options()})==32
    race,r,h=sample();atoms=features(race,r,h)['atoms']
    assert rule_value(atoms,next(x for x in rules if x['id']=='prev_win&prev1800')) is True


def test_layoff_boundaries():
    """境界日数が連続して計算されることを確認する。"""
    race,r,h=sample();f=features(race,r,h)
    assert f['gap_days']==83 and f['atoms']['gap28_84'] is True
