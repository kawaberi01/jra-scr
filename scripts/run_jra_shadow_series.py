"""概要: 固定2モデルと芝限定候補の前向き比較を最長14日継続する。
作成日: 2026-11-07
入力: --output、--first、--last、固定済みspec454/455・モデルと既存API/SQL。
出力: 凍結protocol、日別既存worker原本、監督state、3候補の仮想集計。
実行例: uv run --frozen --extra ml python scripts/run_jra_shadow_series.py --check-only
注意事項: 各日09〜18時JST。実購入0円。既存API/collectorや恒久タスクは変更しない。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx

import run_jra_research_shadow as daily
from jra_srb import jra_research_shadow_series as series

ROOT, read, save, sha, require = daily.ROOT, daily.read, daily.save, daily.sha, daily.require
RESEARCH = ROOT / 'artifacts/jra_research/condition_gate_20261107'
SPECS = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec'


def fixed_sources():
    """予測・集計・学習器・取消判定・仕様とモデルをまとめてSHA固定する。"""
    paths = [Path(__file__), Path(series.__file__), Path(daily.__file__), Path(daily.shadow.__file__),
             Path(daily.learning.model.__file__), Path(daily.learning.model.base.__file__),
             Path(daily.learning.model.base.core.__file__), Path(daily.learning.model.base.core.base.__file__),
             Path(daily.extractors.__file__), Path(daily.learning.policy.__file__),
             SPECS / '453-固定候補の発走前仮想検証運用.md', SPECS / '454-条件制限の時系列再検証と継続運用.md',
             SPECS / '455-芝限定候補の前向き固定.md', RESEARCH / 'assessment.json',
             RESEARCH / 'independent-verification.json', ROOT / 'scripts/start_jra_shadow_series.ps1',
             ROOT / 'tests/test_jra_shadow_series.py', ROOT / 'scripts/audit_jra_forward_capture.py',
             ROOT / 'src/jra_srb/service.py', ROOT / 'src/jra_srb/models.py',
             ROOT / 'src/jra_srb/analysis_store.py', ROOT / 'src/jra_srb/storage.py'] + list(daily.MODELS.values())
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def protocol(first, last):
    """検算済み候補の値と最大14日の日程を確かめ、事前固定内容を返す。"""
    require(first == date(2026, 11, 8) and last == date(2026, 11, 21), 'series_fixed_date_contract')
    require(read(RESEARCH / 'independent-verification.json')['status'] == 'passed', 'series_research_not_verified')
    sources = fixed_sources()
    result = read(RESEARCH / 'assessment.json')['S0_P01_surface_pooled']
    require(result['total']['tickets'] == 284 and result['total']['net_yen'] == 4180
            and result['decision']['purchase_allowed'] is False, 'series_candidate_contract')
    return {'first_date': first.isoformat(), 'last_date': last.isoformat(), 'source_sha256': sources,
            'models_sha256': {c: sha(p) for c, p in daily.MODELS.items()},
            'policies': ['S0_T30_P01', 'M10_T10_A', 'S0_T30_P01_TURF'],
            'turf_overlay': {'surface': 'turf', 'start_date': first.isoformat(), 'stake_yen': 100,
                             'applied_to_saved_S0_P01_only': True, 'retrospective_results_included': False},
            'actual_purchase_allowed': False, 'operating_hours_jst': '09:00-18:00',
            'persistent_task_installed': False, 'auto_resume_after_pc_restart': False}


def read_payload(folder, pid):
    """日別新runの対応する事前payloadを読む。"""
    return read(folder / (pid + '-payload.json'))


def aggregate(folder, contract, state):
    """終了済み日だけを3候補へ集計し、今日以前の成績は混ぜない。"""
    rows = {name: [] for name in contract['policies']}
    for day, status in state['days'].items():
        if status['status'] != 'complete':
            continue
        run = folder / day
        saved = read(run / 'state.json')
        for pid, item in saved['records'].items():
            payload = read_payload(run, pid)
            require(payload['budget'] == 0 and payload['prediction_tickets'] == [], 'series_actual_purchase')
            require(item['status'] == 'evaluated', 'series_unevaluated')
            virtual = item.get('research_simulation', {})
            stake = item['virtual_stake_yen']
            row = {'race_id': item['race_id'], 'race_date': day, 'indices': [], 'tickets': int(stake > 0),
                   'stake_yen': stake, 'paid_yen': virtual.get('virtual_payout_yen', 0),
                   'hits': int(bool(virtual.get('hit'))) if stake else 0}
            key = 'S0_T30_P01' if item['case'] == 'S0' else 'M10_T10_A'
            rows[key].append(row)
            if item['case'] == 'S0':
                rows['S0_T30_P01_TURF'].append(series.turf_overlay(item, payload, contract['frozen_at'], date.fromisoformat(contract['first_date'])))
    summaries = {key: daily.learning.policy.summary(sorted(rr, key=lambda r: r['race_id'])) for key, rr in rows.items()}
    content = {'updated_at': datetime.now(timezone.utc).isoformat(), 'models': summaries,
               'rows': rows, 'actual_purchase_yen': 0, 'purchase_adoption': False}
    daily.write_state(folder / 'aggregate', content)
    return summaries


def execute(args):
    """SHA固定後に期限付き監督を実行し、所有する子だけを起動・終了管理する。"""
    contract = protocol(args.first, args.last)
    if args.check_only:
        print(json.dumps({'status': 'check_passed', 'first': args.first.isoformat(), 'last': args.last.isoformat(),
                          'policies': contract['policies'], 'frozen_files': len(contract['source_sha256']), 'actual_purchase_yen': 0}), flush=True)
        return
    folder = args.output.resolve()
    require(folder.is_relative_to(ROOT / 'artifacts/jra_research'), 'series_output_outside_research')
    require(datetime.now(series.JST).date() < args.first, 'series_must_freeze_before_start_day')
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'aggregate').mkdir()
    contract['frozen_at'] = datetime.now(timezone.utc).isoformat()
    save(folder / 'protocol.json', contract)
    state = {'pid': os.getpid(), 'status': 'starting', 'days': {}, 'errors': [],
             'first_date': args.first.isoformat(), 'last_date': args.last.isoformat(), 'actual_purchase_yen': 0}
    child = None
    try:
        aggregate(folder, contract, state)
        while True:
            now = datetime.now(series.JST)
            state['heartbeat_at'] = now.astimezone(timezone.utc).isoformat()
            current = series.phase(now, args.first, args.last)
            state['status'] = current
            daily.write_state(folder, state)
            require(fixed_sources() == contract['source_sha256'], 'series_frozen_source_changed')
            if current == 'finished':
                break
            if current == 'waiting' or now.date().isoformat() in state['days']:
                time.sleep(30)
                continue
            day = now.date().isoformat()
            healthy = False
            for attempt in range(3):
                try:
                    response = httpx.get('http://127.0.0.1:8000/health', timeout=3)
                    healthy = response.status_code == 200 and response.json().get('status') == 'ok'
                except (httpx.HTTPError, ValueError):
                    healthy = False
                if healthy:
                    break
                time.sleep(5)
            if not healthy:
                state['days'][day] = {'status': 'api_unavailable', 'actual_purchase_yen': 0}
                daily.write_state(folder, state)
                continue
            run = folder / day; run.mkdir(exist_ok=False)
            with (run / 'worker.stdout.log').open('x', encoding='utf-8') as stdout, (run / 'worker.stderr.log').open('x', encoding='utf-8') as stderr:
                child = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(daily.__file__)), '--date', day,
                    '--output', str(run)], cwd=ROOT, stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                state['days'][day] = {'status': 'running', 'pid': child.pid, 'started_at': datetime.now(timezone.utc).isoformat()}
                daily.write_state(folder, state)
                while child.poll() is None:
                    state['heartbeat_at'] = datetime.now(timezone.utc).isoformat()
                    daily.write_state(folder, state)
                    require(fixed_sources() == contract['source_sha256'], 'series_source_changed_during_child')
                    if (run / 'state.json').exists():
                        worker = read(run / 'state.json')
                        heartbeat = worker.get('heartbeat_at')
                        require(not heartbeat or (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)).total_seconds() < 600,
                                'series_child_stalled')
                    time.sleep(30)
                require(child.returncode == 0, 'series_daily_worker_failed')
            worker = read(run / 'state.json')
            require(worker['status'] == 'finished' and all(v['status'] == 'evaluated' for v in worker['records'].values()), 'series_daily_incomplete')
            state['days'][day] |= {'status': 'complete', 'predictions': len(worker['records']),
                                   'input_errors': len(worker['errors']), 'ended_at': datetime.now(timezone.utc).isoformat(),
                                   'no_input': len(worker['records']) == 0}
            aggregate(folder, contract, state)
            daily.write_state(folder, state)
            child = None
        state['status'] = 'finished'
    except Exception as error:
        state['status'] = 'failed'
        state['errors'].append({'reason': getattr(error, 'reason', str(error)), 'type': type(error).__name__})
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=15)
        raise
    finally:
        state['heartbeat_at'] = datetime.now(timezone.utc).isoformat()
        daily.write_state(folder, state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/shadow_series_20261108_20261121')
    parser.add_argument('--first', type=date.fromisoformat, default=date(2026, 11, 8))
    parser.add_argument('--last', type=date.fromisoformat, default=date(2026, 11, 21))
    parser.add_argument('--check-only', action='store_true')
    execute(parser.parse_args())
