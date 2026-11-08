"""概要: 当日だけ固定2候補を発走前保存し、公式結果と仮想精算を自動照合する。
作成日: 2026-11-07
入力: --date、--output、SQL保存T30/T10、固定S0/M10モデル、ローカルAPI。
出力: 新UUIDの研究予想/受領証拠/評価、run台帳/ハートビート/停止理由。
実行例: uv run --frozen --extra ml python scripts/run_jra_research_shadow.py --once
注意事項: 実購入0円。当日18時JSTに停止。3連続エラーで停止。API/collector再起動なし。
"""

import os
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_var] = '1'

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
import json
import hashlib
from pathlib import Path
import time

import httpx
import joblib
import numpy as np

import run_jra_ten_minute as learning
from audit_jra_forward_capture import market_entries, instant
from jra_srb import extractors
from jra_srb import jra_research_shadow as shadow
from jra_srb.service import JraService
from jra_srb.storage import build_analysis_store
from jra_srb.jra_odds_timeline import parse_start_datetime
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.idempotency import current_key, register_request
from jra_srb.jra_research_result_wait import pending_result

ROOT, read, save, sha, require = learning.ROOT, learning.read, learning.save, learning.sha, learning.require
JST = timezone(timedelta(hours=9))
MODELS = {'S0': ROOT / 'artifacts/jra_research/current_attributes_S0_20261025/2026_S0.joblib',
          'M10': ROOT / 'artifacts/jra_research/ten_minute_20261107/2026_M10.joblib'}
SPEC = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit/spec/453-固定候補の発走前仮想検証運用.md'


def write_state(folder, state):
    """自分のrunの状態だけを一時ファイル経由で置換保存する。"""
    path = folder / 'state.json'
    temp = folder / 'state.next.json'
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
    temp.replace(path)


class Watcher:
    """既存原本の新しい保存だけを拾い、一回の当日研究セッションを管理する。"""

    def __init__(self, folder, target):
        """独立検算/ソースSHAを確認し、モデルと再開可能な台帳を初期化する。"""
        self.folder, self.target = folder, target
        folder.mkdir(parents=True, exist_ok=True)
        require(read(MODELS['M10'].parent / 'independent-verification-v2.json')['status'] == 'passed', 'M10_not_verified')
        require(read(MODELS['S0'].parent / 'independent-verification.json')['status'] == 'passed', 'S0_not_verified')
        self.hashes = {case: sha(path) for case, path in MODELS.items()}
        require(self.hashes['M10'] == read(MODELS['M10'].parent / '2026_M10.json')['model_sha256'], 'shadow_M10_hash')
        require(self.hashes['S0'] == read(MODELS['S0'].parent / 'manifest.json')['model_sha256'][MODELS['S0'].name], 'shadow_S0_hash')
        self.models = {case: joblib.load(path) for case, path in MODELS.items()}
        paths = [SPEC, Path(__file__), Path(shadow.__file__), Path(extractors.__file__), Path(learning.model.__file__)]
        sources = {str(p.relative_to(ROOT)): sha(p) for p in paths}
        protocol = {'target_date': target.isoformat(), 'models_sha256': self.hashes, 'source_sha256': sources,
                    'actual_purchase_allowed': False, 'stop_at': f'{target.isoformat()}T18:00:00+09:00'}
        if (folder / 'protocol.json').exists():
            require(read(folder / 'protocol.json') == protocol, 'shadow_resume_contract_changed')
        else:
            save(folder / 'protocol.json', protocol)
        self.state = read(folder / 'state.json') if (folder / 'state.json').exists() else {'records': {}, 'seen': [], 'errors': [], 'cycles': 0}
        self.markets, self.receipts_seen = {}, set()
        self.cursor = datetime.combine(target, datetime.min.time(), JST).astimezone(timezone.utc)
        self.store, self.service = build_analysis_store(), JraService()
        self.client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=35.)
        self.consecutive_errors = 0

    def new_markets(self):
        """当日受領を上限付き増分読取し、各時点/券種の最初の版を保持する。"""
        start, end = self.target.strftime('%Y%m%d') + '0000', (self.target + timedelta(days=1)).strftime('%Y%m%d') + '0000'
        with self.store._connect(read_only=True) as c:
            rows = c._raw('SELECT TOP(1001) request_sha256,race_id,payload_json,received_at_utc FROM api_runtime.write_receipts '
                'WHERE operation=? AND race_id>=? AND race_id<? AND received_at_utc>=? ORDER BY received_at_utc,request_sha256',
                ('odds', start, end, self.cursor.replace(tzinfo=None))).fetchall()
        require(len(rows) <= 1000, 'shadow_receipt_limit')
        for row in rows:
            digest = bytes(row['request_sha256']).hex()
            received = instant(row['received_at_utc'], sql_utc=True)
            self.cursor = max(self.cursor, received - timedelta(seconds=1))
            if digest in self.receipts_seen:
                continue
            self.receipts_seen.add(digest)
            payload = json.loads(row['payload_json'])
            bet, timing = payload.get('bet_type'), payload.get('odds_timing')
            if bet not in ('win', 'quinella') or timing not in ('t_minus_30m', 't_minus_10m'):
                continue
            self.markets.setdefault((row['race_id'], timing), {}).setdefault(bet, {'payload': payload,
                'received': received.isoformat(), 'request_sha256': digest})

    async def predict(self, key, timing, case, rule):
        """修正済み新プロセスの公式カードと鮮度適格市場で予想し、SQL/GET確認する。"""
        token = f'{key}:{case}'
        if token in self.state['seen']:
            return
        markets = self.markets[(key, timing)]
        if set(markets) != {'win', 'quinella'}:
            return
        now = datetime.now(timezone.utc)
        observed = {b: instant(v['payload']['odds']['fetched_at']) for b, v in markets.items()}
        if any((now - t).total_seconds() > 180 or t > now + timedelta(seconds=2) for t in observed.values()):
            self.state['seen'].append(token)
            return
        course = learning.reuse.COURSES[int(key[8:10])]
        card = await self.service.get_race_card_by_number(self.target, course, int(key[10:]), refresh=True)
        post = parse_start_datetime(self.target, card.start_time)
        plain = card.model_dump(mode='json')
        quality = plain.get('data_status') or {}
        require(card.race_id == key and quality.get('source_kind') == 'pre_race_card'
                and quality.get('runner_set') == 'complete', 'shadow_card_quality')
        require(post and (post - datetime.now(timezone.utc)).total_seconds() >= 30, 'shadow_post_guard')
        bounds = (25, 35, 300) if timing == 't_minus_30m' else (7, 13, 180)
        lo, hi, gap = bounds
        require(all(lo <= (post - t).total_seconds() / 60 <= hi for t in observed.values())
                and (max(observed.values()) - min(observed.values())).total_seconds() <= gap, 'shadow_timing_guard')
        with self.store._connect(read_only=True) as c:
            require(c._raw('SELECT race_id FROM api_runtime.race_results WHERE race_id=?', (key,)).fetchone() is None, 'result_already_saved')
        self.store.write_card(self.target, course, int(key[10:]), card)
        horses = sorted([f'{int(r.horse_no):02d}' for r in card.runners if r.status == 'active'], key=int)
        odds = {bet: market_entries(v['payload']['odds'], bet, horses)[0] for bet, v in markets.items()}
        obs = {'race_id': key, 'race_date': self.target.isoformat(), 'timing': timing, 'card': plain,
               'odds': odds, 'post_at': post.isoformat(), 'observed_at': {b: t.isoformat() for b, t in observed.items()},
               'server_received_at': {b: v['received'] for b, v in markets.items()},
               'parser_sha256': sha(Path(extractors.__file__)), 'recorded_in_fresh_process': True}
        if case == 'M10':
            early_market = self.markets.get((key, 't_minus_30m'), {})
            require(set(early_market) == {'win', 'quinella'}, 'shadow_early_market_missing')
            early = obs | {'timing': 't_minus_30m',
                'odds': {b: market_entries(v['payload']['odds'], b, horses)[0] for b, v in early_market.items()},
                'observed_at': {b: v['payload']['odds']['fetched_at'] for b, v in early_market.items()},
                'server_received_at': {b: v['received'] for b, v in early_market.items()}, 'early_market_only': True}
            r = learning.model.from_observations(early, obs)
            p = learning.model.predict(self.models[case], r)
            obs['early_observation'] = early
        else:
            r = learning.model.base.from_capture(obs)
            p = learning.model.base.predict(self.models[case], r)
        prices = {tuple(v['combination']): v['odds'] for v in odds['quinella']}
        o = np.array([prices[k] for k in combinations(r['horses'], 2)])
        require(all((datetime.now(timezone.utc) - t).total_seconds() <= 180 for t in observed.values()), 'shadow_market_expired_during_card_fetch')
        payload = shadow.payload(r, p, o, obs, case, self.hashes[case], rule, post.isoformat())
        pid = payload['prediction_id']
        save(self.folder / (pid + '-payload.json'), payload)
        require(datetime.now(timezone.utc) < post - timedelta(seconds=20), 'shadow_save_too_late')
        request_key = 'spec453:' + pid
        register_request(self.store.settings, request_key, hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')).digest())
        context_token = current_key.set(request_key)
        try:
            self.store.upsert_prediction_record(payload)
        finally:
            current_key.reset(context_token)
        response = self.client.get('/jra/predictions/' + pid); response.raise_for_status()
        actual = response.json()
        require(actual['prediction'] == payload['prediction_json'] and actual['pre_race_snapshot'] == payload['pre_race_snapshot']
                and actual['budget'] == 0 and actual['prediction_tickets'] == [], 'shadow_full_readback')
        with self.store._connect(read_only=True) as c:
            receipt = c._raw('SELECT TOP(1) received_at_utc FROM api_runtime.write_receipts WHERE operation=? '
                'AND race_id=? AND JSON_VALUE(payload_json,?)=? ORDER BY received_at_utc DESC',
                ('prediction_record', key, '$.prediction_id', pid)).fetchone()
        require(receipt is not None and instant(receipt[0], sql_utc=True) < post, 'shadow_prediction_receipt_not_prerace')
        require(datetime.now(timezone.utc) < post, 'shadow_readback_after_post')
        save(self.folder / (pid + '-readback.json'), actual)
        self.state['records'][pid] = {'prediction_id': pid, 'race_id': key, 'case': case, 'rule': rule,
            'post_at': post.isoformat(), 'status': 'saved', 'virtual_stake_yen': payload['prediction_json']['research_plan']['total_stake_yen'],
            'server_received_at': instant(receipt[0], sql_utc=True).isoformat()}
        self.state['seen'].append(token)
        print('prediction_saved', key, case, pid, flush=True)
        return True

    def evaluate(self):
        """15分後に公式結果を照合し、型付き公開待ちは5分間隔で有限待機する。"""
        now = datetime.now(timezone.utc)
        for pid, item in self.state['records'].items():
            if item['status'] != 'saved' or now < datetime.fromisoformat(item['post_at']) + timedelta(minutes=15):
                continue
            if item.get('next_result_check_at') and now < datetime.fromisoformat(item['next_result_check_at']):
                continue
            response = self.client.get('/jra/predictions/' + pid); response.raise_for_status()
            require(response.json()['prediction']['generated_before_result'], 'shadow_saved_prediction_missing')
            key = item['race_id']; course = learning.reuse.COURSES[int(key[8:10])]
            response = self.client.post(f'/jra/meetings/{self.target.isoformat()}/{course}/races/{int(key[10:])}/result/save')
            if response.status_code in (400, 404):
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                waiting = pending_result(response.status_code, body, self.target, course, int(key[10:]), now)
                item['last_result_response'] = {'status_code': response.status_code, 'body': body}
                if waiting:
                    item['last_result_state'] = waiting
                    item['next_result_check_at'] = (now + timedelta(minutes=5)).isoformat()
                    continue
            response.raise_for_status()
            require(response.json()['race_id'] == key, 'shadow_result_identity')
            eid = 'eval-' + pid
            self.store.evaluate_prediction_record({'prediction_id': pid, 'evaluation_id': eid})
            response = self.client.get('/jra/evaluations/' + eid); response.raise_for_status()
            actual = response.json()
            require(actual['prediction_id'] == pid and actual['total_bet'] == 0, 'shadow_evaluation_actual_purchase')
            if item['virtual_stake_yen']:
                summary = actual['evaluation'].get('summary', actual['evaluation'])
                virtual = summary.get('research_simulation')
                require(virtual and virtual['status'] == 'available' and virtual['virtual_stake_yen'] == item['virtual_stake_yen'], 'shadow_virtual_evaluation_missing')
                item['research_simulation'] = virtual
            item |= {'status': 'evaluated', 'evaluation_id': eid}
            item.pop('next_result_check_at', None)
            item['last_result_state'] = 'evaluated'
            self.consecutive_errors = 0
            save(self.folder / (eid + '-readback.json'), actual)
            print('evaluation_saved', pid, eid, flush=True)

    async def tick(self):
        """新原本と既存予想を一巡し、結果/入力不足は理由付きで保持する。"""
        self.new_markets()
        for key, timing in sorted(self.markets):
            if timing not in ('t_minus_30m', 't_minus_10m'):
                continue
            case, rule = ('S0', 'P01') if timing == 't_minus_30m' else ('M10', 'A')
            try:
                if await self.predict(key, timing, case, rule):
                    self.consecutive_errors = 0
            except Exception as error:
                reason = getattr(error, 'reason', str(error)) if isinstance(error, (ValueError, ResearchError)) else type(error).__name__
                self.state['errors'].append({'race_id': key, 'case': case, 'reason': reason, 'at': datetime.now(timezone.utc).isoformat()})
                self.state['seen'].append(f'{key}:{case}')
                if isinstance(error, ValueError) or getattr(error, 'reason', None):
                    continue
                self.consecutive_errors += 1
                if self.consecutive_errors >= 3:
                    raise RuntimeError('three_consecutive_shadow_errors')
        try:
            self.evaluate()
        except httpx.HTTPError as error:
            self.consecutive_errors += 1
            self.state['errors'].append({'phase': 'evaluation', 'reason': type(error).__name__,
                                         'at': datetime.now(timezone.utc).isoformat()})
            if self.consecutive_errors >= 3:
                raise RuntimeError('three_consecutive_evaluation_errors') from error
        self.state['cycles'] += 1
        self.state['heartbeat_at'] = datetime.now(timezone.utc).isoformat()
        write_state(self.folder, self.state)


def run(args):
    """指定日の18時まで監視し、一巡モード/停止理由と自分のPIDを保存する。"""
    watcher = Watcher(args.output, date.fromisoformat(args.date))
    stop = datetime.combine(watcher.target, datetime.min.time(), JST).replace(hour=18)
    watcher.state['pid'] = os.getpid()
    watcher.state['status'] = 'running'
    watcher.state['stop_at'] = stop.isoformat()
    try:
        while datetime.now(JST) < stop and datetime.now(JST).date() == watcher.target:
            asyncio.run(watcher.tick())
            if args.once:
                break
            time.sleep(60)
        watcher.state['status'] = 'one_pass_complete' if args.once else 'finished'
    except Exception as error:
        watcher.state['status'] = 'failed'
        watcher.state['stop_reason'] = type(error).__name__
        write_state(watcher.folder, watcher.state)
        raise
    watcher.state['heartbeat_at'] = datetime.now(timezone.utc).isoformat()
    write_state(watcher.folder, watcher.state)
    print(json.dumps({'status': watcher.state['status'], 'records': len(watcher.state['records']), 'errors': len(watcher.state['errors']), 'output': str(args.output)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', default='2026-11-07')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/jra_research/shadow_sessions_20261107_v3')
    parser.add_argument('--once', action='store_true')
    run(parser.parse_args())
