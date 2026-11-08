"""概要: 30仮説の時点・尤度勾配・PL・再開改ざん・会計を検証する。
作成日: 2026-10-22
入力: 合成競走と一時ディレクトリ。実SQLは使用しない。
出力: pytestの検証結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_chimera_thirty.py
注意事項: 外部通信・実購入・既存runの変更なし。
"""
from copy import deepcopy
from datetime import date
import json

import numpy as np
import pytest
from scipy.optimize import check_grad

from jra_srb import jra_research_chimera_thirty as research
from jra_srb import jra_research_chimera_thirty_features as features
from jra_srb import jra_research_chimera_thirty_model as model
from jra_srb.jra_research_contracts import ResearchError


def record(index=0, n=8):
    """30方式すべてを学習できる有限な合成競走を返す。"""
    rng = np.random.default_rng(241+index)
    market = rng.uniform(.1, 1, n*(n-1)//2)
    market /= market.sum()
    return {'race_key': f'202401{index+1:02d}010101', 'race_date': f'2024-01-{index+1:02d}',
            'x': rng.normal(size=(n, 12)).astype(np.float32),
            'addition': rng.normal(size=(n, features._column)).astype(np.float32),
            'basic': rng.normal(size=(n, 8)).astype(np.float32), 'market': market,
            'pl': features.pl_pairs(rng.uniform(.1, 1, n)), 'styles': rng.uniform(0, 1, n),
            'density': .3, 'group': index % 4, 'winner': index % len(market),
            'prices': 1/market, 'payout_yen': 2000, 'market_sha256': 'a', 'win_sha256': 'b', 'hr_sha256': 'c'}


def test_pl_and_top_two_marginal():
    """PLが順序を周辺化し、2着内周辺確率の和が2となることを確認する。"""
    win = np.array([.6, .3, .1])
    q = features.pl_pairs(win)
    assert q[0] == pytest.approx(.6*.3/.4+.3*.6/.7)
    assert q.sum() == pytest.approx(1)
    assert features.marginal(q, 3).sum() == pytest.approx(2)
    assert not np.allclose(q, np.array([.18, .06, .03])/.27)


@pytest.mark.parametrize('case', ['R1', 'J01', 'J25', 'J27', 'J29'])
def test_analytic_gradient(case):
    """通常・階層縮約・減衰・群頑健の勾配を数値微分と照合する。"""
    data = model.pack([record(i) for i in range(8)], case)
    beta = np.random.default_rng(241).normal(0, .01, data['x'].shape[1])
    error = check_grad(lambda b: model.objective(b, data, case)[0],
                       lambda b: model.objective(b, data, case)[1], beta)
    assert error < 2e-5


def test_all_cases_fit_predict_without_results():
    """30方式の推論が正規化され、現結果・払戻の変更に依存しないことを確認する。"""
    records = [record(i) for i in range(8)]
    predictions = []
    base = None
    for case in ('R1', *model.CASES):
        if case == 'J26':
            fitted = {'case': case, 'base': base, 'weight': model.confidence([])}
        elif case == 'J30':
            fitted = model.fit_stack([[.1]*30, [.2]*30])
        else:
            fitted = model.fit(records, case)
        if case == 'J01':
            base = fitted
        clean = model.clean_record(records[0])
        components = [records[0]['market'], *predictions[-29:]] if case == 'J30' else None
        p = model.predict(fitted, clean, components)
        mutated = deepcopy(records[0])
        mutated.update(winner=17, payout_yen=99999999, race_date='2099-12-31')
        assert np.array_equal(p, model.predict(fitted, model.clean_record(mutated), components))
        assert p.sum() == pytest.approx(1)
        assert (p > 0).all()
        predictions.append(p)


def test_training_scale_does_not_see_future():
    """尺度が訓練競走だけから計算されることを確認する。"""
    train = [record(i) for i in range(4)]
    fitted = model.fit(train, 'J01')
    expected = np.maximum(np.std(model.pack(train, 'J01')['x'], axis=0, dtype=np.float64), 1e-5)
    assert np.allclose(fitted['scale'], expected, atol=1e-12, rtol=1e-12)
    assert fitted['trained_through'] == '2024-01-04'


def test_stack_cold_start_and_prior_oos_only():
    """OOSなしは市場100%、過去OOSの重みは非負・和1であることを確認する。"""
    assert np.array_equal(model.fit_stack([])['weights'], np.r_[1., np.zeros(29)])
    history = np.full((40, 30), .01)
    history[:, 2] = .1
    fitted = model.fit_stack(history)
    assert fitted['weights'].sum() == pytest.approx(1)
    assert (fitted['weights'] >= 0).all()
    assert fitted['weights'][2] > .99
    assert model.confidence([]) == .5
    assert model.confidence([.1]) < .01


def test_checkpoint_roundtrip_and_tamper(tmp_path):
    """保存後再開が同じ予測を戻し、会計改ざんを拒否することを確認する。"""
    records = [record(i) for i in range(3)]
    fitted = model.fit(records, 'J01')
    p = [model.predict(fitted, model.clean_record(r)) for r in records]
    cell = research.save_cell(tmp_path, '2024-02', 'J01', fitted, records, p, 'fixed')
    path = tmp_path/'2024-02_J01.json'
    restored, _ = research.read_cell(path, 'fixed', research.cohort_hash(records))
    assert restored == cell
    assert restored['reload_checks'] == 3
    changed = json.loads(path.read_text(encoding='utf-8'))
    changed['rows'][0]['payout'] += 600
    path.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(ResearchError, match='thirty_checkpoint_changed'):
        research.read_cell(path, 'fixed', research.cohort_hash(records))


def test_accounting_and_missing_roi():
    """一口100円のHRを600円へ換算し、購入ゼロのROIを未定義とする。"""
    r = record()
    p = np.full(28, .3/27)
    p[0] = .7
    r['winner'] = 0
    r['prices'] = np.full(28, 2.)
    r['prices'][0] = 10
    row = research.measure(r, p)
    assert row['stake'] == 600 and row['payout'] == 12000
    r['prices'][:] = 2
    assert research.summary([research.measure(r, p)])['roi'] is None


def test_previous_day_mechanisms_ignore_current_results():
    """追加特徴の生成が現着順・時計・当日ラップに依存しないことを確認する。"""
    r = {'ordinal': date(2024, 1, 1).toordinal(), 'surface': 0, 'distance': 1600, 'course': 1,
         'runners': [{'horse_id': str(i), 'age': 3, 'weight': 55, 'frame': i+1} for i in range(8)]}
    state = features.MechanismStates()
    public = {'x': np.zeros((8, 9))}
    a = state.public(r, None, public)
    other = deepcopy(r)
    other['pace'] = -10000
    for runner in other['runners']:
        runner.update(rank=99, closing=1, trainer_code='99999', jockey='99999')
    b = state.public(other, None, public)
    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[1], b[1])


def test_thirty_calendar_months_and_no_seed_repeats():
    """30回が異なる暦月であり、24選抜＋6確認となることを確認する。"""
    assert len(set(research.MONTHS)) == 30
    assert research.MONTHS[0] == '2024-04'
    assert research.MONTHS[23] == '2026-03'
    assert research.MONTHS[-1] == '2026-09'
    assert len(model.CASES)*len(research.MONTHS) == 900


def test_abnormal_run_is_censored_not_defeat():
    """異常走の存在だけを保存し、時計・順位・能力履歴を作らない。"""
    state = features.MechanismStates()
    day = date(2024, 1, 1).toordinal()
    update = ({'ordinal': day, 'runners': [{'horse_id': 'horse'}]}, {}, 0, 'abnormal', None)
    state.update_day([update], features.previous.TwentyStates())
    assert state.abnormal['horse'] == (1, day)
    assert not state.last and not state.small and not state.class_clocks


def test_same_day_history_is_rejected():
    """同日結果が追加履歴へ入っていれば、予測を続けず停止する。"""
    state = features.MechanismStates()
    r = {'ordinal': 100, 'surface': 0, 'distance': 1600, 'course': 1,
         'runners': [{'horse_id': 'x', 'age': 3, 'weight': 55, 'frame': 1}]}
    state.last['x'] = [{'day': 100, 'corner': .5}]
    with pytest.raises(ResearchError, match='thirty_same_day_history'):
        state.public(r, None, {'x': np.zeros((1, 9))})


def test_small_field_history_preserves_rank_and_identity():
    """正常小頭数だけを戻し、順位0や馬ID重複の履歴を拒否する。"""
    ra = bytearray(b' '*1272)
    ra[705:707], ra[697:701], ra[634:637] = b'11', b'1600', b'005'
    source = {'RA': (1, 'sha', bytes(ra)), 'conflict': False, 'SE': {}}
    for i in range(1, 5):
        se = bytearray(b'0'*555)
        se[28:30] = f'{i:02d}'.encode()
        se[30:40] = f'{i:010d}'.encode()
        se[334:336] = f'{i:02d}'.encode()
        source['SE'][f'{i:02d}'] = (1, 'sha', bytes(se))
    parsed = features.historical_small('20240101010101', source)
    assert len(parsed['runners']) == 4
    bad = deepcopy(source)
    se = bytearray(bad['SE']['01'][2])
    se[334:336] = b'00'
    bad['SE']['01'] = (1, 'sha', bytes(se))
    assert features.historical_small('20240101010101', bad) is None


def test_confirmation_cannot_change_selection():
    """最後6か月の別案が高成績でも24か月で固定した候補を変えない。"""
    cells = []
    row = research.measure(record(), record()['market'])
    for month in research.MONTHS:
        for case in model.CASES:
            copied = dict(row)
            copied['loss'] = 1 if case == 'J07' else 2
            if month in research.MONTHS[24:] and case == 'J02':
                copied['loss'] = .01
            cells.append({'month': month, 'case': case, 'rows': [copied], 'cell_sha256': month+case})
    assert research.lock_selection(cells)['candidate'] == 'J07'


def test_paired_bootstrap_rejects_misaligned_races():
    """対応のない競走同士を損益差として比較しない。"""
    row = research.measure(record(), record()['market'])
    other = dict(row, race_key='different')
    with pytest.raises(ResearchError, match='thirty_paired_cohort'):
        research.intervals([row], [other], [row], 30)
