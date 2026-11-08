"""概要: J23と市場の1係数凸混合を過去OOSだけで校正し、固定選抜ゲートで停止判断する。
作成日: 2026-10-23
入力: spec260の事前protocol、既存J23/M0の月別正解ペア確率。
出力: j23_market_calibration_20261023の係数・選抜結果・診断・レポート。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/screen_j23_market_calibration_20261023.py
注意事項: 既使用期間の研究。基本モデル学習・SQL・購入・元run変更なし。選抜不合格時は確認処理をしない。
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import brentq


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT/'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'
OUT = ROOT/'artifacts/jra_research/j23_market_calibration_20261023'


def digest(value):
    """有限JSONのcanonical内容SHAを返す。"""
    s = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(s.encode()).hexdigest()


def save(name, value):
    """研究成果物をUTF-8で新規作成し、既存ファイルは上書きしない。"""
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def objective(alpha, p, q):
    """正解ペア確率の混合尤度にJ23中心の弱い固定罰則を加える。"""
    mixed = (1-alpha)*q+alpha*p
    return float(-np.log(mixed).mean()+.001*(alpha-1)**2/2)


def gradient(alpha, p, q):
    """1係数の罰則付き尤度の解析微分を返す。"""
    return float(-((p-q)/((1-alpha)*q+alpha*p)).mean()+.001*(alpha-1))


def fit(p, q):
    """凸目的の端点勾配または一意な根からalphaを求め、両端点より悪い解を拒否する。"""
    p, q = np.asarray(p), np.asarray(q)
    assert p.shape == q.shape and len(p) > 0 and np.all((p > 0)&(p <= 1)) and np.all((q > 0)&(q <= 1))
    if gradient(1., p, q) <= 0:
        alpha = 1.
    elif gradient(0., p, q) >= 0:
        alpha = 0.
    else:
        alpha = float(brentq(gradient, 0., 1., args=(p, q), xtol=1e-12))
    assert 0 <= alpha <= 1
    assert objective(alpha, p, q) <= min(objective(0, p, q), objective(1, p, q))+1e-12
    if 0 < alpha < 1:
        assert abs(gradient(alpha, p, q)) < 1e-8
    return alpha


def comparison(rows):
    """当月より前だけで校正した予測を、同じ日の原型J23と比較する。"""
    daily = defaultdict(lambda: np.zeros(2))
    for row in rows:
        daily[row['race_date']] += [row['loss']-row['J23_loss'], 1]
    values = np.asarray([v for _, v in sorted(daily.items())])
    indices = np.random.default_rng(260).integers(0, len(values), size=(2000, len(values)))
    totals = values[indices].sum(axis=1)
    bounds = np.quantile(totals[:, 0]/totals[:, 1], [.025, .975]).tolist()
    baseline = float(np.mean([r['J23_loss'] for r in rows]))
    calibrated = float(np.mean([r['loss'] for r in rows]))
    market = float(np.mean([r['M0_loss'] for r in rows]))
    return {'races': len(rows), 'days': len(values), 'J23_logloss': baseline,
            'calibrated_logloss': calibrated, 'M0_logloss': market,
            'relative_gain_vs_J23': 1-calibrated/baseline,
            'difference_vs_J23': calibrated-baseline, 'difference_95': bounds}


def self_checks():
    """端点・内点・数値微分・全分布の和1を合成値で独立確認する。"""
    assert fit(np.asarray([.8, .7]), np.asarray([.2, .1])) == 1
    assert fit(np.asarray([.1, .1]), np.asarray([.9, .8])) == 0
    p, q = np.asarray([.8, .1]), np.asarray([.2, .9])
    alpha = fit(p, q)
    assert 0 < alpha < 1
    numerical = (objective(alpha+1e-6, p, q)-objective(alpha-1e-6, p, q))/2e-6
    assert math.isclose(numerical, gradient(alpha, p, q), abs_tol=1e-8)
    a, b = np.asarray([.1, .2, .7]), np.asarray([.3, .4, .3])
    for weight in (0., alpha, 1.):
        assert np.isclose(((1-weight)*b+weight*a).sum(), 1)


def main():
    """選抜期間を先に判定し、不合格なら確認用係数を一つも作らず停止記録を保存する。"""
    self_checks()
    protocol = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    assert protocol['candidate_count'] == 1 and protocol['adjustment_rounds'] == 0
    source_files = [p for c in ('J23', 'M0') for p in sorted((SOURCE/'cells').glob('*_'+c+'.json'))]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    months = {}
    for path in sorted((SOURCE/'cells').glob('*_J23.json')):
        a = json.loads(path.read_text(encoding='utf-8-sig'))
        b = json.loads((SOURCE/'cells'/(a['month']+'_M0.json')).read_text(encoding='utf-8-sig'))
        assert a['cohort_sha256'] == b['cohort_sha256']
        for cell in (a, b):
            assert digest({k: v for k, v in cell.items() if k != 'cell_sha256'}) == cell['cell_sha256']
        market = {r['race_key']: r for r in b['rows']}
        assert len(market) == len(a['rows'])
        rows = []
        for r in a['rows']:
            q = market[r['race_key']]
            assert r['winner'] == q['winner'] and r['race_date'] == q['race_date']
            rows.append({'race_key': r['race_key'], 'race_date': r['race_date'],
                         'p': r['winning_probability'], 'q': q['winning_probability'],
                         'J23_loss': r['loss'], 'M0_loss': q['loss']})
        months[a['month']] = rows
    assert len(months) == 30
    fitted, predictions = [], []

    def evaluate_month(month):
        """対象月より前のOOSだけで1係数を学び、その月の正解確率を計算する。"""
        prior = [r for m in sorted(months) if m < month for r in months[m]]
        assert prior and all(r['race_date'] < month+'-01' for r in prior)
        alpha = fit([r['p'] for r in prior], [r['q'] for r in prior])
        fitted.append({'month': month, 'alpha': alpha, 'trained_through': max(r['race_date'] for r in prior),
                       'training_races': len(prior), 'training_cohort_sha256': digest([r['race_key'] for r in prior]),
                       'training_input_sha256': digest(prior)})
        result = []
        for r in months[month]:
            probability = (1-alpha)*r['q']+alpha*r['p']
            result.append({'race_key': r['race_key'], 'race_date': r['race_date'], 'alpha': alpha,
                           'winning_probability': probability, 'loss': -math.log(probability),
                           'J23_loss': r['J23_loss'], 'M0_loss': r['M0_loss']})
        return result

    for month in sorted(months):
        if '2024-07' <= month <= '2026-03':
            predictions.extend(evaluate_month(month))
    assert len(fitted) == 21
    selection = comparison(predictions)
    checks = {'min_races': selection['races'] >= 1000, 'min_days': selection['days'] >= 30,
              'min_relative_logloss_gain': selection['relative_gain_vs_J23'] >= .001,
              'paired_day_interval': selection['difference_95'][1] < 0,
              'not_worse_than_market': selection['calibrated_logloss'] <= selection['M0_logloss']}
    passed = all(checks.values())
    confirmation = None
    if passed:
        confirmation_rows = []
        for month in sorted(months):
            if '2026-04' <= month <= '2026-09':
                confirmation_rows.extend(evaluate_month(month))
        confirmation = comparison(confirmation_rows)
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    assert before == after
    verification = {'status': 'passed', 'synthetic_checks': True, 'source_unchanged': True,
                    'training_strictly_prior_months': all(f['trained_through'] < f['month']+'-01' for f in fitted),
                    'source_sha256': before, 'base_model_fits': 0, 'calibration_fits': len(fitted),
                    'confirmation_fits': sum(f['month'] >= '2026-04' for f in fitted),
                    'sql_queries': 0, 'independent_test': False}
    report = {'protocol': protocol, 'selection': selection, 'gate_checks': checks,
              'selection_passed': passed, 'confirmation': confirmation,
              'decision': 'proceed_to_already_seen_confirmation' if passed else 'stop_selection_gate_failed',
              'adoption': False, 'purchase_evaluated': False, 'full_Brier_evaluated': False,
              'verification': verification}
    save('calibrations.json', fitted)
    save('selection-predictions.json', predictions)
    save('results.json', report)
    lines = ['# J23と市場の単一係数校正screening', '', '2026-10-23。1案のみ、既使用期間の探索。', '',
             f"選抜: {selection['races']}競走/{selection['days']}日、21月。",
             f"J23 logloss={selection['J23_logloss']:.9f}、校正後={selection['calibrated_logloss']:.9f}。",
             f"相対改善={100*selection['relative_gain_vs_J23']:.6f}%、対応差95%区間={selection['difference_95']}。", '',
             f"固定選抜ゲート={passed}、内訳={checks}。", f"判断={report['decision']}。", '',
             '| 月 | alpha（J23反映率） | 学習最終日 | 過去OOS競走 |', '|---|---:|---|---:|']
    lines += [f"| {f['month']} | {f['alpha']:.9f} | {f['trained_through']} | {f['training_races']} |" for f in fitted]
    lines += ['', f"確認用fit={verification['confirmation_fits']}。基本モデル再学習0、SQL0、元原本SHA不変。",
              'Brier・新購入ペア・回収率は未測定。確認6月も独立新期間ではない。',
              '不合格を見て係数・罰則・期間・基準を調整せず、この1案で停止する。']
    with (OUT/'report.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(lines)+'\n')
    print('\n'.join(lines[:11]))
    print('verification', verification['status'], 'calibration fits',len(fitted))


if __name__ == '__main__':
    main()
