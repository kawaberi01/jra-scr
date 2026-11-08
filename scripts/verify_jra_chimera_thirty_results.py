"""概要: 30仮説研究の保存結果を独立再集計し、月単位の不確実性と結果文書を作る。
作成日: 2026-10-22
入力: --run 完了run ID。保存済みJSONとhash検証済みモデルのみ。
出力: run内independent-verification.json/monthly-uncertainty.json、docs/researchの結果文書。
実行例: uv run --frozen --extra ml python scripts/verify_jra_chimera_thirty_results.py --run RUN_ID
注意事項: SQL再読取・再学習・候補再選抜なし。学習中のコード/仕様を変更しない。
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys

for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_variable] = '1'

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def read(path):
    """UTF-8の保存研究JSONを取得する。"""
    return json.loads(path.read_text(encoding='utf-8'))


def content_hash(value):
    """保存側と同じ正規JSON規則で内容hashを独立計算する。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    """モデルとコードの実内容SHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate(rows):
    """予測モーメントから損失/Brierと会計/最大損失を別実装で集計する。"""
    stakes = sum(row['stake'] for row in rows)
    returned = sum(row['payout'] for row in rows)
    biggest = max(row['payout'] for row in rows)
    balance = peak = drawdown = 0
    for row in sorted(rows, key=lambda r: (r['race_date'], r['race_key'])):
        balance += row['payout']-row['stake']
        peak = max(peak, balance)
        drawdown = max(drawdown, peak-balance)
    return {'races': len(rows), 'logloss': sum(-math.log(row['winning_probability']) for row in rows)/len(rows),
            'brier': sum((row['squared_sum']-2*row['winning_probability']+1)/row['pair_count'] for row in rows)/len(rows),
            'bets': sum(row['chosen'] is not None for row in rows),
            'buy_days': len({row['race_date'] for row in rows if row['stake']}),
            'hits': sum(row['payout'] > 0 for row in rows), 'stake': stakes, 'payout': returned,
            'roi': returned/stakes if stakes else None, 'roi_without_largest': (returned-biggest)/stakes if stakes else None,
            'largest_payout_share': biggest/returned if returned else None, 'max_drawdown_yen': drawdown}


def month_intervals(monthly, market, baseline):
    """月全体を復元抽出し、6か月/24か月単位の不確実性を診断として返す。"""
    import numpy as np
    matrix = np.asarray([[row['races'], row['logloss']*row['races']-m['logloss']*m['races'],
                          row['logloss']*row['races']-b['logloss']*b['races'], row['stake'], row['payout'],
                          row['payout']-row['stake']-b['payout']+b['stake']]
                         for row, m, b in zip(monthly, market, baseline, strict=True)])
    rng = np.random.default_rng(241)
    sampled = matrix[rng.integers(0, len(matrix), size=(20000, len(matrix)))].sum(axis=1)
    measures = np.column_stack((sampled[:, 1]/sampled[:, 0], sampled[:, 2]/sampled[:, 0],
                                sampled[:, 4]/np.maximum(1, sampled[:, 3]), sampled[:, 5]))
    bounds = np.quantile(measures, [.025, .975], axis=0)
    rois = [r['roi'] for r in monthly if r['roi'] is not None]
    return {'months': len(monthly), 'replicates': 20000, 'loss_difference_market_95': bounds[:, 0].tolist(),
            'loss_difference_r1_95': bounds[:, 1].tolist(),
            'roi_95': bounds[:, 2].tolist() if any(r['stake'] for r in monthly) else None,
            'profit_difference_r1_yen_95': bounds[:, 3].tolist(), 'months_with_bets': len(rois),
            'monthly_roi_min': min(rois) if rois else None, 'monthly_roi_max': max(rois) if rois else None,
            'diagnostic_only_not_candidate_selection_or_gate': True,
            'limitation': 'Only six confirmation months; monthly bootstrap is descriptive, not new independent evidence.'}


def verify(run_id):
    """台帳・時系列・混合履歴・会計・選抜・採用判断を独立に照合する。"""
    import joblib
    import numpy as np
    from jra_srb.jra_research_artifacts import ROOT, existing_run
    folder = existing_run(run_id)
    manifest, frozen = read(folder/'manifest.json'), read(folder/'frozen.json')
    assert manifest['status'] == 'complete', '研究runが完了していない'
    metrics, ledger, lock = read(folder/'metrics.json'), read(folder/'ledger.json'), read(folder/'selection-lock.json')
    assert content_hash(metrics) == manifest['metrics_sha256'], '指標hash不一致'
    assert ledger['status'] == 'complete' and ledger['completed_hypothesis_cells'] == 900
    assert len(ledger['cells']) == 960 and len({(c['month'], c['case']) for c in ledger['cells']}) == 960
    for path, expected_hash in {**frozen['code']['code_sha256'], **frozen['contracts']}.items():
        assert file_hash(ROOT/path) == expected_hash, 'コード/仕様/入力監査hash不一致'
    audit_path = ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/diagnostics/20261021-thirty-market-contract-v3.json'
    audit = read(audit_path)
    months = frozen['config']['months']
    cases = ['M0', 'R1', *frozen['config']['cases']]
    frozen_hash = content_hash(frozen)
    cells = {}
    train_dates = [row['race_date'] for row in audit['race_inputs']]
    past_oos = 0
    errors = []
    for month in months:
        month_keys = sorted(row['race_key'] for row in audit['race_inputs'] if row['month'] == month)
        training = [d for d in train_dates if d < month+'-01']
        for case in cases:
            cell = read(folder/'cells'/f'{month}_{case}.json')
            cell_hash = cell.pop('cell_sha256')
            assert content_hash(cell) == cell_hash
            entry = next(r for r in ledger['cells'] if r['month'] == month and r['case'] == case)
            assert entry['cell_sha256'] == cell_hash
            assert cell['frozen_sha256'] == frozen_hash
            assert cell['train_races'] == len(training) and cell['trained_through'] == max(training)
            assert sorted(r['race_key'] for r in cell['rows']) == month_keys
            assert file_hash(folder/'cells'/cell['model_file']) == cell['model_sha256']
            restored = joblib.load(folder/'cells'/cell['model_file'])
            assert restored['trained_through'] == max(training)
            if case == 'J26':
                target = 1/(1+math.exp(50*float(np.mean(errors)))) if errors else .5
                assert abs(restored['weight']-target) < 1e-12
            elif case == 'J30':
                assert restored['history_races'] == past_oos
                weights = restored['weights']
                assert weights.min() >= 0 and abs(weights.sum()-1) < 1e-12
                if not past_oos:
                    assert weights[0] == 1 and not weights[1:].any()
            for row in cell['rows']:
                assert row['race_date'].startswith(month) and row['minimum'] > 0
                assert abs(row['probability_sum']-1) < 1e-9
                assert abs(-math.log(row['winning_probability'])-row['loss']) < 1e-12
                assert abs((row['squared_sum']-2*row['winning_probability']+1)/row['pair_count']-row['brier']) < 1e-12
                assert row['winning_probability']**2 <= row['squared_sum']+1e-12 <= 1+1e-12
                assert row['stake'] == (600 if row['chosen'] is not None else 0)
                assert row['payout'] == (row['hr_payout_yen']*6 if row['chosen'] == row['winner'] else 0)
                if row['chosen'] is not None:
                    assert 4 <= row['ticket_odds'] <= 80 and row['ticket_probability'] >= .015
                    assert row['ticket_odds']*row['ticket_probability'] >= 1.05
            independently_summed = aggregate(cell['rows'])
            for key, value in independently_summed.items():
                saved = cell['summary'][key]
                assert (value is None and saved is None) or (value is not None and math.isclose(value, saved, rel_tol=1e-12, abs_tol=1e-12)), 'セル集計不一致'
            cell['summary'] = independently_summed
            cells[month, case] = cell
        errors.extend(a['loss']-b['loss'] for a, b in zip(cells[month, 'J01']['rows'], cells[month, 'M0']['rows'], strict=True))
        past_oos += len(month_keys)
    monthly, phases = {}, {}
    for phase, selected_months in [('selection', months[:24]), ('confirmation', months[24:])]:
        phases[phase] = {}
        for case in cases:
            rows = [r for month in selected_months for r in cells[month, case]['rows']]
            actual = aggregate(rows)
            expected = metrics['phases'][phase][case]
            for key, value in actual.items():
                assert (value is None and expected[key] is None) or (value is not None and math.isclose(value, expected[key], rel_tol=1e-12, abs_tol=1e-12)), f'再集計不一致:{phase}/{case}/{key}'
            phases[phase][case] = actual
        monthly[phase] = {case: month_intervals([cells[m, case]['summary'] for m in selected_months],
                                               [cells[m, 'M0']['summary'] for m in selected_months],
                                               [cells[m, 'R1']['summary'] for m in selected_months]) for case in cases[2:]}
    candidate = min(cases[2:], key=lambda c: (phases['selection'][c]['logloss'], c))
    assert candidate == lock['candidate'] == metrics['candidate']
    s, m, b = (metrics['phases']['confirmation'][c] for c in (candidate, 'M0', 'R1'))
    ci = s['intervals']
    accuracy = (1-s['logloss']/m['logloss'] >= .0025 and 1-s['logloss']/b['logloss'] >= .005
                and s['brier']/m['brier']-1 <= .005 and ci['loss_difference_market'][1] < 0 and ci['loss_difference_r1'][1] < 0)
    purchase = (s['roi'] is not None and s['roi'] >= 1.05 and s['bets'] >= 100 and s['buy_days'] >= 30
                and s['hits'] >= 10 and b['roi'] is not None and s['roi']-b['roi'] >= .05
                and ci['roi'][0] > 1 and ci['profit_difference_r1_yen'][0] > 0)
    assert accuracy == metrics['accuracy_pass'] and purchase == metrics['purchase_pass']
    result = {'status': 'passed', 'hypothesis_cells': 900, 'control_cells': 60,
              'rows': sum(len(c['rows']) for c in cells.values()), 'candidate': candidate,
              'accuracy_pass': accuracy, 'purchase_pass': purchase, 'sql_rereads': 0, 'refits': 0,
              'purchase_sample_sufficient': s['bets'] >= 100 and s['buy_days'] >= 30 and s['hits'] >= 10,
              'r1_roi_defined': b['roi'] is not None,
              'independent_formulas': True, 'frozen_sha256': frozen_hash,
              'diagnostic_script_sha256': file_hash(Path(__file__)),
              'limitations': ['全ペア確率を複製していないため、保存JSONのみから最大EVの全候補再探索はしない。',
                             '既参照データの後ろ向き検証であり、将来利益の証明ではない。']}
    for name, value in [('monthly-uncertainty.json', monthly), ('independent-verification.json', result)]:
        (folder/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    write_report(ROOT, folder, metrics, monthly, cells, result)
    return result


def percent(value):
    """未定義の回収率を数値0へ置換せず表示する。"""
    return f'{value*100:.2f}%' if value is not None else '購入なし・未定義'


def write_report(root, folder, metrics, monthly, cells, result):
    """選抜固定と精度/購入別の結果、月別成績、限界を日本語で保存する。"""
    case = metrics['candidate']
    s = metrics['phases']['confirmation'][case]
    r1 = metrics['phases']['confirmation']['R1']
    lines = ['# 新キメラ30仮説×30か月の結果', '', '作成日: 2026-10-22。', '',
             f'run: `{folder.name}`。30案×30暦月=900評価、対照60評価。独立再集計passed。', '',
             'R1対照は元R1と同じ8入力を各月の直前までで再学習したもの。未来まで学習済みの保存R1を過去月へ適用していない。', '',
             f'24か月で固定した候補は **{case}**。確認6か月の精度判定は **{s["accuracy_pass"]}**、購入判定は **{s["purchase_pass"]}**。',
             f'市場比の対数損失改善 {s["market_logloss_improvement"]*100:.4f}%、R1対照比 {s["r1_logloss_improvement"]*100:.4f}%。負値は悪化。',
             f'馬連1点600円の仮想回収率 {percent(s["roi"])}、{s["bets"]}点／{s["buy_days"]}購入日／{s["hits"]}的中。R1対照は{percent(r1["roi"])}（{r1["bets"]}点／{r1["hits"]}的中）。',
             f'最大払戻を除いた回収率 {percent(s["roi_without_largest"])}、最大ドローダウン{s["max_drawdown_yen"]:,}円。', '',
             '## 30案の確認期間成績', '', '確認期間で好成績だった別案への選び直しは行わない。未選抜案は診断値。', '',
             '|案|市場比損失改善|R1比損失改善|J01比損失改善|仮想ROI|点数|的中|精度合格|購入合格|',
             '|---|---:|---:|---:|---:|---:|---:|---|---|']
    for name in metrics['phases']['confirmation']:
        if not name.startswith('J'):
            continue
        row = metrics['phases']['confirmation'][name]
        j01_improvement = 1-row['logloss']/metrics['phases']['confirmation']['J01']['logloss']
        lines.append(f'|{name}|{row["market_logloss_improvement"]*100:.4f}%|{row["r1_logloss_improvement"]*100:.4f}%|{j01_improvement*100:.4f}%|{percent(row["roi"])}|{row["bets"]}|{row["hits"]}|{row["accuracy_pass"]}|{row["purchase_pass"]}|')
    lines.extend(['', '## 固定候補の月別成績', '', '|月|競走数|対数損失|ROI|点数|的中|', '|---|---:|---:|---:|---:|---:|'])
    for month in metrics_months(cells):
        row = cells[month, case]['summary']
        lines.append(f'|{month}|{row["races"]}|{row["logloss"]:.6f}|{percent(row["roi"])}|{row["bets"]}|{row["hits"]}|')
    uncertainty = monthly['confirmation'][case]
    lines.extend(['', '## 不確実性・採用判断', '',
                  f'対応開催日bootstrapのROI95%区間: {s["intervals"]["roi"] if s["roi"] is not None else "購入なし・未定義"}（倍率）。',
                  f'月全体bootstrapのROI95%区間: {uncertainty["roi_95"]}（倍率）。6確認月だけの診断で、独立した追加検証ではない。',
                  '精度は市場比0.25%以上/R1比0.5%以上改善、Brier悪化0.5%以内と対応日区間を要求。',
                  '購入はROI105%以上、100点・30日・10的中以上、R1比+5ポイント、ROI下限100%超と損益差下限0超を要求。',
                  f'判断: `{metrics["adoption"]}`。既定モデル・元R1・API・スキルは変更していない。',
                  '2025/2026年は以前の研究で参照済み。900評価の完了を利益の証明にしない。将来の発走前保存予測による確認が必要。',
                  'J12/J13/J18の変更情報は直近完了走までに限定し、今回T30時点の乗替り・転厩公表を取得できたとは扱わない。',
                  '固定版の履歴RA/SEを前日結果として扱っている。競走日による切断は検証したが、後日の訂正を含む各過去時点の原文版の完全復元までは検証していない。',
                  '生原文・全特徴・全ペア確率の永続複製なし。保存後照合と独立再集計はSQL再読取0/再学習0。',
                  '同じデータの購入閾値・重みを変更して不合格を解消する再探索は行わない。', ''])
    lines.extend(['## 固定候補の購入判定内訳', '',
                  '購入なし・標本不足・対照ROI未定義は、性能が悪いと確定したこととは区別する。いずれも実用採用の根拠には不足する。', '',
                  '|条件|実測|充足|', '|---|---:|---|',
                  f'|回収率105%以上|{percent(s["roi"])}|{s["roi"] is not None and s["roi"] >= 1.05}|',
                  f'|100点以上|{s["bets"]}|{s["bets"] >= 100}|',
                  f'|30購入日以上|{s["buy_days"]}|{s["buy_days"] >= 30}|',
                  f'|10的中以上|{s["hits"]}|{s["hits"] >= 10}|',
                  f'|R1比+5ポイント以上|{percent(s["roi"]-r1["roi"]) if s["roi"] is not None and r1["roi"] is not None else "算定不可"}|{s["roi"] is not None and r1["roi"] is not None and s["roi"]-r1["roi"] >= .05}|',
                  f'|ROI95%下限100%超|{percent(s["intervals"]["roi"][0]) if s["roi"] is not None else "未定義"}|{s["roi"] is not None and s["intervals"]["roi"][0] > 1}|',
                  f'|対応損益差95%下限0円超|{s["intervals"]["profit_difference_r1_yen"][0]:.0f}円|{s["intervals"]["profit_difference_r1_yen"][0] > 0}|', ''])
    path = root/'docs/research/chimera-thirty-results-20261022.md'
    path.write_text('\n'.join(lines), encoding='utf-8')


def metrics_months(cells):
    """保存セルに存在する暦月を重複なく昇順で返す。"""
    return sorted({month for month, _ in cells})


def main():
    """完了runを指定して独立検証を起動する。"""
    parser = argparse.ArgumentParser(description='30仮説保存結果の独立検証')
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.run), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
