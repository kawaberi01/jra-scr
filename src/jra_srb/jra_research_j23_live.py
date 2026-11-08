"""概要: 固定J23とQ03/Q06をSQL受領入力で参考推論し、事前保存と事後比較を行う。
作成日: 2026-10-23
入力: 開催属性、native API ID、保存済み公式receipt、固定モデルと元J23月別履歴。
出力: 新規研究run、任意の共通SQL参考予想、独立した発走後評価run。
実行例: uv run --frozen --extra ml python -X utf8 scripts/score_jra_j23_live.py --help
注意事項: 学習・自動取得・実購入・既定変更なし。公表時刻のないreceiptは性能評価対象外。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import gc
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest, horse_number, timestamp
from .jra_research_history import HistoryConfig
from .jra_research_j23_policy import monthly_parameters, policy_stake
from .jra_research_native_card import _identity, _official_source_url
from .jra_research_r1_calibration import select_pair
from .jra_research_r1_live import LiveAnnualReader, read_json, require, validate_card, numeric
from .jra_research_reader import ResearchReader
from .jra_research_resources import check_memory
from .jra_research_runtime import _payload, _utc, _time_key, select_runtime_bundle
from .jra_research_runtime_sql import _preflight
from . import jra_research_chimera_thirty_features as features
from . import jra_research_chimera_thirty_model as learner


SOURCE_RUN = '20261022T080510Z_b6a4eb0716114496b680ea3378644159'
MODEL_SHA = 'cc69d01c7b01776f30b5d55fa286fc0428eb58f41faecd72a7f32686f875034e'
MONTHLY_SOURCE_SHA = '8df204672b9fe79ca67766cb8b8de13aa4d7e61c7e3d3183dcf4273ed8826a8d'
POLICIES = ('J23', 'Q03', 'Q06')
PROTOCOL = 'spec250-j23-frozen-reference-v1'


def now_utc():
    """実行時のUTC時刻を返す。"""
    return datetime.now(timezone.utc)


def load_frozen(day):
    """明示固定モデルのSHAを確認してからロードし、当月係数を元セルから再構成する。

    Raises:
        ResearchError: モデル変更、対象日以前の学習でない、月別履歴が不完全。
    Notes:
        joblibは本リポジトリの既知SHAのファイルだけを読む。再学習しない。
    """
    folder = existing_run(SOURCE_RUN) / 'cells'
    cell = read_json(folder / '2026-09_J23.json')
    model_path = folder / '2026-09_J23.joblib'
    require(cell['model_file'] == model_path.name and cell['model_sha256'] == MODEL_SHA
            and hashlib.sha256(model_path.read_bytes()).hexdigest() == MODEL_SHA,
            'j23_model_sha_mismatch')
    model = joblib.load(model_path)
    require(model['case'] == 'J23' and model['trained_through'] == cell['trained_through'] < day,
            'j23_model_not_before_target')
    require(model['coef'].shape == model['scale'].shape == (28,)
            and np.isfinite(model['coef']).all() and np.isfinite(model['scale']).all()
            and (model['scale'] > 0).all(), 'j23_model_shape')
    months, hashes = {}, {}
    for path in sorted(folder.glob('*_J23.json')):
        value = read_json(path)
        require(value['case'] == 'J23' and value['status'] == 'evaluated'
                and value['month'] not in months, 'j23_incomplete_monthly_source')
        months[value['month']] = [r for r in value['rows'] if r['stake']]
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    require(len(months) == 30 and digest(hashes) == MONTHLY_SOURCE_SHA, 'j23_monthly_source_changed')
    parameters = monthly_parameters(months, day[:7])
    provenance = {'source_run': SOURCE_RUN, 'model_file': model_path.name,
                  'model_sha256': MODEL_SHA, 'trained_through': model['trained_through'],
                  'train_races': cell['train_races'], 'monthly_source_sha256': digest(hashes),
                  'policy_sha256': hashlib.sha256((ROOT/'src/jra_srb/jra_research_j23_policy.py').read_bytes()).hexdigest()}
    return model, parameters, provenance


def receipt_rows(reader, identity, cutoff, *, result_only=False):
    """既存race索引で1競走のカード/市場または結果を本文32MiB・1,000行以内に限定する。

    Args:
        reader: 権限・版・索引のpreflight済み研究reader。
        identity: 属性照合済みnative API ID。
        cutoff: timezone付きのSQL受領日時上限。
        result_only: Trueなら結果だけ、Falseならカードと市場だけを読む。
    Returns:
        メモリ内の受領本文・SHA・時刻。
    Raises:
        ResearchError: 行数/本文量上限、ID不一致、SQL失敗。
    Notes:
        scoreでは結果operationをSQL条件から除く。本文はメモリ内だけに保持する。
    """
    operations = "operation=N'race_result'" if result_only else "operation IN (N'race_card',N'odds')"
    sql = ("SELECT request_sha256,operation,race_id,received_at_utc,"
           "CASE WHEN SUM(CONVERT(bigint,DATALENGTH(payload_json))) OVER ()<=33554432 "
           "THEN payload_json ELSE NULL END payload_json FROM ("
           "SELECT TOP (1001) request_sha256,operation,race_id,payload_json,"
           "CONVERT(varchar(33),received_at_utc,126) received_at_utc "
           "FROM api_runtime.write_receipts WHERE race_sha256=CONVERT(binary(32),?) "
           "AND CONVERT(varbinary(max),race_id)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?)) "
           "AND received_at_utc<=CONVERT(datetime2(7),?) AND " + operations +
           " ORDER BY received_at_utc,request_sha256) bounded_receipts ORDER BY received_at_utc,request_sha256")
    rows = reader._small('j23:receipt_result' if result_only else 'j23:receipt_inputs', sql,
                         (hashlib.sha256(identity.api_race_id.encode('utf-16le')).digest(),
                          identity.api_race_id, _utc(cutoff).removesuffix('+00:00')))
    require(len(rows) <= 1000, 'j23_receipt_row_limit')
    require(all(r['payload_json'] is not None and r['race_id'] == identity.api_race_id for r in rows),
            'j23_receipt_payload_limit_or_identity')
    return rows


def select_official(rows, identity, operation, cutoff, *, market=None, decision=None):
    """公式source内で同時刻競合を拒否し、既存時点選択を使って最新の完全束を返す。"""
    sources = set()
    for row in rows:
        if row['operation'] != operation:
            continue
        payload, body = _payload(row, identity, operation)
        if market and (payload['odds_timing'] != 't_minus_30m'
                       or market not in body.get('odds', {}) and payload['bet_type'] != market):
            continue
        require(_official_source_url(body['source']), 'j23_nonofficial_receipt')
        sources.add(body['source'])
    require(bool(sources), 'j23_missing_official_receipt')
    candidates = [select_runtime_bundle(rows, identity, operation=operation, source=source,
                                       knowledge_cutoff=cutoff, decision_cutoff=decision,
                                       bet_type=market, odds_timing='t_minus_30m' if market else None)
                  for source in sorted(sources)]
    latest = max(_time_key(b.known_at) for b in candidates)
    candidates = [b for b in candidates if _time_key(b.known_at) == latest]
    require(len({b.payload_sha256 for b in candidates}) == 1, 'j23_ambiguous_official_revision')
    return candidates[0]


def evidence(bundle):
    """未登録の統一IDや公表時刻を作らず、native受領証跡だけを返す。"""
    return {'api_race_id': bundle.identity.api_race_id, 'unified_race_id': None,
            'identity_status': 'native_api_attributes_only', 'operation': bundle.operation,
            'source': bundle.source, 'selection_key': bundle.selection_key,
            'received_at_utc': bundle.known_at, 'fetched_at': bundle.provider_fetched_at,
            'announced_at': None, 'payload_sha256': bundle.payload_sha256,
            'odds_timing': bundle.odds_timing, 'bet_type': bundle.bet_type}


def odds_prices(bundle, market, keys):
    """明示市場の数値価格を馬集合・重複・発売状態と照合して馬番順に返す。"""
    body = bundle.payload['odds']
    rows = body.get('odds', {}).get(market) if body.get('odds') else body['entries']
    prices = {}
    for row in rows or []:
        require(row.get('bet_type') in (None, market), 'j23_mixed_market')
        key = tuple(sorted((horse_number(n) for n in row['combination']), key=int))
        require(len(key) == (1 if market == 'win' else 2) and len(set(key)) == len(key)
                and key not in prices, 'j23_duplicate_or_invalid_odds_key')
        try:
            value = float(row['odds'])
        except (TypeError, ValueError):
            raise ResearchError('j23_non_numeric_or_suspended_price') from None
        require(math.isfinite(value) and value >= 1, 'j23_invalid_odds_price')
        prices[key] = value
    require(set(prices) == set(keys), 'j23_market_roster_mismatch')
    return np.asarray([prices[k] for k in keys], dtype=float)


def market_inputs(card_bundle, win_bundle, pair_bundle, identity, now):
    """同じT30判断締切以前の公式カードと全単勝/馬連から入力を組み立てる。

    Returns:
        カード、有効馬、発走時刻、判断締切、ペア順序、単勝/馬連価格、入力証跡。
    Raises:
        ResearchError: 時刻・馬集合・発売・カード属性が不整合。
    """
    card = card_bundle.payload['card']
    runners, post = validate_card(card, identity.race_date, identity.course, identity.race_no, now)
    require(all(r['status'] == 'active' for r in card['runners']), 'j23_unresolved_withdrawal')
    deadline = post - timedelta(minutes=30)
    require(now <= deadline, 'j23_after_decision_cutoff')
    for bundle in (card_bundle, win_bundle, pair_bundle):
        require(_time_key(_utc(bundle.known_at)) <= _time_key(now.isoformat())
                and _time_key(_utc(bundle.provider_fetched_at)) <= _time_key(now.isoformat())
                and _time_key(_utc(bundle.known_at)) <= _time_key(deadline.isoformat())
                and _time_key(_utc(bundle.provider_fetched_at)) <= _time_key(deadline.isoformat()),
                'j23_input_after_cutoff')
        require(timedelta(0) <= now-timestamp(bundle.provider_fetched_at) <= timedelta(minutes=10),
                'j23_stale_market')
    require(win_bundle.odds_timing == pair_bundle.odds_timing == 't_minus_30m', 'j23_wrong_odds_horizon')
    numbers = [r['horse_no'] for r in runners]
    keys = list(combinations(numbers, 2))
    win = odds_prices(win_bundle, 'win', [(n,) for n in numbers])
    prices = odds_prices(pair_bundle, 'quinella', keys)
    # 現receiptは公表時刻を持たず、同一captureも保証しない。候補式と評価用賭金を分離する。
    quality = {'performance_eligible': False, 'scope': 'runtime_validation_only',
               'reasons': ['missing_announced_at', 'unproven_same_T30_capture', 'unmapped_unified_identity'],
               'inputs': [evidence(b) for b in (card_bundle, win_bundle, pair_bundle)]}
    return card, runners, post, deadline, keys, win, prices, quality


def read_inputs(identity, current_time, artifacts):
    """1競走の公式受領をSQLから読み、T30以前の有効な入力束を返す。

    Notes:
        長い履歴構築の後にも呼び、収集処理が保存した最新受領を再選択する。
        自らHTTP取得をせず、必要な新受領がなければ鮮度検査で停止する。
    """
    with ResearchReader(SimpleNamespace(raw={'limits': {'query_timeout_seconds': 30}})) as reader:
        artifacts.write_json('preflight.json', _preflight(reader, {'source_policy': {'source_key': 'analysis-current', 'snapshot_id': 34}}))
        cutoff = current_time.isoformat()
        rows = receipt_rows(reader, identity, cutoff)
        card_bundle = select_official(rows, identity, 'race_card', cutoff)
        _, post = validate_card(card_bundle.payload['card'], identity.race_date, identity.course, identity.race_no, current_time)
        decision = (post-timedelta(minutes=30)).isoformat()
        require(current_time <= timestamp(decision), 'j23_after_decision_cutoff')
        card_bundle = select_official(rows, identity, 'race_card', cutoff, decision=decision)
        win_bundle = select_official(rows, identity, 'odds', cutoff, market='win', decision=decision)
        pair_bundle = select_official(rows, identity, 'odds', cutoff, market='quinella', decision=decision)
    return market_inputs(card_bundle, win_bundle, pair_bundle, identity, current_time)


def build_history(runners, identity, artifacts):
    """2003年以降の既存年別readerからJ23の時計履歴を日末更新で再構築する。

    Args:
        runners: 馬名・年齢・直近公式履歴を含む有効出走馬。
        identity: 履歴の対象日を固定する競走属性。
        artifacts: 年別件数とdigestだけを保存する新規run。
    Returns:
        J23用履歴状態、horse_id照合済みの出走属性、履歴来歴。
    Raises:
        ResearchError: 本文/時計不正、履歴不足、同定曖昧、同日結果混入。
    Notes:
        対象日以降はSQL readerで除外。元研究でJ23が使う正常8頭以上の履歴条件を維持。
        公式カードの直近正常走より古い履歴は拒否し、公表時点の未証明を来歴へ残す。
    """
    day = identity.race_date
    births = {r['horse_name']: date.fromisoformat(day).year-int(numeric(r['sex_age'])) for r in runners}
    require(len(births) == len(runners), 'j23_duplicate_horse_name')
    states, matches, latest, years = features.previous.TwentyStates(), defaultdict(set), {}, {}
    config = HistoryConfig.load(ROOT/'configs/research/history_sql_v1.json')
    with LiveAnnualReader(config) as reader:
        artifacts.write_json('preflight.json', reader.preflight())
        for year in range(2003, date.fromisoformat(day).year+1):
            raw, audit = reader.year_before(year, day)
            daily = defaultdict(list)
            for key, source in sorted(raw.items()):
                for _, _, se in source['SE'].values():
                    name = se[40:76].decode('cp932').strip().replace('\u3000', '')
                    if name in births and year-features.old.native.number(se[82:84]) == births[name]:
                        matches[name].add(se[30:40].decode('ascii'))
                race, reason = features.old.native.parse_race(key, source)
                if reason:
                    continue
                require(race['day'] < day, 'j23_future_history')
                ra = source['RA'][2]
                seconds = {r['horse_no']: features.old.clock_seconds(source['SE'][r['horse_no']][2][338:342])
                           for r in race['runners']}
                going = features.old.native.number(ra[888:889] if race['surface'] == 0 else ra[889:890])
                require(going in (1, 2, 3, 4), 'j23_history_going')
                laps = [features.old.native.number(ra[890+j*3:893+j*3])/10 for j in range(25)]
                race['closing_total'] = sum([v for v in laps if v > 0][-3:]) if race['pace'] is not None else None
                daily[race['day']].append((race, seconds, going))
            del raw
            for past_day, updates in sorted(daily.items()):
                states.update_day(updates)
                for race, _, _ in updates:
                    for runner in race['runners']:
                        latest[runner['horse_id']] = past_day
            years[str(year)] = audit
            artifacts.write_json('coverage.json', {'stage': 'j23_history', 'years': years})
            print(json.dumps({'stage': 'j23_history', 'year': year,
                              'latest_raw_day': audit['latest_raw_day']}), flush=True)
            del daily
            gc.collect()
            check_memory(2**31)
    current, coverage = [], []
    for runner in runners:
        ids = matches[runner['horse_name']]
        require(len(ids) == 1, 'j23_horse_identity_missing_or_ambiguous')
        hid = next(iter(ids))
        require(hid in latest, 'j23_no_eligible_horse_history')
        official = [str(r['source_date']) for r in runner.get('official_recent_races', [])
                    if r.get('source_date') and r.get('finish_rank') is not None
                    and (r.get('field_size') or 0) >= 8 and str(r['source_date']) < day]
        require(not official or latest[hid] >= max(official), 'j23_history_stale_vs_official_card')
        current.append({'horse_no': runner['horse_no'], 'horse_id': hid,
                        'age': int(numeric(runner['sex_age'])), 'weight': numeric(runner['weight_carried']),
                        'frame': int(numeric(runner['frame_no'])), 'jockey': '', 'trainer': ''})
        coverage.append({'horse_no': runner['horse_no'], 'horse_id': hid, 'latest_eligible_day': latest[hid]})
    return states, current, {'years': years, 'horses': coverage, 'history_before': day,
                             'input_digest': digest({y: v['input_digest'] for y, v in years.items()}),
                             'strict_history_publication_verified': False, 'sqlite_used': False}


def public_record(states, race, win, prices):
    """既存時計特徴と同時点単勝PLを組み、J23の使用する12馬特徴だけを作る。"""
    public = states.public(race)
    x = np.column_stack((public['x'], public['extra'][:, 20:23])).astype(np.float32)
    require(x.shape == (len(race['runners']), 12) and np.isfinite(x).all(), 'j23_feature_shape')
    market = 1/prices
    market /= market.sum()
    # clean_recordの他ケース用欄はJ23のmatrixでは参照しない。
    return {'x': x, 'addition': np.empty((len(x), 0)), 'basic': np.empty((len(x), 0)),
            'styles': np.zeros(len(x)), 'density': 0., 'group': race['surface']*2+int(race['distance'] >= 2000),
            'market': market, 'pl': features.pl_pairs(1/win)}


def score(model, record, keys, prices, parameters):
    """結果非依存のJ23全ペア確率と、同じ元ペアに対する固定3政策の候補賭金を返す。"""
    clean = learner.clean_record(record)
    with threadpool_limits(limits=1):
        p = learner.predict(model, clean)
    require(len(p) == len(keys) == len(prices) and np.isfinite(p).all()
            and (p > 0).all() and abs(float(p.sum())-1) < 1e-9, 'j23_probability_contract')
    require(np.array_equal(p, learner.predict(model, learner.clean_record(
        {**record, 'winner': 999, 'payout_yen': 999999}))), 'j23_result_dependency')
    chosen = select_pair(p, prices, np.ones(len(p)))
    rows = [{'horses': list(key), 'probability': float(p[i]), 'market_probability': float(record['market'][i]),
             'quoted_odds': float(prices[i])} for i, key in enumerate(keys)]
    amounts = {name: 0 for name in POLICIES}
    if chosen is not None:
        amounts['J23'] = 600
        row = {'ticket_probability': float(p[chosen]), 'ticket_odds': float(prices[chosen])}
        amounts.update({name: policy_stake(name, row, parameters) for name in ('Q03', 'Q06')})
    policies = {name: {'candidate_stake_yen': amount, 'stake_yen': 0,
                       'reason': 'runtime_validation_only' if amount else 'no_base_pair' if chosen is None else 'adjusted_ev_below_1.05'}
                for name, amount in amounts.items()}
    return {'pairs': rows, 'chosen': rows[chosen] if chosen is not None else None,
            'policies': policies, 'outcome_independent': True}


def save_reference(output, store):
    """一意ID・既存idempotency receiptでSQL参考予想を保存し、commit後のサーバ時刻まで検査する。

    Args:
        output: 発走前の参考予測。実購入券は作らない。
        store: 既存SqlServerAnalysisStore。SQLiteや別Storeは拒否する。
    Returns:
        保存内容SHA、受信時刻、commit後のSQL時刻と読戻し検証結果。
    Raises:
        ResearchError: ID既存、時刻超過、SQL保存/再取得内容の不一致。
    """
    from .idempotency import current_key, register_request, request_digest
    from .sqlserver_store import SqlServerAnalysisStore

    require(isinstance(store, SqlServerAnalysisStore), 'j23_sql_store_required')
    deadline = timestamp(output['decision_cutoff'])
    require(now_utc() <= deadline, 'j23_save_after_cutoff')
    prediction_id = f"jra-{output['race_id']}-j23-reference-{output['run_id']}"
    try:
        store.get_prediction_record(prediction_id)
    except LookupError:
        pass
    else:
        raise ResearchError('j23_prediction_already_exists')
    prediction = {'research_only': True, 'generated_before_result': True, 'strategy': PROTOCOL,
                  'betting_decision_status': 'reference_only', 'predicted_ranking': [],
                  'predicted_top3': [], 'axis_horse_numbers': [], 'run_id': output['run_id'],
                  'forecast_sha256': digest(output), 'pairs': output['pairs'], 'chosen': output['chosen'],
                  'policies': output['policies'], 'model': output['model'], 'parameters': output['parameters'],
                  'quality': output['quality'], 'decision_cutoff': output['decision_cutoff']}
    payload = {'prediction_id': prediction_id, 'race_id': output['race_id'],
               'theory_version': PROTOCOL, 'mode': 'research_reference', 'budget': 0,
               'created_at': output['scored_at'], 'pre_race_snapshot': output['pre_race_snapshot'],
               'prediction_json': prediction, 'prediction_tickets': []}
    key = 'j23-reference:'+output['run_id']
    register_request(store.settings, key, bytes.fromhex(digest(payload)))
    token = current_key.set(key)
    try:
        receipt_key = request_digest('prediction_record', output['race_id'])
        store.upsert_prediction_record(payload)
    finally:
        current_key.reset(token)
    saved = store.get_prediction_record(prediction_id)
    require(saved.race_id == output['race_id'] and digest(saved.prediction) == digest(prediction)
            and digest(saved.pre_race_snapshot) == digest(payload['pre_race_snapshot'])
            and saved.budget == 0 and not saved.prediction_tickets, 'j23_sql_readback_mismatch')
    # ここはSELECTのみ。receiptは既存Storeが予測と同じtransactionで作成する。
    with store._connect(read_only=True) as conn:
        receipt = conn._raw("SELECT payload_json,CONVERT(varchar(33),received_at_utc,126) received_at_utc,"
                            "CONVERT(varchar(33),SYSUTCDATETIME(),126) confirmed_at_utc "
                            "FROM api_runtime.write_receipts WHERE request_sha256=?", (receipt_key,)).fetchone()
    require(receipt is not None and digest(json.loads(receipt[0])) == digest(payload), 'j23_receipt_readback_mismatch')
    received, confirmed = _utc(receipt[1], sql_utc=True), _utc(receipt[2], sql_utc=True)
    require(_time_key(received) <= _time_key(confirmed) <= _time_key(_utc(output['decision_cutoff']))
            and timestamp(output['scored_at']) <= timestamp(confirmed), 'j23_sql_confirmation_after_cutoff')
    return {'status': 'passed', 'prediction_id': prediction_id, 'request_sha256': receipt_key.hex(),
            'payload_sha256': digest(payload), 'forecast_sha256': digest(output),
            'received_at_utc': received, 'commit_confirmed_at_utc': confirmed,
            'readback_verified': True, 'actual_tickets': 0, 'append_only_guarantee': 'application_checked'}


def execute(day, course, race_no, race_id, *, save=False):
    """SQL保存済みの当日1競走を参考推論し、新規runと任意のSQL参考予想へ保存する。

    Args:
        day: JST開催日。YYYY-MM-DD形式で実行当日に限定する。
        course: 既存COURSESの競馬場コード。
        race_no: 1〜12の競走番号。
        race_id: 元APIの12桁ID。統一IDを生成しない。
        save: Trueなら空の実購入券とbudget=0で共通SQLへ保存する。
    Returns:
        run ID、動作検証区分、元選択ペア、3政策とSQL保存診断。
    Raises:
        ResearchError: 入力/履歴/モデル/時刻/保存が不成立。新runへ失敗を記録する。
    Notes:
        HTTP取得、学習、対象結果の読取は行わない。既存runを変更しない。
    """
    identity = _identity(race_id, day, course, race_no)
    artifacts = RunArtifacts({'protocol': PROTOCOL, 'date': day, 'course': course,
                              'race_no': race_no, 'race_id': race_id, 'save': save}, 'j23-live-reference')
    stage = 'load_frozen'
    try:
        current_time = now_utc()
        require(day == current_time.astimezone(timezone(timedelta(hours=9))).date().isoformat(), 'j23_same_day_required')
        model, parameters, provenance = load_frozen(day)
        stage = 'select_receipts'
        card, runners, post, deadline, keys, win, prices, quality = read_inputs(identity, current_time, artifacts)
        stage = 'history'
        states, current, coverage = build_history(runners, identity, artifacts)
        stage = 'refresh_receipts'
        fresh = read_inputs(identity, now_utc(), artifacts)
        fresh_card, fresh_runners, fresh_post = fresh[:3]
        attributes = ('horse_no', 'horse_name', 'sex_age', 'frame_no', 'weight_carried')
        require([{k: r[k] for k in attributes} for r in runners] ==
                [{k: r[k] for k in attributes} for r in fresh_runners]
                and post == fresh_post and card['surface'] == fresh_card['surface']
                and card['distance'] == fresh_card['distance'], 'j23_card_changed_during_history')
        card, runners, post, deadline, keys, win, prices, quality = fresh
        require(card['surface'] in ('芝', 'ダート') and numeric(card['distance']) > 0, 'j23_invalid_race_attributes')
        race = {'day': day, 'ordinal': date.fromisoformat(day).toordinal(), 'course': int(race_id[8:10]),
                'distance': int(numeric(card['distance'])), 'surface': int(card['surface'] == 'ダート'), 'runners': current}
        record = public_record(states, race, win, prices)
        stage = 'score'
        prediction = score(model, record, keys, prices, parameters)
        scored_at = now_utc()
        require(scored_at <= deadline, 'j23_preparation_exceeded_cutoff')
        quality['reasons'].append('unproven_history_publication_time')
        definition = [features.__file__, features.previous.__file__, features.old.__file__, learner.__file__, __file__]
        snapshot = {'race_id': race_id, 'race_date': day, 'course': course, 'race_no': race_no,
                    'roster': [{'horse_no': r['horse_no'], 'horse_name': r['horse_name']} for r in runners],
                    'post_time': post.isoformat(), 'post_time_source': card['source'], 'inputs': quality['inputs'],
                    'history_digest': coverage['input_digest'], 'feature_digest': digest(record['x'].tolist()),
                    'feature_definition_sha256': digest({str(Path(p).relative_to(ROOT)): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                                         for p in definition})}
        output = {'status': 'reference_only', 'protocol': PROTOCOL, 'run_id': artifacts.run_id,
                  'race_id': race_id, 'race_date': day, 'course': course, 'race_no': race_no,
                  'post_time': post.isoformat(), 'decision_cutoff': deadline.isoformat(),
                  'scored_at': scored_at.isoformat(), 'model': provenance, 'parameters': parameters,
                  'parameters_sha256': digest(parameters), 'quality': quality, 'pre_race_snapshot': snapshot,
                  'actual_tickets': [], 'new_fits': 0, 'outcome_read': False, **prediction}
        artifacts.write_json('coverage.json', coverage)
        artifacts.write_json('metrics.json', output)
        sql_report = None
        if save:
            stage = 'sql_save_and_readback'
            from .storage import build_analysis_store
            from .storage_config import storage_backend
            os.environ.setdefault('JRA_SRB_STORAGE_ENV_FILE', str(ROOT/'data/storage/runtime.env'))
            require(storage_backend() == 'sqlserver', 'j23_sql_backend_required')
            sql_report = save_reference(output, build_analysis_store(ROOT/'data/db/analysis.sqlite'))
            with (artifacts.path/'sql-save-verification.json').open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(sql_report, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
        artifacts.finish(overall_complete=False, performance_eligible=False, outcome_read=False,
                         metrics_sha256=digest(output), sql_save=sql_report)
        return {'run_id': artifacts.run_id, 'status': output['status'], 'quality': quality,
                'chosen': output['chosen'], 'policies': output['policies'], 'sql_save': sql_report}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError('j23_live_failed', 4, error_type=type(error).__name__)
        safe.details['stage'] = stage
        if save:
            safe.details['sql_prediction_id'] = f'jra-{race_id}-j23-reference-{artifacts.run_id}'
        artifacts.fail(safe)
        safe.details['run_id'] = artifacts.run_id
        raise safe from None


def settle(output, result):
    """正常な一意着順と明示馬連払戻を照合し、保存時の3政策だけを精算する。

    Notes:
        同着、取消、不明精算は拒否。締切オッズを払戻から逆算しない。
    """
    require(result['race_id'] == output['race_id'] and _official_source_url(result['source']), 'j23_result_identity_or_source')
    require(timestamp(result['fetched_at']) >= timestamp(output['post_time']), 'j23_result_before_post')
    rows = result['results']
    require(len(rows) >= 8 and all(re.fullmatch(r'[0-9]+', r['rank']) for r in rows), 'j23_unresolved_settlement')
    require(sorted(int(r['rank']) for r in rows) == list(range(1, len(rows)+1)), 'j23_nonunique_result_rank')
    roster = {r['horse_no'] for r in output['pre_race_snapshot']['roster']}
    require(len(rows) == len(roster) and {horse_number(r['horse_no']) for r in rows} == roster, 'j23_result_roster_mismatch')
    winners = sorted((horse_number(r['horse_no']) for r in rows if int(r['rank']) <= 2), key=int)
    payouts = [p for p in result['payouts'] if p['bet_type'] in ('quinella', '馬連')]
    require(len(payouts) == 1, 'j23_missing_or_ambiguous_quinella_payout')
    numbers = re.findall(r'[0-9]+', payouts[0]['combination'])
    require(len(numbers) == 2 and sorted((horse_number(n) for n in numbers), key=int) == winners,
            'j23_winner_payout_mismatch')
    raw = payouts[0]['payout'].strip().removesuffix('円').replace(',', '')
    require(raw.isascii() and raw.isdigit() and int(raw) > 0 and int(raw) % 10 == 0, 'j23_invalid_payout')
    chosen = output['chosen']
    hit = chosen is not None and chosen['horses'] == winners
    policies = {}
    for name in POLICIES:
        stake = output['policies'][name]['stake_yen']
        require(type(stake) is int and stake in (0, 600), 'j23_invalid_saved_stake')
        require(output['quality']['performance_eligible'] or stake == 0, 'j23_ineligible_saved_stake')
        returned = int(raw)*(stake//100) if hit else 0
        policies[name] = {'stake_yen': stake, 'payout_yen': returned, 'profit_yen': returned-stake,
                          'hit': bool(hit and stake)}
    winning = next(p for p in output['pairs'] if p['horses'] == winners)
    p = np.asarray([r['probability'] for r in output['pairs']])
    q = np.asarray([r['market_probability'] for r in output['pairs']])
    target = np.asarray([r['horses'] == winners for r in output['pairs']], dtype=float)
    return {'race_id': output['race_id'], 'performance_eligible': output['quality']['performance_eligible'],
            'winning_horses': winners, 'quinella_payout_per_100_yen': int(raw), 'policies': policies,
            'accuracy': {'J23_logloss': -math.log(winning['probability']),
                         'M0_logloss': -math.log(winning['market_probability']),
                         'J23_pair_brier': float(np.mean((p-target)**2)), 'M0_pair_brier': float(np.mean((q-target)**2))},
            'closing_price': None, 'closing_price_status': 'unavailable_not_imputed', 'adopted': False}


def verify_saved_receipt(reader, manifest, output):
    """事後比較時にSQL受領本文を再照合し、ローカルのみの参考予想と区別する。"""
    saved = manifest.get('sql_save')
    if saved is None:
        require(not output['quality']['performance_eligible'], 'j23_eligible_forecast_without_sql_save')
        return {'status': 'local_reference_only', 'readback_verified': False}
    require(saved['status'] == 'passed' and saved['forecast_sha256'] == digest(output)
            and _time_key(saved['commit_confirmed_at_utc']) <= _time_key(_utc(output['decision_cutoff'])),
            'j23_saved_receipt_evidence_changed')
    rows = reader._small('j23:verify_prediction_receipt',
                         "SELECT operation,race_id,payload_json,CONVERT(varchar(33),received_at_utc,126) received_at_utc "
                         "FROM api_runtime.write_receipts WHERE request_sha256=CONVERT(binary(32),?)",
                         (bytes.fromhex(saved['request_sha256']),))
    require(len(rows) == 1, 'j23_saved_receipt_missing')
    row = rows[0]
    payload = json.loads(row['payload_json'])
    require(row['operation'] == 'prediction_record' and row['race_id'] == output['race_id']
            and digest(payload) == saved['payload_sha256']
            and payload['prediction_json']['forecast_sha256'] == digest(output)
            and _time_key(_utc(row['received_at_utc'], sql_utc=True)) == _time_key(saved['received_at_utc']),
            'j23_saved_receipt_changed')
    return {'status': 'passed', 'readback_verified': True, 'prediction_id': saved['prediction_id']}


def evaluate(run_id):
    """元runを変更せず公式結果をSQLから取得し、新規評価runへ会計を保存する。

    Args:
        run_id: complete状態のJ23参考予測run ID。
    Returns:
        新規評価run ID、元予測とSQL受領の照合、3政策の会計、精度診断。
    Raises:
        ResearchError: 発走前、元予測改変、SQL受領不一致、公式結果/精算不成立。
    Notes:
        結果はSELECT専用で取得し、元予想やSQL予測を更新しない。
    """
    original = existing_run(run_id)
    manifest, output = read_json(original/'manifest.json'), read_json(original/'metrics.json')
    require(manifest['status'] == 'complete' and output['protocol'] == PROTOCOL
            and output['run_id'] == run_id and digest(output) == manifest['metrics_sha256'], 'j23_forecast_artifact_changed')
    require(now_utc() >= timestamp(output['post_time']), 'j23_evaluate_before_post')
    identity = _identity(output['race_id'], output['race_date'], output['course'], output['race_no'])
    artifacts = RunArtifacts({'protocol': PROTOCOL, 'forecast_run': run_id,
                              'forecast_sha256': digest(output)}, 'j23-post-race-comparison')
    try:
        with ResearchReader(SimpleNamespace(raw={'limits': {'query_timeout_seconds': 30}})) as reader:
            artifacts.write_json('preflight.json', _preflight(reader, {'source_policy': {'source_key': 'analysis-current', 'snapshot_id': 34}}))
            saved_verification = verify_saved_receipt(reader, manifest, output)
            cutoff = now_utc().isoformat()
            rows = receipt_rows(reader, identity, cutoff, result_only=True)
            bundle = select_official(rows, identity, 'race_result', cutoff)
        report = {'forecast_run': run_id, 'forecast_sha256': digest(output), 'result_evidence': evidence(bundle),
                  'forecast_sql_verification': saved_verification,
                  **settle(output, bundle.payload)}
        artifacts.write_json('metrics.json', report)
        artifacts.finish(overall_complete=False, metrics_sha256=digest(report), forecast_run=run_id,
                         performance_eligible=report['performance_eligible'], default_changed=False)
        return {'run_id': artifacts.run_id, **report}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError('j23_evaluation_failed', 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details['run_id'] = artifacts.run_id
        raise safe from None
