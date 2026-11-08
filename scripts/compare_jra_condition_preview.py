"""概要: 新条件別キメラと固定旧J23の事前参考予想を同じ出走馬で比較しSQL保存する。
作成日: 2026-10-24
入力: 完成モデルrun、準備済み公開特徴、公式出馬表・単勝/全馬連オッズJSON。
出力: 新規比較フォルダーの全分布・順位・SQL保存payloadと読み戻し証跡。
実行例: uv run --frozen --extra ml python scripts/compare_jra_condition_preview.py --training-run artifacts/jra_research/condition_chimera_20261024 --input-dir artifacts/predictions/20261025-condition-chimera/input --card artifacts/predictions/20261025-condition-chimera/official-card.json --odds artifacts/predictions/20261025-condition-chimera/official-odds.json --output artifacts/predictions/20261025-condition-chimera/comparison --save
注意事項: 未採用モデルの参考比較。購入0円。--save時のみ共通SQLへ予想保存。結果取得なし。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from datetime import datetime, timedelta, timezone
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np

import run_jra_condition_chimera as training
from jra_srb import jra_research_j23_live as legacy
from jra_srb.jra_research_contracts import horse_number, digest
from jra_srb.jra_research_r1_live import utc, require
from jra_srb.jra_research_native_card import _official_source_url


def price_array(odds, market, keys):
    """同一公式束の完全な単勝/馬連数値価格だけを馬番順に返す。"""
    values = {}
    for row in odds['odds'][market]:
        key = tuple(sorted((horse_number(v) for v in row['combination']), key=int))
        require(key not in values and row.get('bet_type') in (None, market), 'preview_duplicate_or_mixed_market')
        value = float(row['odds'])
        require(np.isfinite(value) and value >= 1, 'preview_invalid_odds')
        values[key] = value
    require(set(values) == set(keys), 'preview_incomplete_market')
    return np.asarray([values[k] for k in keys])


def ranking(p, horses):
    """馬連確率から馬別2着内周辺順位と全ペア順位を作る。"""
    keys = list(combinations(horses, 2))
    totals = {h: 0. for h in horses}
    for pair, value in zip(keys, p, strict=True):
        for h in pair:
            totals[h] += float(value)
    return {'horse_ranking': [{'horse_no': h, 'top2_probability': totals[h]} for h in sorted(horses, key=lambda h: (-totals[h], int(h)))],
            'pair_ranking': [{'horses': list(keys[i]), 'probability': float(p[i])} for i in np.argsort(-p, kind='stable')]}


def compare(args):
    """同じ入力時点の研究予想を作り、任意SQL保存後に全順位・買い目なしを照合する。"""
    folder = args.output
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        read = legacy.read_json
        record, quality = read(args.input_dir/'input.json'), read(args.input_dir/'quality.json')
        card, odds = read(args.card), read(args.odds)
        now = datetime.now(timezone.utc)
        require(quality['status'] == 'passed' and card['race_id'] == odds['race_id'] == record['race_id'], 'preview_identity')
        require(quality['card_sha256'] == training.sha(args.card), 'preview_card_changed')
        # 入力の対象レース時刻を使用し、別レースへ固定時刻を流用しない。
        import re
        match = re.fullmatch(r'(\d{1,2})時(\d{2})分', card['start_time'])
        require(match is not None, 'preview_post_time')
        post = datetime.fromisoformat(f"{record['race_date']}T{int(match[1]):02d}:{int(match[2]):02d}:00+09:00")
        require(now < post and _official_source_url(odds['source']), 'preview_after_post_or_unofficial')
        require(timedelta(0) <= now-utc(odds['fetched_at']) <= timedelta(days=1), 'preview_stale_odds')
        horses = record['horses']
        keys = list(combinations(horses, 2))
        prices = price_array(odds, 'quinella', keys)
        win = price_array(odds, 'win', [(h,) for h in horses])
        manifest = read(args.training_run/'model-manifest.json')
        require(training.sha(args.training_run/'final_model.joblib') == manifest['model_sha256'], 'preview_model_sha')
        require(read(args.training_run/'independent-verification.json')['status'] == 'passed', 'preview_unverified_model')
        fitted = joblib.load(args.training_run/'final_model.joblib')
        stage = 'score'
        new = training.model.forecast(fitted, record)
        old, _, old_provenance = legacy.load_frozen(record['race_date'])
        public = read(args.input_dir/'j23_public_features.json')
        require(public['horses'] == horses and public['race_id'] == record['race_id'], 'preview_old_public_roster')
        market = 1/prices
        market /= market.sum()
        old_record = {'x': np.asarray(public['x'], dtype=np.float32), 'market': market, 'pl': legacy.features.pl_pairs(1/win),
                      'addition': np.empty((len(horses), 0)), 'basic': np.empty((len(horses), 0)),
                      'styles': np.zeros(len(horses)), 'density': 0., 'group': record['surface']*2+int(record['distance'] >= 2000)}
        old_p = legacy.learner.predict(old, legacy.learner.clean_record(old_record))
        require(abs(old_p.sum()-1) < 1e-9 and np.all(old_p > 0), 'preview_legacy_probability')
        old_report = {**ranking(old_p, horses), 'case': 'J23', 'provenance': old_provenance}
        reports = {'condition_chimera': new, 'legacy_J23': old_report}
        names = {horse_number(r['horse_no']): r['horse_name'] for r in card['runners']}
        snapshot = {'card': card, 'odds': odds, 'input_quality': quality, 'input_features': record,
                    'new_model_sha256': manifest['model_sha256'], 'legacy_model_provenance': old_provenance}
        training.save(folder/'comparison.json', {'created_at': now.isoformat(), 'race_id': record['race_id'],
            'race_name': card['race_name'], 'research_only': True, 'preview_only': True, 'reports': reports,
            'names': names, 'new_model_market_input': False, 'legacy_market_input': True,
            'odds_fetched_at': odds['fetched_at'], 'purchase_policy': 'none', 'same_day_recheck_required': True})
        receipts = []
        if args.save:
            stage = 'sql_save'
            from jra_srb.storage import build_analysis_store
            from jra_srb.storage_config import storage_backend
            require(storage_backend() == 'sqlserver', 'preview_sql_backend_required')
            store = build_analysis_store(training.ROOT/'data/db/analysis.sqlite')
            try:
                for name, report in reports.items():
                    horse_ranking = [r['horse_no'] for r in report['horse_ranking']]
                    prediction_id = f"jra-{record['race_id']}-{name}-{now.strftime('%Y%m%dT%H%M%SZ')}"
                    prediction = {'predicted_ranking': horse_ranking, 'predicted_top3': horse_ranking[:3],
                        'ranking_semantics': 'top2_marginal_descending_not_finish_order_probability',
                        'probability_type': 'quinella_and_top2_marginal', 'generated_before_result': True,
                        'research_only': True, 'preview_only': True, 'production_adoption': False,
                        'head_horse_numbers': [], 'axis_horse_numbers': horse_ranking[:1],
                        'opponent_horse_numbers': horse_ranking[1:5], 'betting_decision_status': 'research_reference_no_purchase',
                        'forecast': report, 'prediction_tickets': [], 'same_day_recheck_required': True}
                    payload = {'prediction_id': prediction_id, 'race_id': record['race_id'],
                        'theory_version': f'condition-chimera-comparison:{name}:spec350', 'mode': 'research_reference',
                        'budget': 0, 'created_at': now.isoformat(), 'pre_race_snapshot': snapshot,
                        'prediction_json': prediction, 'prediction_tickets': []}
                    training.save(folder/f'{name}_payload.json', payload)
                    store.upsert_prediction_record(payload)
                    saved = store.get_prediction_record(prediction_id)
                    require(saved.race_id == record['race_id'] and digest(saved.prediction) == digest(prediction)
                            and not saved.prediction_tickets, 'preview_saved_readback_mismatch')
                    receipts.append({'prediction_id': prediction_id, 'race_id': saved.race_id,
                                     'readback_verified': True, 'prediction_sha256': digest(prediction)})
            finally:
                if hasattr(store, 'close'):
                    store.close()
        training.save(folder/'verification.json', {'status': 'passed', 'race_id': record['race_id'], 'runners': len(horses),
            'new_and_old_scored': True, 'sql_saved': bool(args.save), 'saved': receipts,
            'purchase_yen': 0, 'same_day_recheck_required': True})
        training.log('preview_comparison_complete', race_id=record['race_id'], sql_saved=bool(args.save), saved=receipts)
    except Exception as error:
        training.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training-run', type=Path, required=True)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--card', type=Path, required=True)
    parser.add_argument('--odds', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--save', action='store_true')
    compare(parser.parse_args())
