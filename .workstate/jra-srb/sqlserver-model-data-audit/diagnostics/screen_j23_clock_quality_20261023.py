"""概要: 凍結J23の経験交互作用を時計品質へ置換する1候補を過去月だけで検証する。
作成日: 2026-10-23
入力: spec270、元24月の保存セル/モデル、既存SELECT専用SQL設定。
出力: j23_clock_quality_20261023のprotocol・進捗・選抜予測・検証結果。
実行例: uv run --frozen --extra ml python -u -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/screen_j23_clock_quality_20261023.py
注意事項: 1800秒/2GiB。既使用期間の探索。基本モデル再学習・SQL更新・購入・本番変更なし。
"""

from collections import defaultdict
import gc
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import brentq
from scipy.special import logsumexp, softmax
from threadpoolctl import threadpool_limits

import trace_j23_features_20261023 as trace
import screen_j23_market_calibration_20261023 as prior


ROOT, SOURCE = trace.ROOT, trace.SOURCE
OUT = ROOT/'artifacts/jra_research/j23_clock_quality_20261023'
START = time.monotonic()
f, learner, require = trace.f, trace.learner, trace.require


def save(name, value, *, progress=False):
    """有限JSONを新規保存し、実行進捗だけは置換する。"""
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    path = OUT/name
    if progress:
        temp = path.with_suffix('.tmp')
        temp.write_text(text, encoding='utf-8')
        temp.replace(path)
    else:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)


def guard():
    """固定時間・メモリ上限を検査する。"""
    require(time.monotonic()-START <= 1800, 'quality_wall_time_limit')
    return trace.check_memory(2**31)


def clock_quality(past, ordinal):
    """前日までの最大3正常走から、鮮度と時計分散を含む品質代理値を返す。"""
    require(all(p[0] < ordinal for p in past), 'quality_future_history')
    if not past:
        return 0.
    variance = float(np.var([p[1] for p in past]))
    return len(past)/(len(past)+2)*math.exp(-(ordinal-past[-1][0])/365)/math.sqrt(1+variance)


def source_targets():
    """成績に依存せずwarmupと選抜の全保存対象を固定する。"""
    targets = []
    for path in sorted((SOURCE/'cells').glob('*_J23.json')):
        if path.name[:7] <= '2026-03':
            cell = json.loads(path.read_text(encoding='utf-8-sig'))
            targets.extend({'race_key': r['race_key']} for r in cell['rows'])
    require(len(targets) == 5657 and len({t['race_key'] for t in targets}) == 5657, 'quality_target_cohort')
    return targets


def reconstruct(targets, models, originals):
    """年別履歴を一巡して前日特徴を作り、4方式の元予測と一致した全分布だけを返す。

    Args:
        targets: 結果で選別していないwarmup/選抜対象。
        models: SHA照合済み凍結月別モデル。
        originals: SHA照合済み元保存行。
    Returns:
        校正用のメモリ内分布と、SQL/元予測再現の集計証跡。
    Raises:
        ResearchError: 履歴digest・時点・再現・資源上限が不一致。
    Notes:
        原文・全特徴はファイル保存せず、当日結果は全当日推論特徴を作った後に履歴へ反映する。
    """
    keys = {t['race_key'] for t in targets}
    states, records, years = f.previous.TwentyStates(), [], {}
    config = trace.HistoryConfig.load(ROOT/'configs/research/history_sql_v1.json')
    historical = json.loads((f.old.AUDIT/'audit.json').read_text(encoding='utf-8-sig'))
    scanned = 0
    with trace.LiveAnnualReader(config) as reader:
        reader.preflight()
        trace.market_preflight(reader)
        for year in range(2003, 2027):
            guard()
            raw, audit = reader.year_before(year, '2026-10-18')
            require(audit['input_digest'] == historical['annual'][str(year)]['source_audit']['input_digest'], 'quality_annual_changed')
            scanned += audit.get('scanned_RA', 0)+audit.get('scanned_SE', 0)
            require(scanned <= 2000000, 'quality_row_limit')
            daily = defaultdict(list)
            for key, source in sorted(raw.items()):
                if key[:8] > '20260331':
                    continue
                race, reason = f.old.native.parse_race(key, source)
                if reason:
                    continue
                ra = source['RA'][2]
                seconds = {r['horse_no']: f.old.clock_seconds(source['SE'][r['horse_no']][2][338:342]) for r in race['runners']}
                going = f.old.native.number(ra[888:889] if race['surface'] == 0 else ra[889:890])
                require(going in (1, 2, 3, 4), 'quality_going')
                laps = [f.old.native.number(ra[890+i*3:893+i*3])/10 for i in range(25)]
                race['closing_total'] = sum([v for v in laps if v > 0][-3:]) if race['pace'] is not None else None
                daily[race['day']].append((race, seconds, going))
            del raw
            for day, updates in sorted(daily.items()):
                guard()
                for race, _, _ in updates:
                    if race['key'] not in keys:
                        continue
                    public = states.public(race)
                    x = np.column_stack((public['x'], public['extra'][:, 20:23])).astype(np.float32)
                    quality = []
                    for r in race['runners']:
                        h = states.horses.get(r['horse_id'])
                        quality.append(clock_quality(list(h.last) if h else [], race['ordinal']))
                    records.append({'race_key': race['key'], 'race_date': day, 'x': x,
                                    'basic': states.legacy_features(race)[:, f.old.residual.BASIC].astype(np.float32),
                                    'addition': np.empty((len(x), 0)), 'styles': np.zeros(len(x)), 'density': 0., 'group': 0,
                                    'quality': np.asarray(quality), 'race': race})
                states.update_day(updates)
            years[str(year)] = audit
            save('state.json', {'stage': 'history', 'year': year, 'records': len(records),
                                'memory_bytes': guard(), 'elapsed_seconds': time.monotonic()-START}, progress=True)
            print(json.dumps({'stage': 'history', 'year': year, 'records': len(records)}), flush=True)
            del daily
            gc.collect()
        history_query_count = len(reader.query_metrics)
    del states
    gc.collect()
    require({r['race_key'] for r in records} == keys, 'quality_reconstruction_cohort')
    # 既存の100競走ずつの索引照会とT30/HR検査をそのまま使う。
    markets = f.load_markets({r['race_key']: r['race'] for r in records}, config)
    guard()
    output, max_diff = [], 0.
    for record in records:
        key, month = record['race_key'], record['race_date'][:7]
        record.update(markets.pop(key))
        winners = tuple(r['horse_no'] for r in record['race']['runners'] if r['rank'] <= 2)
        winner = list(trace.combinations([r['horse_no'] for r in record['race']['runners']], 2)).index(winners)
        predictions = {}
        for case in ('J23', 'J01', 'R1', 'M0'):
            p = record['market'].copy() if case == 'M0' else learner.predict(models[(month, case)], learner.clean_record(record))
            old = originals[(month, case)][key]
            loss = float(-np.log(p[winner]))
            brier = float((p@p-2*p[winner]+1)/len(p))
            differences = [abs(p[winner]-old['winning_probability']), abs(loss-old['loss']), abs(brier-old['brier'])]
            require(winner == old['winner'] and len(p) == old['pair_count'] and max(differences) < 1e-12, 'quality_original_prediction_mismatch')
            max_diff = max(max_diff, *differences)
            predictions[case] = p
        p = predictions['J23']
        old = originals[(month, 'J23')][key]
        chosen = trace.select_pair(p, record['prices'], np.ones(len(p)))
        require(chosen == old['chosen'] and (chosen is None or abs(p[chosen]-old['ticket_probability']) < 1e-12), 'quality_original_chosen_mismatch')
        model = models[(month, 'J23')]
        matrix = learner.matrix(record, 'J23')/model['scale'].astype(np.float32)
        left, right = f.old.pairs(len(record['x'])).T
        quality = (record['quality'][left]+record['quality'][right])/2
        experience = (record['x'][left, 9]+record['x'][right, 9])/2
        gap = np.clip(np.log(record['pl']/record['market']), -10, 10)
        gq = gap*quality
        gq -= record['market']@gq
        output.append({'race_key': key, 'race_date': record['race_date'], 'month': month,
                       'winner': winner, 'logp': np.log(p), 'old_term': matrix[:, -1]*model['coef'][-1],
                       'quality_term': gq*model['coef'][-1]/float(np.float32(model['scale'][-1])),
                       'mean_quality': float(quality.mean()), 'mean_experience': float(experience.mean()),
                       'J23_loss': old['loss'], 'J23_brier': old['brier'],
                       'M0_loss': originals[(month, 'M0')][key]['loss']})
    del records, markets
    gc.collect()
    require(max_diff < 1e-12, 'quality_replay')
    return sorted(output, key=lambda r: r['race_key']), {'replayed_races': len(output), 'models_per_race': 4,
            'maximum_prediction_metric_difference': max_diff, 'annual': years,
            'scanned_rows': scanned, 'history_query_count': history_query_count, 'market_batch_size': 100}


def packed(rows, scale):
    """競走群の凍結確率と置換差分を1係数の凸最適化入力へ連結する。"""
    counts = np.asarray([len(r['logp']) for r in rows])
    starts = np.cumsum(np.r_[0, counts[:-1]])
    return {'logp': np.concatenate([r['logp'] for r in rows]),
            'delta': np.concatenate([scale*r['quality_term']-r['old_term'] for r in rows]),
            'starts': starts, 'groups': np.repeat(np.arange(len(rows)), counts),
            'target': starts+np.asarray([r['winner'] for r in rows])}


def objective(alpha, data):
    """確率和1を保つ置換logitの平均損失と解析勾配を返す。"""
    logits = data['logp']+alpha*data['delta']
    p, norm = learner.probabilities(logits, data['starts'], data['groups'])
    n = len(data['starts'])
    loss = float(np.mean(norm-logits[data['target']])+.001*alpha**2/2)
    gradient = float((p@data['delta']-data['delta'][data['target']].sum())/n+.001*alpha)
    return loss, gradient


def fit(data):
    """凸目的の端点勾配または一意な根から置換率を学び、端点より悪い解を拒否する。"""
    if objective(0., data)[1] >= 0:
        alpha = 0.
    elif objective(1., data)[1] <= 0:
        alpha = 1.
    else:
        alpha = float(brentq(lambda a: objective(a, data)[1], 0., 1., xtol=1e-12))
    require(objective(alpha, data)[0] <= min(objective(0., data)[0], objective(1., data)[0])+1e-12, 'quality_optimizer_endpoint')
    h = 1e-5
    numerical = (objective(alpha+h, data)[0]-objective(alpha-h, data)[0])/(2*h)
    require(abs(numerical-objective(alpha, data)[1]) < 1e-7, 'quality_gradient')
    return alpha


def self_checks():
    """履歴時点・品質範囲・鮮度/分散の単調性と係数最適化を合成入力で検証する。"""
    require(clock_quality([], 100) == 0, 'quality_empty')
    stable = [(90, 0.), (91, 0.), (92, 0.)]
    noisy = [(90, -1.), (91, 0.), (92, 1.)]
    require(0 < clock_quality(noisy, 100) < clock_quality(stable, 100) < 1, 'quality_variance')
    require(clock_quality(stable, 101) < clock_quality(stable, 100), 'quality_freshness')
    for direction, endpoint in ((np.asarray([1., -1.]), 1.), (np.asarray([-1., 1.]), 0.)):
        data = {'logp': np.log([.5, .5]), 'delta': direction, 'starts': np.asarray([0]),
                'groups': np.asarray([0, 0]), 'target': np.asarray([0])}
        require(fit(data) == endpoint, 'quality_synthetic_fit')


def evaluate(records):
    """21選抜月で厳密な過去月学習を行い、固定ゲートと全ペアBrierを比較する。"""
    fits, predictions = [], []
    for month in sorted({r['month'] for r in records if r['month'] >= '2024-07'}):
        past = [r for r in records if r['month'] < month]
        current = [r for r in records if r['month'] == month]
        scale = float(np.mean([r['mean_experience'] for r in past])/np.mean([r['mean_quality'] for r in past]))
        require(math.isfinite(scale) and scale > 0 and max(r['race_date'] for r in past) < month+'-01', 'quality_prior_scale')
        data = packed(past, scale)
        alpha = fit(data)
        fits.append({'month': month, 'alpha': alpha, 'quality_scale': scale, 'training_races': len(past),
                     'trained_through': max(r['race_date'] for r in past),
                     'training_cohort_sha256': trace.digest([r['race_key'] for r in past]),
                     'objective': objective(alpha, data)[0], 'gradient': objective(alpha, data)[1]})
        for r in current:
            delta = scale*r['quality_term']-r['old_term']
            p = softmax(r['logp']+alpha*delta)
            require(abs(p.sum()-1) < 1e-12 and np.all(p > 0), 'quality_probability')
            require(abs(-r['logp'][r['winner']]-r['J23_loss']) < 1e-12, 'quality_alpha_zero')
            predictions.append({'race_key': r['race_key'], 'race_date': r['race_date'], 'alpha': alpha,
                                'winning_probability': float(p[r['winner']]), 'loss': float(-np.log(p[r['winner']])),
                                'brier': float((p@p-2*p[r['winner']]+1)/len(p)),
                                'J23_loss': r['J23_loss'], 'J23_brier': r['J23_brier'], 'M0_loss': r['M0_loss']})
        del data
        guard()
        save('state.json', {'stage': 'selection', 'month': month, 'alpha': alpha,
                            'predictions': len(predictions), 'elapsed_seconds': time.monotonic()-START}, progress=True)
        print(json.dumps({'stage': 'selection', 'month': month, 'alpha': alpha}), flush=True)
    require(len(fits) == 21 and len(predictions) == 4938, 'quality_selection_cohort')
    comparison = prior.comparison(predictions)
    comparison['candidate_brier'] = float(np.mean([r['brier'] for r in predictions]))
    comparison['J23_brier'] = float(np.mean([r['J23_brier'] for r in predictions]))
    checks = {'min_races': comparison['races'] >= 1000, 'min_days': comparison['days'] >= 30,
              'min_relative_logloss_gain': comparison['relative_gain_vs_J23'] >= .001,
              'paired_day_interval': comparison['difference_95'][1] < 0,
              'not_worse_than_market': comparison['calibrated_logloss'] <= comparison['M0_logloss'],
              'brier_not_worse': comparison['candidate_brier'] <= comparison['J23_brier']}
    return fits, predictions, comparison, checks


def main():
    """protocolを固定して1候補を検証し、失敗時は依存計算を停止して理由を保存する。"""
    OUT.mkdir(exist_ok=True)
    stage = 'protocol'
    try:
        targets = source_targets()
        save('protocol.json', {'candidate': 'C02_clock_quality_interaction', 'candidate_count': 1,
                              'adjustment_rounds': 0, 'spec': '270-J23時計品質交互作用の単一候補検証.md',
                              'spec_sha256': trace.sha(ROOT/'.workstate/jra-srb/sqlserver-model-data-audit/spec/270-J23時計品質交互作用の単一候補検証.md'),
                              'targets': targets, 'selection': ['2024-07', '2026-03'], 'warmup': ['2024-04', '2024-06'],
                              'wall_seconds': 1800, 'memory_bytes': 2**31, 'bootstrap_seed': 260,
                              'confirmation_reconstruct_only_if_passed': True})
        self_checks()
        stage = 'source'
        models, originals, hashes = trace.load_sources(targets)
        with threadpool_limits(limits=1):
            stage = 'reconstruct'
            records, verification = reconstruct(targets, models, originals)
            save('replay-verification.json', verification)
            stage = 'selection'
            fits, predictions, comparison, checks = evaluate(records)
        require(all(trace.sha(ROOT/p) == h for p, h in hashes.items()), 'quality_source_changed')
        passed = all(checks.values())
        result = {'candidate': 'C02', 'selection': comparison, 'gate_checks': checks, 'selection_passed': passed,
                  'decision': 'selection_passed_confirmation_pending' if passed else 'stop_selection_gate_failed',
                  'adoption': False, 'independent_test': False, 'base_model_fits': 0,
                  'calibration_fits': len(fits), 'confirmation_fits': 0, 'confirmation_predictions': 0,
                  'synthetic_and_gradient_checks': True, 'source_unchanged': True,
                  'source_sha256': hashes, 'replay': verification, 'elapsed_seconds': time.monotonic()-START,
                  'sql_writes': 0, 'purchase_evaluated': False}
        save('calibrations.json', fits)
        save('selection-predictions.json', predictions)
        save('results.json', result)
        save('state.json', {'status': 'passed', 'selection_passed': passed, 'decision': result['decision'],
                            'elapsed_seconds': time.monotonic()-START}, progress=True)
        print(json.dumps({'selection': comparison, 'checks': checks, 'decision': result['decision']}, ensure_ascii=False), flush=True)
    except Exception as error:
        safe = error if isinstance(error, trace.ResearchError) else trace.ResearchError('quality_failed', 4, error_type=type(error).__name__)
        save('failure.json', {'stage': stage, 'reason': safe.reason, 'details': safe.details,
                              'elapsed_seconds': time.monotonic()-START})
        save('state.json', {'status': 'failed', 'stage': stage, 'reason': safe.reason}, progress=True)
        print(json.dumps({'status': 'failed', 'stage': stage, 'reason': safe.reason, 'details': safe.details}), flush=True)
        raise


if __name__ == '__main__':
    main()
