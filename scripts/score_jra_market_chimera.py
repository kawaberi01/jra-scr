"""概要: 有望研究候補H系を公式の保存時点入力で推論し、任意でSQLへ参考保存する。
作成日: 2026-10-24
入力: spec355の最終モデル、既存出走馬15特徴、公式カード/単勝/馬連束。
出力: 新規dirの全ペア・馬別2着内周辺順位、入力来歴と任意SQL保存の読戻し証跡。
実行例: uv run --frozen --extra ml python scripts/score_jra_market_chimera.py --training-run artifacts/jra_research/market_condition_chimera_20261024 --snapshot-dir artifacts/predictions/20261025-condition-chimera --output artifacts/predictions/20261025-market-condition-chimera --save
注意事項: 前日参考、購入0円。--saveだけSQLへ予想書込。結果は取得しない。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_market_chimera as runner
from compare_jra_condition_preview import price_array, ranking
from jra_srb.jra_research_chimera_thirty_features import pl_pairs
from jra_srb.jra_research_contracts import digest, horse_number
from jra_srb.jra_research_r1_live import require, utc
from jra_srb.jra_research_native_card import _official_source_url


def score(args):
    """検算済みの固定候補を保存時点の公式束へ適用し、入力と予想を保存する。"""
    folder = args.output
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        read = runner.prior.features.read_json
        source = args.snapshot_dir
        card, odds = read(source/'official-card.json'), read(source/'official-odds.json')
        public, quality = read(source/'input/input.json'), read(source/'input/quality.json')
        now = datetime.now(timezone.utc)
        match = re.fullmatch(r'(\d{1,2})時(\d{2})分', card['start_time'])
        require(match is not None, 'market_live_post_time')
        post = datetime.fromisoformat(f"{public['race_date']}T{int(match[1]):02d}:{int(match[2]):02d}:00+09:00")
        require(now < post and quality['status'] == 'passed', 'market_live_after_post_or_bad_quality')
        require(card['race_id'] == odds['race_id'] == public['race_id'], 'market_live_identity')
        require(_official_source_url(card['source']) and _official_source_url(odds['source']), 'market_live_unofficial')
        require(runner.prior.sha(source/'official-card.json') == quality['card_sha256'], 'market_live_card_changed')
        require(all(timedelta(0) <= now-utc(bundle['fetched_at']) <= timedelta(days=1) for bundle in (card, odds)), 'market_live_old_snapshot')
        manifest = read(args.training_run/'model-manifest.json')
        require(runner.prior.sha(args.training_run/'final_model.joblib') == manifest['model_sha256']
                and read(args.training_run/'independent-verification.json')['status'] == 'passed', 'market_live_model_unverified')
        fitted = joblib.load(args.training_run/'final_model.joblib')
        horses = public['horses']
        pair_prices = price_array(odds, 'quinella', list(combinations(horses, 2)))
        win_prices = price_array(odds, 'win', [(h,) for h in horses])
        q = 1/pair_prices
        q /= q.sum()
        record = {**public, 'market': q, 'pl': pl_pairs(1/win_prices)}
        p = runner.model.predict(fitted, runner.model.clean(record))
        require(np.array_equal(p, runner.model.predict(fitted, {**record, 'winner': -1, 'payout_yen': -999})), 'market_live_result_dependency')
        forecast = {**ranking(p, horses), 'case': fitted['case'], 'race_id': public['race_id'],
            'race_date': public['race_date'], 'race_name': card['race_name'], 'created_at': now.isoformat(),
            'horse_names': {horse_number(r['horse_no']): r['horse_name'] for r in card['runners']},
            'trained_through': fitted['trained_through'], 'model_sha256': manifest['model_sha256'],
            'active_contexts': [name for name in runner.model.base.contexts(record, runner.model.context_case(fitted['case'])) if name in fitted['contexts']],
            'fallback_contexts': [name for name in runner.model.base.contexts(record, runner.model.context_case(fitted['case'])) if name not in fitted['contexts']],
            'probability_type': 'quinella_and_top2_marginal_not_win_probability',
            'research_only': True, 'preview_only': True, 'market_input': True, 'production_adoption': False,
            'same_day_recheck_required': True, 'card_observed_at': card['fetched_at'], 'odds_observed_at': odds['fetched_at']}
        runner.prior.save(folder/'forecast.json', forecast)
        snapshot = {'card': card, 'odds': odds, 'input_quality': quality,
            'public_features': public, 'model_sha256': manifest['model_sha256'],
            'assessment': read(args.training_run/'assessment.json')}
        receipt = None
        if args.save:
            stage = 'sql_save'
            from jra_srb.storage import build_analysis_store
            from jra_srb.storage_config import storage_backend
            require(storage_backend() == 'sqlserver', 'market_live_sql_required')
            store = build_analysis_store(runner.ROOT/'data/db/analysis.sqlite')
            ranks = [row['horse_no'] for row in forecast['horse_ranking']]
            prediction_id = f"jra-{public['race_id']}-market-condition-{now.strftime('%Y%m%dT%H%M%SZ')}"
            prediction = {'predicted_ranking': ranks, 'predicted_top3': ranks[:3],
                'ranking_semantics': 'top2_marginal_not_finish_order', 'generated_before_result': True,
                'head_horse_numbers': [], 'axis_horse_numbers': ranks[:1], 'opponent_horse_numbers': ranks[1:5],
                'betting_decision_status': 'research_reference_no_purchase', 'prediction_tickets': [],
                'forecast': forecast, 'research_only': True, 'preview_only': True, 'production_adoption': False}
            payload = {'prediction_id': prediction_id, 'race_id': public['race_id'],
                'theory_version': 'market-condition-chimera:H2:spec355', 'mode': 'research_reference', 'budget': 0,
                'created_at': now.isoformat(), 'pre_race_snapshot': snapshot, 'prediction_json': prediction, 'prediction_tickets': []}
            runner.prior.save(folder/'prediction_payload.json', payload)
            try:
                store.upsert_prediction_record(payload)
                saved = store.get_prediction_record(prediction_id)
                require(saved.race_id == public['race_id'] and digest(saved.prediction) == digest(prediction)
                        and not saved.prediction_tickets, 'market_live_saved_mismatch')
                receipt = {'prediction_id': prediction_id, 'readback_verified': True, 'prediction_sha256': digest(prediction)}
            finally:
                if hasattr(store, 'close'):
                    store.close()
        runner.prior.save(folder/'verification.json', {'status': 'passed', 'runners': len(horses),
            'pair_count': len(p), 'probability_sum': float(p.sum()), 'result_ignored': True,
            'model_sha_verified': True, 'sql_saved': bool(args.save), 'saved': receipt, 'purchase_yen': 0})
        runner.prior.log('market_live_scored', case=fitted['case'], race_id=public['race_id'], sql_saved=bool(args.save), saved=receipt)
    except Exception as error:
        runner.prior.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training-run', type=Path, required=True)
    parser.add_argument('--snapshot-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--save', action='store_true')
    score(parser.parse_args())
