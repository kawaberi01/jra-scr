"""概要: 検算済みD0を保存公式束へ適用し、旧予想を残してSQLへ参考保存する。
作成日: 2026-10-24
入力: spec365の完成run、公式カード/単勝/馬連と既存15履歴特徴。
出力: 新規出力先の入力・予想・SQL読戻し証跡。
実行例: uv run --frozen --extra ml python scripts/score_jra_attribute_chimera.py --help
注意事項: 前日参考、購入0円。--save時だけSQLへ書込。結果は取得しない。
"""

import argparse
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
import re

import joblib
import numpy as np

import run_jra_attribute_chimera as runner
from compare_jra_condition_preview import price_array, ranking
from verify_jra_attribute_chimera import independent_predict
from jra_srb.jra_research_chimera_thirty_features import pl_pairs
from jra_srb.jra_research_contracts import digest, horse_number
from jra_srb.jra_research_native_card import _official_source_url
from jra_srb.jra_research_r1_live import utc


def score(args):
    """公式公開属性を同じ馬集合へ結合し、保存・別式・結果遮断を確認する。

    Notes:
        D0だけを対象とする。競走条件フラグはD0では未使用と明記する。
        保存失敗時はfailure.jsonへ記録し、結果取得や評価へ進まない。
    """
    folder, source = args.output, args.snapshot_dir
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'inputs'
    try:
        read, require = runner.read, runner.require
        card, odds = read(source/'official-card.json'), read(source/'official-odds.json')
        public, quality = read(source/'input/input.json'), read(source/'input/quality.json')
        now = datetime.now(timezone.utc)
        match = re.fullmatch(r'(\d{1,2})時(\d{2})分', card['start_time'])
        require(match is not None, 'attribute_live_post_time')
        post = datetime.fromisoformat(f"{public['race_date']}T{int(match[1]):02d}:{int(match[2]):02d}:00+09:00")
        require(now < post and quality['status'] == 'passed', 'attribute_live_after_post_or_quality')
        require(card['race_id'] == odds['race_id'] == public['race_id'], 'attribute_live_identity')
        require(all(_official_source_url(b['source']) and timedelta(0) <= now-utc(b['fetched_at']) <= timedelta(days=1)
                    for b in (card, odds)), 'attribute_live_source_or_age')
        require(runner.sha(source/'official-card.json') == quality['card_sha256'], 'attribute_live_card_sha')
        run = args.training_run
        manifest, assessment = read(run/'model-manifest.json'), read(run/'assessment.json')
        require(runner.sha(run/'final_model.joblib') == manifest['model_sha256']
                and runner.sha(run/'assessment.json') == manifest['assessment_sha256']
                and read(run/'independent-verification.json')['status'] == 'passed'
                and assessment['replace_H2_as_research_candidate'], 'attribute_live_unverified_model')
        fitted = joblib.load(run/'final_model.joblib')
        require(fitted['case'] == 'D0', 'attribute_live_only_D0')
        horses = public['horses']
        rows = {horse_number(r['horse_no']): r for r in card['runners'] if r['status'] == 'active'}
        require(set(rows) == set(horses) and len(rows) == len(horses), 'attribute_live_roster')
        attrs = []
        for number in horses:
            row = rows[number]
            age, female, gelding = runner.model.sex_age_attributes(row['sex_age'])
            frame = row['frame_no']
            known = frame is not None and str(frame).isdigit() and 1 <= int(frame) <= 8
            attrs.append([age, female, gelding, int(frame)/8 if known else .5, int(number)/len(horses), int(not known)])
        pair_prices = price_array(odds, 'quinella', list(combinations(horses, 2)))
        q = 1/pair_prices
        q /= q.sum()
        # JSONの倍精度listを、学習datasetと同じfloat32特徴契約へ戻す。
        record = {**public, 'x': np.asarray(public['x'], dtype=np.float32), 'market': q, 'pl': pl_pairs(1/price_array(odds, 'win', [(h,) for h in horses])),
                  'attributes': np.asarray(attrs, dtype=np.float32), 'race_flags': np.zeros(3, dtype=np.float32)}
        p = runner.model.predict(fitted, record)
        require(np.allclose(p, independent_predict(fitted, record), rtol=1e-12, atol=1e-14), 'attribute_live_independent')
        require(np.array_equal(p, runner.model.predict(fitted, {**record, 'winner': -1, 'payout_yen': -1})), 'attribute_live_result_dependency')
        contexts = runner.model.core.base.contexts(record, 'C2')
        forecast = {**ranking(p, horses), 'case': 'D0', 'race_id': public['race_id'], 'race_date': public['race_date'],
            'race_name': card['race_name'], 'created_at': now.isoformat(), 'trained_through': fitted['trained_through'],
            'horse_names': {n: rows[n]['horse_name'] for n in horses}, 'model_sha256': manifest['model_sha256'],
            'active_contexts': [c for c in contexts if c in fitted['contexts']],
            'fallback_contexts': [c for c in contexts if c not in fitted['contexts']],
            'probability_type': 'quinella_and_top2_marginal_not_win_probability', 'market_input': True,
            'research_only': True, 'preview_only': True, 'production_adoption': False, 'same_day_recheck_required': True,
            'card_observed_at': card['fetched_at'], 'odds_observed_at': odds['fetched_at']}
        snapshot = {'card': card, 'odds': odds, 'input_quality': quality, 'public_features': public,
            'attributes': attrs, 'attribute_names': list(runner.model.ATTRIBUTES), 'race_flags_unused_by_D0': True,
            'model_sha256': manifest['model_sha256'], 'assessment': assessment}
        runner.save(folder/'forecast.json', forecast)
        runner.save(folder/'input.json', snapshot)
        receipt = None
        if args.save:
            stage = 'sql_save'
            from jra_srb.storage import build_analysis_store
            from jra_srb.storage_config import storage_backend
            require(storage_backend() == 'sqlserver', 'attribute_live_sql_required')
            ranks = [r['horse_no'] for r in forecast['horse_ranking']]
            prediction = {'predicted_ranking': ranks, 'predicted_top3': ranks[:3],
                'ranking_semantics': 'top2_marginal_not_finish_order', 'generated_before_result': True,
                'head_horse_numbers': [], 'axis_horse_numbers': ranks[:1], 'opponent_horse_numbers': ranks[1:5],
                'betting_decision_status': 'research_reference_no_purchase', 'prediction_tickets': [],
                'forecast': forecast, 'research_only': True, 'preview_only': True, 'production_adoption': False}
            prediction_id = f"jra-{public['race_id']}-attribute-D0-{now.strftime('%Y%m%dT%H%M%SZ')}"
            payload = {'prediction_id': prediction_id, 'race_id': public['race_id'],
                'theory_version': 'market-attribute-chimera:D0:spec365', 'mode': 'research_reference', 'budget': 0,
                'created_at': now.isoformat(), 'pre_race_snapshot': snapshot, 'prediction_json': prediction, 'prediction_tickets': []}
            runner.save(folder/'prediction_payload.json', payload)
            store = build_analysis_store(runner.ROOT/'data/db/analysis.sqlite')
            try:
                store.upsert_prediction_record(payload)
                saved = store.get_prediction_record(prediction_id)
                require(saved.race_id == public['race_id'] and digest(saved.prediction) == digest(prediction)
                        and not saved.prediction_tickets, 'attribute_live_readback_mismatch')
                receipt = {'prediction_id': prediction_id, 'readback_verified': True, 'prediction_sha256': digest(prediction)}
            finally:
                if hasattr(store, 'close'):
                    store.close()
        runner.save(folder/'verification.json', {'status': 'passed', 'runners': len(horses), 'pair_count': len(p),
            'probability_sum': float(p.sum()), 'independent_formula_equal': True, 'result_ignored': True,
            'sql_saved': bool(args.save), 'saved': receipt, 'purchase_yen': 0})
        print(receipt)
    except Exception as error:
        runner.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training-run', type=Path, required=True)
    parser.add_argument('--snapshot-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--save', action='store_true')
    score(parser.parse_args())
