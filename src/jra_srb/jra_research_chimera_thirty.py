"""概要: 30仮説×30暦月の前進検証を保存・再開し、精度と購入成績を別判定する。
作成日: 2026-10-22
入力: spec240/241、固定SQL、入力監査、任意の再開run ID。
出力: 900セル台帳、月次モデル/会計、選抜固定、性能と独立再集計証跡。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera_thirty.py
注意事項: 後ろ向き研究。実購入・既定モデル変更・DB書込・外部AI送信なし。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from . import jra_research_chimera_thirty_features as features
from . import jra_research_chimera_thirty_model as learner
from .jra_research_artifacts import ROOT, RunArtifacts, existing_run, code_identity
from .jra_research_contracts import digest, ResearchError
from .jra_research_r1_live import require, read_json
from .jra_research_resources import check_memory

MONTHS = tuple(f'{year}-{month:02d}' for year in range(2024, 2027) for month in range(1, 13)
               if '2024-04' <= f'{year}-{month:02d}' <= '2026-09')
CONFIG = {'protocol': 'spec241-thirty-forward-v1', 'months': list(MONTHS), 'selection_months': 24,
          'cases': list(learner.CASES), 'memory_limit': features.LIMIT, 'penalty': .1,
          'stake': 600, 'bootstrap_replicates': 20000, 'seed': 241, 'max_adjustment_rounds': 0,
          'retrospective_previously_seen_data': True}


def sha(path):
    """ファイル実内容のSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, value):
    """研究集計をUTF-8一時ファイルから原子的に保存する。"""
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def identity():
    """再開時の実装・仕様・共通入力監査の一致を検査できる来歴を作る。"""
    result = code_identity()
    paths = [features.AUDIT, ROOT/'scripts/run_jra_chimera_thirty.py',
             features.RECORD_ROOT/'spec/240-新キメラ30仮説30期間の研究計画.md',
             features.RECORD_ROOT/'spec/241-30仮説の固定実装契約.md']
    return {'code': result, 'contracts': {str(p.relative_to(ROOT)): sha(p) for p in paths}, 'config': CONFIG}


def cohort_hash(records):
    """対象キー・日・価格/払戻来歴を結果非依存の順番で固定する。"""
    return digest([(r['race_key'], r['race_date'], r['market_sha256'], r['win_sha256'], r['hr_sha256']) for r in records])


def measure(record, probability):
    """一競走の確率モーメントと固定政策の仮想損益だけを保存する。"""
    p = np.asarray(probability, dtype=float)
    require(np.isfinite(p).all() and np.all(p > 0) and abs(float(p.sum())-1) < 1e-9, 'thirty_probability_contract')
    winner = record['winner']
    chosen = features.old.select_pair(p, record['prices'], np.ones(len(p)))
    stake = 600 if chosen is not None else 0
    returned = int(record['payout_yen'])*6 if chosen == winner else 0
    return {'race_key': record['race_key'], 'race_date': record['race_date'], 'pair_count': len(p),
            'winner': int(winner), 'winning_probability': float(p[winner]), 'squared_sum': float(p@p),
            'probability_sum': float(p.sum()), 'minimum': float(p.min()), 'loss': float(-np.log(p[winner])),
            'brier': float((p@p-2*p[winner]+1)/len(p)),
            'chosen': chosen, 'ticket_probability': float(p[chosen]) if chosen is not None else None,
            'ticket_odds': float(record['prices'][chosen]) if chosen is not None else None,
            'stake': stake, 'payout': returned, 'hr_payout_yen': int(record['payout_yen'])}


def summary(rows):
    """精度、点数、購入日、最大払戻依存とドローダウンを集計する。"""
    require(bool(rows), 'thirty_empty_summary')
    stake, payout = sum(r['stake'] for r in rows), sum(r['payout'] for r in rows)
    maximum = max(r['payout'] for r in rows)
    profits = np.asarray([r['payout']-r['stake'] for r in sorted(rows, key=lambda r: (r['race_date'], r['race_key']))])
    cumulative = np.r_[0, profits.cumsum()]
    return {'races': len(rows), 'logloss': float(np.mean([r['loss'] for r in rows])),
            'brier': float(np.mean([r['brier'] for r in rows])), 'bets': sum(r['stake'] > 0 for r in rows),
            'buy_days': len({r['race_date'] for r in rows if r['stake']}), 'hits': sum(r['payout'] > 0 for r in rows),
            'stake': stake, 'payout': payout, 'roi': payout/stake if stake else None,
            'roi_without_largest': (payout-maximum)/stake if stake else None,
            'largest_payout_share': maximum/payout if payout else None,
            'max_drawdown_yen': int(np.max(np.maximum.accumulate(cumulative)-cumulative))}


def read_cell(path, frozen_sha, inputs_sha):
    """セルのhashとモデル来歴を検査し、安全に再利用できる結果だけを返す。"""
    cell = read_json(path)
    value = {k: v for k, v in cell.items() if k != 'cell_sha256'}
    require(digest(value) == cell['cell_sha256'], 'thirty_checkpoint_changed')
    require(cell['frozen_sha256'] == frozen_sha and cell['cohort_sha256'] == inputs_sha, 'thirty_checkpoint_identity')
    model_path = path.parent/cell['model_file']
    require(model_path.parent.resolve() == path.parent.resolve() and sha(model_path) == cell['model_sha256'], 'thirty_model_changed')
    require(cell['status'] == 'evaluated' and cell['summary'] == summary(cell['rows']), 'thirty_checkpoint_summary')
    require(cell['trained_through'] < cell['month']+'-01', 'thirty_checkpoint_future_training')
    return cell, joblib.load(model_path)


def save_cell(folder, month, case, model, records, predictions, frozen_sha):
    """一方式一月のモデルと会計を原子的に保存し、再読込推論を照合する。"""
    path = folder/f'{month}_{case}.json'
    require(not path.exists(), 'thirty_completed_cell_overwrite')
    model_path = folder/f'{month}_{case}.joblib'
    temporary = model_path.with_suffix('.joblib.tmp')
    joblib.dump(model, temporary)
    temporary.replace(model_path)
    restored = joblib.load(model_path)
    checks = 0
    # 混合J30は重みと全当月成分の一致を呼出元で検査する。
    if case != 'J30':
        for index in sorted({0, len(records)//2, len(records)-1}):
            actual = learner.predict(restored, learner.clean_record(records[index]))
            require(np.allclose(actual, predictions[index], atol=1e-14, rtol=1e-12), 'thirty_reload_prediction')
            checks += 1
    else:
        require(np.array_equal(restored['weights'], model['weights']), 'thirty_stack_reload_weights')
    rows = [measure(r, p) for r, p in zip(records, predictions, strict=True)]
    value = {'month': month, 'case': case, 'status': 'evaluated', 'trained_through': model['trained_through'],
             'train_races': model.get('train_races', 0), 'frozen_sha256': frozen_sha,
             'cohort_sha256': cohort_hash(records), 'model_file': model_path.name, 'model_sha256': sha(model_path),
             'reload_checks': checks, 'summary': summary(rows), 'rows': rows}
    value['cell_sha256'] = digest(value)
    atomic_json(path, value)
    verified, _ = read_cell(path, frozen_sha, cohort_hash(records))
    return verified


def lock_selection(cells):
    """最初の24月の対数損失だけから候補1案を固定する。"""
    scores = {}
    for case in learner.CASES:
        chosen = [c for c in cells if c['case'] == case and c['month'] in MONTHS[:24]]
        require(len(chosen) == 24, 'thirty_selection_incomplete')
        scores[case] = summary([r for c in chosen for r in c['rows']])['logloss']
    candidate = min(scores, key=lambda case: (scores[case], case))
    return {'candidate': candidate, 'selected_through': MONTHS[23], 'confirmation_starts': MONTHS[24],
            'rule': 'minimum_pooled_selection_logloss_then_case_id', 'scores': scores,
            'selection_cells_sha256': digest([c['cell_sha256'] for c in cells if c['month'] in MONTHS[:24]]),
            'policy': {'odds_min': 4, 'odds_max': 80, 'probability_min': .015, 'ev_min': 1.05, 'stake': 600}}


def intervals(rows, market_rows, r1_rows, multiplicity):
    """同じ開催日を再標本化して精度差・損益差・ROI区間を算出する。"""
    require([r['race_key'] for r in rows] == [r['race_key'] for r in market_rows] == [r['race_key'] for r in r1_rows], 'thirty_paired_cohort')
    daily = defaultdict(lambda: np.zeros(8))
    for row, m, b in zip(rows, market_rows, r1_rows, strict=True):
        daily[row['race_date']] += [row['loss']-m['loss'], row['loss']-b['loss'], 1,
                                    row['stake'], row['payout'], row['payout']-row['stake']-b['payout']+b['stake'],
                                    m['loss'], b['loss']]
    values = np.asarray([v for _, v in sorted(daily.items())])
    rng = np.random.default_rng(CONFIG['seed'])
    draws = []
    for _ in range(CONFIG['bootstrap_replicates']//1000):
        indices = rng.integers(0, len(values), size=(1000, len(values)))
        total = values[indices].sum(axis=1)
        draws.append(np.column_stack((total[:, 0]/total[:, 2], total[:, 1]/total[:, 2],
                                      total[:, 4]/np.maximum(total[:, 3], 1), total[:, 5])))
    draws = np.concatenate(draws)
    tail = .025/multiplicity
    bounds = np.quantile(draws, [tail, 1-tail], axis=0)
    return {'days': len(values), 'replicates': CONFIG['bootstrap_replicates'], 'multiplicity': multiplicity,
            'loss_difference_market': bounds[:, 0].tolist(), 'loss_difference_r1': bounds[:, 1].tolist(),
            'roi': bounds[:, 2].tolist(), 'profit_difference_r1_yen': bounds[:, 3].tolist(),
            'method': 'paired_day_bootstrap_bonferroni_percentile' if multiplicity > 1 else 'paired_day_bootstrap_percentile'}


def report(cells, selection):
    """全30案を報告しつつ、確認期間からの候補選び直しを禁止する。"""
    phases = {}
    for phase, months in (('selection', MONTHS[:24]), ('confirmation', MONTHS[24:])):
        rows = {case: [r for c in cells if c['case'] == case and c['month'] in months for r in c['rows']]
                for case in ('M0', 'R1', *learner.CASES)}
        result = {}
        m0, r1 = summary(rows['M0']), summary(rows['R1'])
        for case in ('M0', 'R1', *learner.CASES):
            s = summary(rows[case])
            s['market_logloss_improvement'] = 1-s['logloss']/m0['logloss']
            s['r1_logloss_improvement'] = 1-s['logloss']/r1['logloss']
            s['brier_change_vs_market'] = s['brier']/m0['brier']-1
            if case.startswith('J'):
                ci = intervals(rows[case], rows['M0'], rows['R1'], 1 if phase == 'confirmation' and case == selection['candidate'] else 30)
                s['intervals'] = ci
                s['accuracy_pass'] = (s['market_logloss_improvement'] >= .0025 and s['r1_logloss_improvement'] >= .005
                                      and s['brier_change_vs_market'] <= .005 and ci['loss_difference_market'][1] < 0
                                      and ci['loss_difference_r1'][1] < 0)
                s['purchase_pass'] = (s['roi'] is not None and s['roi'] >= 1.05 and s['bets'] >= 100
                                      and s['buy_days'] >= 30 and s['hits'] >= 10 and r1['roi'] is not None
                                      and s['roi']-r1['roi'] >= .05 and ci['roi'][0] > 1
                                      and ci['profit_difference_r1_yen'][0] > 0)
            result[case] = s
        phases[phase] = result
    candidate = selection['candidate']
    selected = phases['confirmation'][candidate]
    return {'status': 'complete', 'evaluated_hypothesis_cells': sum(c['case'].startswith('J') for c in cells),
            'expected_hypothesis_cells': 900, 'candidate': candidate, 'phases': phases,
            'accuracy_pass': selected['accuracy_pass'], 'purchase_pass': selected['purchase_pass'],
            'adoption': 'prospective_confirmation_required' if selected['accuracy_pass'] and selected['purchase_pass'] else 'rejected',
            'default_changed': False, 'goal_good_roi_proven': False,
            'limitation': 'Previously inspected retrospective data; prospective pre-race recording remains necessary.'}


def verify(folder):
    """SQL再読取・再学習なしで、900セルのhash/会計/選抜を独立再集計する。"""
    frozen = read_json(folder/'frozen.json')
    frozen_sha = digest(frozen)
    require(frozen == identity(), 'thirty_frozen_identity_changed')
    cells = []
    audit = read_json(features.AUDIT)
    for month in MONTHS:
        month_keys = None
        for case in ('M0', 'R1', *learner.CASES):
            path = folder/'cells'/f'{month}_{case}.json'
            raw = read_json(path)
            cell, _ = read_cell(path, frozen_sha, raw['cohort_sha256'])
            keys = [r['race_key'] for r in cell['rows']]
            require(len(keys) == len(set(keys)) and (month_keys is None or keys == month_keys), 'thirty_verified_cohort')
            month_keys = keys
            expected_keys = sorted(r['race_key'] for r in audit['race_inputs'] if r['month'] == month)
            require(sorted(keys) == expected_keys, 'thirty_verified_audit_cohort')
            for row in cell['rows']:
                require(row['race_date'].startswith(month) and row['minimum'] > 0 and abs(row['probability_sum']-1) < 1e-9, 'thirty_verified_probability')
                require(abs(row['loss']+np.log(row['winning_probability'])) < 1e-12, 'thirty_verified_loss')
                require(abs(row['brier']-(row['squared_sum']-2*row['winning_probability']+1)/row['pair_count']) < 1e-12, 'thirty_verified_brier')
                stake = 600 if row['chosen'] is not None else 0
                payout = row['hr_payout_yen']*6 if row['chosen'] == row['winner'] else 0
                require(row['stake'] == stake and row['payout'] == payout, 'thirty_verified_accounting')
                if stake:
                    require(4 <= row['ticket_odds'] <= 80 and row['ticket_probability'] >= .015
                            and row['ticket_probability']*row['ticket_odds'] >= 1.05, 'thirty_verified_ticket')
            cells.append(cell)
    selection = read_json(folder/'selection-lock.json')
    require(selection == lock_selection(cells), 'thirty_selection_changed')
    metrics = read_json(folder/'metrics.json')
    # bootstrapは保存済み区間を使い、ここでは点推定・採用論理を独立に照合する。
    require(metrics['evaluated_hypothesis_cells'] == 900, 'thirty_verified_cell_count')
    for phase, months in (('selection', MONTHS[:24]), ('confirmation', MONTHS[24:])):
        for case in ('M0', 'R1', *learner.CASES):
            observed = summary([r for c in cells if c['case'] == case and c['month'] in months for r in c['rows']])
            require(all(metrics['phases'][phase][case][k] == v for k, v in observed.items()), 'thirty_verified_metrics')
    result = {'status': 'passed', 'cells': len(cells), 'hypothesis_cells': 900,
              'prediction_rows': sum(len(c['rows']) for c in cells), 'sql_rereads': 0, 'refits': 0,
              'selection_candidate': selection['candidate'], 'frozen_sha256': frozen_sha}
    atomic_json(folder/'verification.json', result)
    return result


def run(resume=None):
    """前進30月を順次実行し、各セルの直後に保存して途中再開を可能にする。"""
    frozen = identity()
    if resume:
        folder = existing_run(resume)
        require(read_json(folder/'frozen.json') == frozen, 'thirty_resume_identity_changed')
    else:
        artifacts = RunArtifacts(CONFIG, 'chimera-thirty-forward')
        folder = artifacts.path
        atomic_json(folder/'frozen.json', frozen)
    print(json.dumps({'stage': 'run', 'run_id': folder.name, 'pid': __import__('os').getpid()}), flush=True)
    cells_folder = folder/'cells'
    cells_folder.mkdir(exist_ok=True)
    frozen_sha = digest(frozen)
    try:
        records = features.prepare(folder)
        gc.collect()
        cells, past_stack, past_errors = [], [], []
        for index, month in enumerate(MONTHS):
            if index == 24:
                lock = lock_selection(cells)
                if (folder/'selection-lock.json').exists():
                    require(read_json(folder/'selection-lock.json') == lock, 'thirty_resume_selection_changed')
                else:
                    atomic_json(folder/'selection-lock.json', lock)
                print(json.dumps({'stage': 'selection_locked', 'candidate': lock['candidate']}), flush=True)
            training = [r for r in records if r['race_date'] < month+'-01']
            testing = [r for r in records if r['race_date'].startswith(month)]
            require(bool(training) and bool(testing) and max(r['race_date'] for r in training) < min(r['race_date'] for r in testing), 'thirty_split')
            current, month_cells, models = {}, {}, {}
            for case in ('M0', 'R1', *learner.CASES):
                path = cells_folder/f'{month}_{case}.json'
                if path.exists():
                    cell, model = read_cell(path, frozen_sha, cohort_hash(testing))
                    reused = True
                else:
                    reused = False
                    if case == 'M0':
                        model = {'case': case}
                    elif case == 'J26':
                        model = {'case': case, 'base': models['J01'], 'weight': learner.confidence(past_errors)}
                    elif case == 'J30':
                        model = learner.fit_stack(past_stack)
                    else:
                        model = learner.fit(training, case)
                    model.update(trained_through=max(r['race_date'] for r in training), train_races=len(training))
                if case == 'J30':
                    probabilities = [learner.predict(model, learner.clean_record(r),
                                                    [current['M0'][i], *(current[c][i] for c in learner.CASES[:-1])])
                                     for i, r in enumerate(testing)]
                    if reused:
                        require(model['history_races'] == len(past_stack), 'thirty_stack_resume_history')
                else:
                    probabilities = [learner.predict(model, learner.clean_record(r)) for r in testing]
                if not reused:
                    cell = save_cell(cells_folder, month, case, model, testing, probabilities, frozen_sha)
                else:
                    require(all(abs(p[r['winner']]-r['winning_probability']) < 1e-12 for p, r in zip(probabilities, cell['rows'], strict=True)), 'thirty_resumed_prediction_changed')
                current[case], month_cells[case], models[case] = probabilities, cell, model
                cells.append(cell)
                atomic_json(folder/'ledger.json', {'status': 'running', 'completed_hypothesis_cells': sum(c['case'].startswith('J') for c in cells),
                                                   'expected_hypothesis_cells': 900,
                                                   'cells': [{k: c[k] for k in ('month', 'case', 'status', 'cell_sha256', 'summary')} for c in cells]})
                print(json.dumps({'stage': 'cell', 'month': month, 'case': case, 'reused': reused,
                                  **cell['summary'], 'memory': check_memory(features.LIMIT)}), flush=True)
                gc.collect()
            for i, record in enumerate(testing):
                winner = record['winner']
                past_stack.append([float(current['M0'][i][winner]), *(float(current[c][i][winner]) for c in learner.CASES[:-1])])
                past_errors.append(month_cells['J01']['rows'][i]['loss']-month_cells['M0']['rows'][i]['loss'])
            del current, models
            gc.collect()
        selection = read_json(folder/'selection-lock.json')
        metrics = report(cells, selection)
        atomic_json(folder/'metrics.json', metrics)
        verification = verify(folder)
        manifest = read_json(folder/'manifest.json')
        manifest.update(status='complete', finished_at_utc=datetime.now(timezone.utc).isoformat(),
                        metrics_sha256=digest(metrics), verification=verification)
        atomic_json(folder/'manifest.json', manifest)
        ledger = read_json(folder/'ledger.json')
        ledger['status'] = 'complete'
        atomic_json(folder/'ledger.json', ledger)
        return {'run_id': folder.name, 'candidate': selection['candidate'], 'adoption': metrics['adoption'], 'verification': verification}
    except Exception as error:
        # DB例外全文や接続文字列を出さず、理由コードだけを残す。
        reason = error.reason if isinstance(error, ResearchError) else type(error).__name__
        atomic_json(folder/'failure.json', {'reason': reason, 'stage': 'run', 'completed_cells_preserved': True})
        manifest = read_json(folder/'manifest.json')
        manifest.update(status='failed', reason=reason)
        atomic_json(folder/'manifest.json', manifest)
        raise
