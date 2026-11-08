"""概要: J23の購入判断を異なる10側面から月次の過去限定補正で比較する。
作成日: 2026-10-23
入力: 固定30仮説runのJ23/R1保存セル。外部接続・追加引数なし。
出力: artifacts/jra_research/j23_ten_aspects_20261023の計画・月次係数・仮想購入・比較レポート。
実行例: uv run --frozen python -X utf8 scripts/analyze_j23_ten_aspects.py
注意事項: 既使用期間の探索。新しい確率モデルの学習、別組への買い替え、実購入なし。
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random

from analyze_j23_followup import SOURCE, aggregate, dump, percent
from jra_srb.jra_research_j23_policy import band, estimate, policy_stake

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/jra_research/j23_ten_aspects_20261023'
POLICIES = {
    'Q01': '一律10%の価格低下を想定',
    'Q02': '過去の的中時価格低下を補正',
    'Q03': 'オッズ帯別の的中時価格低下を補正',
    'Q04': '過去の的中数による確率補正',
    'Q05': '価格補正と確率補正を併用',
    'Q06': '直近3か月の確率補正',
    'Q07': '確率補正の不確実性を控除',
    'Q08': '高配当への払戻額集中を賭金で抑制',
    'Q09': '15頭以下の競走に限定',
    'Q10': 'R1も同じ組を購入する場合だけ残す',
}


def applied(row, stake):
    """元のHR払戻を用いて購入額変更後の会計を作る。元行は変更しない。"""
    assert 0 <= stake <= 600 and stake % 100 == 0
    output = dict(row)
    output['stake'] = stake
    output['payout'] = row['hr_payout_yen']*(stake//100) if row['chosen'] == row['winner'] else 0
    return output


def daily_interval(candidate, baseline, seed):
    """同じ購入日集合を再標本化し、探索用の対応利益差区間を算出する。

    Returns:
        未調整95%区間。独立証拠・多重比較補正済み区間・採用判定ではない。
    """
    differences = defaultdict(int)
    for sign, rows in ((1, candidate), (-1, baseline)):
        for row in rows:
            differences[row['race_date']] += sign*(row['payout']-row['stake'])
    values = list(differences.values())
    rng = random.Random(seed)
    draws = sorted(sum(rng.choices(values, k=len(values))) for _ in range(2000))
    return [draws[49], draws[1949]]


def main():
    """10案を先に固定し、27か月を過去限定で比較・保存して原本不変を確認する。"""
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = dict(date='2026-10-23', status='exploratory_previously_seen_data',
                    policies=POLICIES, warmup_months=3, evaluation_start='2024-07',
                    selection_end='2026-03', confirmation_end='2026-09',
                    purchase_min_adjusted_ev=1.05, probability_prior_expected_hits=20,
                    price_prior_quoted_yen=100000, odds_band_edges=[10, 30],
                    uncertainty_z=1.28, fixed_price_multiplier=.9,
                    probability_clip=[.5, 1.25], price_clip=[.65, 1.05],
                    recent_months=3, payout_exposure_cap_yen=6000,
                    max_pair_count=105, learning_window='strictly_prior_months',
                    forecast_refits=0, independent_test=False,
                    selection_rule='ROI desc among >=100 bets, >=30 buy days, >=10 hits; ID tie',
                    intervals='2000 paired-day bootstrap; unadjusted, exploratory only')
    protocol_file = OUT/'protocol.json'
    if protocol_file.exists():
        assert json.loads(protocol_file.read_text(encoding='utf-8')) == protocol
    else:
        dump(protocol_file, protocol)
    files = sorted((SOURCE/'cells').glob('*_J23.json'))+sorted((SOURCE/'cells').glob('*_R1.json'))+[SOURCE/'metrics.json']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    months, raw_baseline = {}, defaultdict(list)
    for path in sorted((SOURCE/'cells').glob('*_J23.json')):
        cell = json.loads(path.read_text(encoding='utf-8-sig'))
        r1 = json.loads((SOURCE/'cells'/f"{cell['month']}_R1.json").read_text(encoding='utf-8-sig'))
        controls = {r['race_key']: r for r in r1['rows']}
        assert len(controls) == len(cell['rows'])
        rows = []
        for row in cell['rows']:
            control = controls[row['race_key']]
            assert row['race_date'] == control['race_date'] and row['pair_count'] == control['pair_count']
            assert row['winner'] == control['winner'] and row['hr_payout_yen'] == control['hr_payout_yen']
            if not row['stake']:
                continue
            r = dict(row, ev=row['ticket_probability']*row['ticket_odds'],
                     r1_agrees=bool(control['stake'] and control['chosen'] == row['chosen']))
            assert r['stake'] == 600 and 0 < r['ticket_probability'] <= 1
            assert r['payout'] == (r['hr_payout_yen']*6 if r['chosen'] == r['winner'] else 0)
            rows.append(r)
        months[cell['month']] = rows
        raw_baseline['selection' if cell['month'] <= '2026-03' else 'confirmation'].extend(rows)
    assert len(months) == 30
    metrics = json.loads((SOURCE/'metrics.json').read_text(encoding='utf-8-sig'))
    for phase, rows in raw_baseline.items():
        actual = aggregate(rows)
        assert all(actual[k] == metrics['phases'][phase]['J23'][k] for k in ('bets', 'stake', 'payout', 'hits'))
    monthly_parameters, transactions = {}, {name: [] for name in ['baseline', *POLICIES]}
    for index, month in enumerate(sorted(months)):
        if index < 3:
            continue
        prior_months = [m for m in months if m < month]
        past = [r for m in prior_months for r in months[m]]
        recent = [r for m in sorted(prior_months)[-3:] for r in months[m]]
        assert all(r['race_date'][:7] < month for r in past)
        parameters = dict(trained_through_month=max(prior_months), global_=estimate(past))
        parameters['global'] = parameters.pop('global_')
        parameters['recent'] = estimate(recent)
        parameters['price_bands'] = {b: estimate([r for r in past if band(r['ticket_odds']) == b]) for b in ('under10', '10to30', '30plus')}
        monthly_parameters[month] = parameters
        transactions['baseline'].extend(months[month])
        for name in POLICIES:
            for row in months[month]:
                stake = policy_stake(name, row, parameters)
                if stake:
                    transactions[name].append(applied(row, stake))
    results = dict(protocol=protocol, monthly_parameters=monthly_parameters, phases={}, source_sha256=hashes)
    selected = None
    for phase in ('selection', 'confirmation'):
        phase_rows = {name: [r for r in rows if (r['race_date'][:7] <= '2026-03') == (phase == 'selection')] for name, rows in transactions.items()}
        result = {name: aggregate(rows) for name, rows in phase_rows.items()}
        for index, name in enumerate(POLICIES):
            result[name]['paired_profit_difference_95_unadjusted'] = daily_interval(phase_rows[name], phase_rows['baseline'], 2310+index)
            assert result[name]['stake'] <= result['baseline']['stake']
        results['phases'][phase] = result
        if phase == 'selection':
            eligible = [n for n in POLICIES if result[n]['bets'] >= 100 and result[n]['buy_days'] >= 30 and result[n]['hits'] >= 10]
            selected = min(eligible, key=lambda n: (-result[n]['roi'], n)) if eligible else None
            dump(OUT/'selection-lock.json', dict(candidate=selected, rule=protocol['selection_rule'], independently_unseen=False))
    results['selected_by_selection_only'] = selected
    results['monthly'] = {name: {m: aggregate([r for r in rows if r['race_date'][:7] == m]) for m in monthly_parameters} for name, rows in transactions.items()}
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    assert len(monthly_parameters) == 27 and len(results['phases']['confirmation']) == 11
    results['verification'] = dict(status='passed', policy_count=10, evaluated_policy_months=270,
                                   common_baseline_months=27, source_unchanged=True,
                                   prior_month_only=True, new_probability_models=0, adopted=False)
    dump(OUT/'results.json', results)
    dump(OUT/'transactions.json', transactions)
    lines = ['# J23・10側面の購入判断比較', '',
             '2026-10-23。過去データだけで月次補正を推定した探索。既使用の確認期間であり、独立検証ではない。', '',
             '最初の3か月を補正用に除外し、全案共通で2024-07〜2026-09の27か月を比較。',
             '選抜は21か月、確認は従来の6か月。元のJ23買い目以外への買い替えはない。', '',
             '| 案 | 側面 | 選抜21月ROI | 確認6月ROI | 確認点数 | 確認最大DD円 |',
             '|---|---|---:|---:|---:|---:|']
    for name in ('baseline', *POLICIES):
        a, b = (results['phases'][phase][name] for phase in ('selection', 'confirmation'))
        lines.append(f"| {name} | {POLICIES.get(name, '共通期間の原型J23')} | {percent(a['roi'])} | {percent(b['roi'])} | {b['bets']} | {b['max_drawdown_yen']} |")
    lines.extend(['', f'選抜期間だけの固定規則による探索候補: {selected}。確認期間の最高値から候補を選び直さない。', '',
                  'Q03は確認40点/4的中・利益8,880円、最大払戻除外99.25%。選抜ROI60.09%で原型未満。',
                  'Q06は確認137点/9的中・利益7,020円、最大払戻除外69.85%。選抜ROI64.55%で原型未満。',
                  'Q09は標本条件を満たす案の選抜ROIが最高でも85.31%で赤字。確認も60.26%で、採用には至らない。',
                  'Q05/Q07/Q10は確認各1点。0%を十分な標本による性能評価とは扱わない。', '',
                  '## 解釈と制約', '',
                  '- 確率補正は選択済み買い目の購入スコア。全組の確率分布を再学習/正規化したモデルではなく、対数損失の精度改善は測定していない。',
                  '- Q02/Q03/Q05の価格学習は過去の的中分だけ。全買い目の最終オッズは未取得であり、選択偏りがある。全体の価格変動モデルとは呼ばない。',
                  '- 的中・HR払戻は係数推定時には前月までしか使わず、現在月の結果は精算だけに使用。',
                  '- Q08は100円単位の賭金変更。投資額が違うので回収率、利益、DDを併記し、DD低下だけで改善とは判断しない。',
                  '- Q09は保存pair_countから頭数を区分。Q10は同じ時点/同じ対象のR1保存購入との一致。元R1の既定運用への昇格ではない。',
                  '- 区間は対応日bootstrap2000回の未調整95%。10案探索と過去の探索履歴があるため有意性や採用の証拠にしない。',
                  '- 旧判定基準は維持。新モデル採用0。独立期間、全対象の最終価格、前向き記録は今回未追加。',
                  '- 再現用protocol・月次係数・購入原票・原本SHA・会計を保存。原本不変と過去月限定を確認。'])
    (OUT/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines[:23]))
    print('verification passed:', OUT)


if __name__ == '__main__':
    main()
