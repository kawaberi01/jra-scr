"""概要: 保存履歴状態と対象日前の追加SQL履歴から、公式出馬表の新キメラ入力を作る。
作成日: 2026-10-24
入力: 学習runのhistory_state.joblibとmanifest、公式カードJSON、対象日/場/番号。
出力: 新規フォルダーの発走前特徴・入力品質・追加年coverage。予想そのものは保存しない。
実行例: uv run --frozen --extra ml python scripts/prepare_jra_condition_input.py --training-run artifacts/jra_research/condition_chimera_20261024 --card artifacts/predictions/20261025-condition-chimera/official-card.json --date 2026-10-25 --course kyoto --race-no 11 --output artifacts/predictions/20261025-condition-chimera/input
注意事項: SQL SELECTのみ。カードは24時間以内の事前参考用。当日再確認が必要。再学習なし。
"""

import os
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import argparse
from datetime import date, datetime, time, timedelta
import gc
import json
from pathlib import Path
import re

import joblib

import run_jra_condition_chimera as training
from jra_srb.jra_research_r1_live import COURSES, JST, utc, numeric, require
from jra_srb.jra_research_native_card import _official_source_url
from jra_srb.jra_research_contracts import horse_number


def prepare(args):
    """同定・履歴最新性・日付境界を満たす18頭等の公開特徴を作り、新規保存する。

    Raises:
        ResearchError: 同定曖昧、履歴不足/古さ、公式カード不備、時点違反。
    Notes:
        原文と結果ラベルを出力せず、訓練runの履歴を変更しない。
    """
    folder = args.output
    folder.mkdir(parents=True, exist_ok=False)
    stage = 'card'
    try:
        card = json.loads(args.card.read_text('utf-8'))
        now = datetime.now(JST)
        day = date.fromisoformat(args.date)
        expected = day.strftime('%Y%m%d')+COURSES[args.course]+f'{args.race_no:02d}'
        require(card['race_id'] == expected and _official_source_url(card['source']), 'condition_card_identity')
        status = card.get('data_status') or {}
        require(status.get('runner_set') == 'complete' and status.get('source_kind') == 'pre_race_card', 'condition_card_incomplete')
        matched = re.fullmatch(r'(\d{1,2})時(\d{2})分', card['start_time'])
        require(matched is not None, 'condition_missing_post')
        post = datetime.combine(day, time(int(matched[1]), int(matched[2])), JST)
        require(now < post and timedelta(0) <= now-utc(card['fetched_at']) <= timedelta(days=1), 'condition_card_time')
        runners = sorted((r for r in card['runners'] if r.get('status') == 'active'), key=lambda r: int(r['horse_no']))
        require(8 <= len(runners) <= 18 and all(r.get('status') in ('active', 'withdrawn', 'excluded') for r in card['runners']),
                'condition_invalid_card_roster')
        require(len({r['horse_no'] for r in runners}) == len(runners), 'condition_duplicate_card_horse')
        stage = 'history_state'
        manifest = json.loads((args.training_run/'dataset-manifest.json').read_text('utf-8'))
        state_path = args.training_run/'history_state.joblib'
        require(training.sha(state_path) == manifest['history_state_sha256'], 'condition_history_sha')
        state = joblib.load(state_path)
        require(state['protocol'] == training.model.PROTOCOL and state['history_before'] <= args.date, 'condition_state_time')
        states, names, latest = state['states'], state['names'], state['latest']
        coverage = {}
        stage = 'additional_history'
        config = training.HistoryConfig.load(training.ROOT/'configs/research/history_sql_v1.json')
        with training.LiveAnnualReader(config) as reader:
            training.save(folder/'preflight.json', reader.preflight())
            for year in range(int(state['history_before'][:4]), day.year+1):
                raw, report = reader.year_before(year, args.date)
                daily, excluded = training.parse_updates(raw)
                for source in raw.values():
                    for _, _, se in source['SE'].values():
                        name = se[40:76].decode('cp932').strip().replace('\u3000', '')
                        born = year-training.features.old.native.number(se[82:84])
                        names.setdefault((name, born), set()).add(se[30:40].decode('ascii'))
                del raw
                for past_day, updates in sorted(daily.items()):
                    if past_day < state['history_before']:
                        continue
                    require(past_day < args.date, 'condition_target_day_history')
                    states.update_day(updates)
                    for race, _, _ in updates:
                        for runner in race['runners']:
                            latest[runner['horse_id']] = past_day
                coverage[str(year)] = {**report, 'excluded': excluded}
                training.save(folder/f'coverage-{year}.json', coverage[str(year)])
                training.log('updated_input_history', year=year, latest_raw_day=report['latest_raw_day'])
                del daily
                gc.collect()
        stage = 'identity_and_freshness'
        current, quality = [], []
        for runner in runners:
            name = runner['horse_name'].replace('\u3000', '')
            age = int(numeric(runner['sex_age']))
            identities = names.get((name, day.year-age), set())
            require(len(identities) == 1, 'condition_horse_identity_missing_or_ambiguous')
            hid = next(iter(identities))
            official = [r['source_date'] for r in runner.get('official_recent_races', [])
                        if r.get('source_date') and r.get('finish_rank') is not None
                        and (r.get('field_size') or 0) >= 8 and r['source_date'] < args.date]
            require(hid in latest and (not official or latest[hid] >= max(official)), 'condition_history_stale_vs_card')
            current.append({'horse_no': horse_number(runner['horse_no']), 'horse_id': hid, 'age': age,
                            'weight': numeric(runner['weight_carried']), 'frame': int(numeric(runner['frame_no']))})
            quality.append({'horse_no': horse_number(runner['horse_no']), 'horse_name': runner['horse_name'],
                            'horse_id': hid, 'latest_eligible_day': latest[hid],
                            'latest_official_normal_day': max(official) if official else None})
        require(card['surface'] in ('芝', 'ダート'), 'condition_unknown_surface')
        distance = int(str(card['distance']).replace(',', ''))
        race = {'key': expected, 'day': args.date, 'ordinal': day.toordinal(), 'course': int(COURSES[args.course]),
                'surface': int(card['surface'] == 'ダート'), 'distance': distance, 'runners': current}
        record = {'race_id': expected, 'race_date': args.date, 'course': race['course'], 'surface': race['surface'],
                  'distance': distance, 'horses': [r['horse_no'] for r in current], 'x': states.condition_public(race).tolist()}
        # J23参考比較用の12列も同じ履歴から保存し、オッズ未入力のまま保持する。
        public = states.public(race)
        legacy_x = training.np.column_stack((public['x'], public['extra'][:, 20:23])).astype(training.np.float32)
        training.save(folder/'input.json', record)
        training.save(folder/'j23_public_features.json', {'race_id': expected, 'race_date': args.date,
                      'horses': record['horses'], 'x': legacy_x.tolist()})
        training.save(folder/'quality.json', {'status': 'passed', 'race_id': expected, 'card_sha256': training.sha(args.card),
            'card_fetched_at': card['fetched_at'], 'prepared_at': now.isoformat(), 'history_before': args.date,
            'checkpoint_sha256': manifest['history_state_sha256'], 'additional_coverage': coverage,
            'horses': quality, 'historical_publication_verified': False, 'preview_only': True,
            'same_day_recheck_required': True, 'new_model_uses_market': False})
        training.log('input_ready', race_id=expected, runners=len(current), output=str(folder/'input.json'))
    except Exception as error:
        training.save(folder/'failure.json', {'stage': stage, 'type': type(error).__name__, 'reason': getattr(error, 'reason', type(error).__name__)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training-run', type=Path, required=True)
    parser.add_argument('--card', type=Path, required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--course', choices=list(COURSES), required=True)
    parser.add_argument('--race-no', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args())
