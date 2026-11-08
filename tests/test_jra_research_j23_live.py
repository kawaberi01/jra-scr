"""概要: J23参考推論の時点、元ペア固定、保存、精算、既存政策との互換を検証する。
作成日: 2026-10-23
入力: 合成の公式receiptとStore代替、既存固定J23モデル。
出力: pytestの検証結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_j23_live.py tests/test_j23_ten_aspects.py
注意事項: SQL/HTTP接続・学習・実購入なし。tmp_path以外の研究成果物を更新しない。
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import combinations
import json
from types import SimpleNamespace

import numpy as np
import pytest

from jra_srb import jra_research_j23_live as live
from jra_srb.jra_research_contracts import ResearchError, canonical_json, digest
from jra_srb.jra_research_j23_policy import estimate, monthly_parameters
from jra_srb.jra_research_native_card import _identity
from jra_srb.jra_research_runtime import RuntimeBundle
from jra_srb.sqlserver_store import SqlServerAnalysisStore


NOW = datetime(2026, 10, 23, 0, tzinfo=timezone.utc)
IDENTITY = _identity('202610230501', '2026-10-23', 'tokyo', 1)


def inputs():
    """公式8頭カードと全28馬連・8単勝の合成受領を作る。"""
    runners = [{'horse_no': f'{i:02d}', 'horse_name': f'馬{i}', 'frame_no': str(i),
                'sex_age': '牡3', 'weight_carried': '57.0', 'status': 'active'} for i in range(1, 9)]
    card = {'race_id': IDENTITY.api_race_id, 'race_name': '検証', 'source': 'https://www.jra.go.jp/card',
            'fetched_at': NOW.isoformat(), 'start_time': '12時00分', 'surface': '芝', 'distance': '1600m',
            'runners': runners, 'data_status': {'runner_set': 'complete', 'source_kind': 'pre_race_card'}}
    keys = list(combinations([r['horse_no'] for r in runners], 2))
    prices = {'win': [{'combination': [r['horse_no']], 'odds': '8.0'} for r in runners],
              'quinella': [{'combination': list(k), 'odds': '30.0'} for k in keys]}
    payloads = [{'date': IDENTITY.race_date, 'course': IDENTITY.course, 'race_no': 1, 'card': card}]
    payloads.extend({'bet_type': market, 'odds_timing': 't_minus_30m',
                     'odds': {'race_id': card['race_id'], 'source': 'https://www.jra.go.jp/odds',
                              'fetched_at': NOW.isoformat(), 'entries': [], 'odds': {market: rows}}}
                    for market, rows in prices.items())
    bundles = []
    for i, p in enumerate(payloads):
        market = p.get('bet_type')
        bundles.append(RuntimeBundle(IDENTITY, 'odds' if market else 'race_card',
                                     p['odds' if market else 'card']['source'], 'receipt', f'{i+1:064x}',
                                     NOW.isoformat(), NOW.isoformat(), NOW.isoformat(), digest(p), p,
                                     bet_type=market, odds_timing=p.get('odds_timing')))
    return bundles


def parameters():
    """空購入月を含む連続3月の中立係数を返す。"""
    return monthly_parameters({'2026-07': [], '2026-08': [], '2026-09': []}, '2026-10')


def forecast():
    """合成カードと既存J23特徴式から、保存・精算用の参考予測を作る。"""
    card, runners, post, deadline, keys, win, prices, quality = live.market_inputs(*inputs(), IDENTITY, NOW)
    race = {'day': IDENTITY.race_date, 'ordinal': NOW.date().toordinal(), 'course': 5, 'distance': 1600,
            'surface': 0, 'runners': [dict(r, horse_id=f'{i:010d}', age=3, weight=57., frame=i)
                                   for i, r in enumerate(runners, 1)]}
    record = live.public_record(live.features.previous.TwentyStates(), race, win, prices)
    model = {'case': 'J23', 'coef': np.zeros(28), 'scale': np.ones(28)}
    scored = live.score(model, record, keys, prices, parameters())
    output = {'status': 'reference_only', 'protocol': live.PROTOCOL, 'run_id': 'synthetic',
              'race_id': IDENTITY.api_race_id, 'race_date': IDENTITY.race_date, 'course': 'tokyo', 'race_no': 1,
              'post_time': post.isoformat(), 'decision_cutoff': deadline.isoformat(), 'scored_at': NOW.isoformat(),
              'pre_race_snapshot': {'roster': runners}, 'model': {'model_sha256': 'a'*64},
              'quality': quality, 'parameters': parameters(), **scored}
    return output, record, keys, prices


def receipt(bundle):
    """実writerと同じ要求SHAを付けた合成receiptを作る。"""
    business = deepcopy(bundle.payload)
    body = business['card'] if bundle.operation == 'race_card' else business['odds'] if bundle.operation == 'odds' else business
    body.pop('cache_hit', None)
    body.pop('meta', None)
    key = hashlib.sha256((bundle.operation+'\n'+IDENTITY.api_race_id+'\n'+canonical_json(business)).encode()).hexdigest()
    return {'operation': bundle.operation, 'race_id': IDENTITY.api_race_id,
            'request_sha256': key, 'payload_json': canonical_json(bundle.payload), 'received_at_utc': NOW.isoformat()}


def test_receipt_selection_validates_digest_and_rejects_late_input():
    """保存版SHAとT30市場名の一致を検査し、締切超過と改変を拒否する。"""
    bundle = inputs()[1]
    row = receipt(bundle)
    selected = live.select_official([row], IDENTITY, 'odds', NOW.isoformat(), market='win', decision=NOW.isoformat())
    assert selected.payload == bundle.payload
    late = dict(row, received_at_utc=(NOW+timedelta(seconds=1)).isoformat())
    with pytest.raises(ResearchError):
        live.select_official([late], IDENTITY, 'odds', late['received_at_utc'], market='win', decision=NOW.isoformat())
    with pytest.raises(ResearchError, match='digest_mismatch'):
        live.select_official([dict(row, request_sha256='0'*64)], IDENTITY, 'odds', NOW.isoformat(), market='win')


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'withdrawn', 'non_numeric', 'T10', 'future', 'stale'])
def test_market_input_rejects_invalid_capture(change):
    """全馬集合・発売・時点に問題がある受領では推論入力を作らない。"""
    bundles = inputs()
    if change == 'missing':
        bundles[2].payload['odds']['odds']['quinella'].pop()
    elif change == 'duplicate':
        rows = bundles[2].payload['odds']['odds']['quinella']
        rows.append(rows[0])
    elif change == 'withdrawn':
        bundles[0].payload['card']['runners'][-1]['status'] = 'withdrawn'
    elif change == 'non_numeric':
        bundles[1].payload['odds']['odds']['win'][0]['odds'] = '発売停止'
    elif change == 'T10':
        object.__setattr__(bundles[2], 'odds_timing', 't_minus_10m')
    elif change == 'future':
        object.__setattr__(bundles[1], 'known_at', (NOW+timedelta(seconds=1)).isoformat())
    else:
        object.__setattr__(bundles[1], 'provider_fetched_at', (NOW-timedelta(minutes=11)).isoformat())
    with pytest.raises(ResearchError):
        live.market_inputs(*bundles, IDENTITY, NOW)


def test_T30_boundary_and_unproven_capture_keep_stakes_zero():
    """T30境界は許容し、1秒超過を拒否、公表時刻がない候補は評価賭金0円にする。"""
    output, _, _, _ = forecast()
    assert output['chosen']['horses'] == ['01', '02']
    assert all(v['candidate_stake_yen'] == 600 and v['stake_yen'] == 0 for v in output['policies'].values())
    deadline = live.timestamp(output['decision_cutoff'])
    bundles = inputs()
    for b in bundles:
        object.__setattr__(b, 'known_at', deadline.isoformat())
        object.__setattr__(b, 'provider_fetched_at', deadline.isoformat())
        if b.operation == 'race_card':
            b.payload['card']['fetched_at'] = deadline.isoformat()
    live.market_inputs(*bundles, IDENTITY, deadline)
    with pytest.raises(ResearchError, match='after_decision'):
        live.market_inputs(*bundles, IDENTITY, deadline+timedelta(seconds=1))


def test_fixed_model_probabilities_match_independent_formula_and_ignore_results():
    """実固定モデルの入力行列から独立softmaxを計算し、結果注入後も確率が不変なことを確認する。"""
    model, params, provenance = live.load_frozen('2026-10-23')
    _, record, keys, prices = forecast()
    rng = np.random.default_rng(250)
    record['x'] = rng.normal(0, .2, (8, 12)).astype(np.float32)
    prices = rng.uniform(4, 60, len(keys))
    record['market'] = (1/prices)/(1/prices).sum()
    win = rng.uniform(.01, .4, 8);win /= win.sum()
    record['pl'] = live.features.pl_pairs(win)
    actual = live.score(model, record, keys, prices, params)
    # 研究matrixを呼ばず、公開式と実馬ペア順序からJ23の28列を独立構築する。
    left, right = np.asarray(list(combinations(range(8), 2))).T
    horse = record['x'];gap = np.clip(np.log(record['pl']/record['market']), -10, 10)
    raw = np.column_stack((np.log(record['market']), (horse[left]+horse[right])/2,
                           np.abs(horse[left]-horse[right]), gap,
                           gap*(horse[left, 0]+horse[right, 0])/2,
                           gap*(horse[left, 9]+horse[right, 9])/2))
    raw -= record['market']@raw
    x = raw.astype(np.float32)/model['scale'].astype(np.float32)
    z = np.log(record['market'])+x@model['coef']
    expected = np.exp(z-z.max());expected /= expected.sum()
    assert np.allclose([r['probability'] for r in actual['pairs']], expected, rtol=1e-12, atol=1e-14)
    assert live.score(model, dict(record, winner=999, payout_yen=999999), keys, prices, params) == actual
    assert provenance['model_sha256'] == live.MODEL_SHA
    assert np.isclose(params['recent']['probability'], 1.0097754532760763)


def test_receipt_precision_after_cutoff_is_not_rounded_down():
    """SQL datetime2の100ns単位で締切を超えた受領を拒否する。"""
    bundles = inputs()
    object.__setattr__(bundles[1], 'known_at', '2026-10-23T00:00:00.0000001+00:00')
    with pytest.raises(ResearchError, match='after_cutoff'):
        live.market_inputs(*bundles, IDENTITY, NOW)


def test_reordered_markets_keep_pair_order_and_no_reselection():
    """市場明細の順序・左右を変えても元ペアを維持し、Q03見送り時に次点へ買い替えない。"""
    output, record, keys, prices = forecast()
    bundles = inputs()
    for market, b in [('win', bundles[1]), ('quinella', bundles[2])]:
        rows = b.payload['odds']['odds'][market]
        rows.reverse()
        for r in rows:r['combination'].reverse()
    _, _, _, _, actual_keys, _, actual_prices, _ = live.market_inputs(*bundles, IDENTITY, NOW)
    assert actual_keys == keys and np.array_equal(actual_prices, prices)
    params = parameters()
    for fit in params['price_bands'].values():fit['price'] = .65
    changed = live.score({'case': 'J23', 'coef': np.zeros(28), 'scale': np.ones(28)}, record, keys, prices, params)
    assert changed['chosen'] == output['chosen']
    assert changed['policies']['Q03']['candidate_stake_yen'] == 0
    assert changed['policies']['Q06']['candidate_stake_yen'] == 600


def test_months_are_calendar_months_and_missing_month_is_not_skipped():
    """欠測月・未来月・当月結果を拒否し、購入なし月は完全な空月として扱う。"""
    params = parameters()
    assert params['recent_months'] == ['2026-07', '2026-08', '2026-09']
    assert estimate([])['probability'] == 1
    for months in [{'2026-06': [], '2026-08': [], '2026-09': []},
                   {'2026-07': [], '2026-08': [], '2026-09': [], '2026-10': []}]:
        with pytest.raises(ResearchError, match='prior_months'):
            monthly_parameters(months, '2026-10')
    bad = {'2026-07': [], '2026-08': [], '2026-09': [dict(race_date='2026-10-01', stake=600,
            ticket_probability=.1, ticket_odds=10., payout=0)]}
    with pytest.raises(ResearchError):monthly_parameters(bad, '2026-10')
    with pytest.raises(ResearchError, match='prior_months'):live.load_frozen('2026-11-01')


class FakeStore(SqlServerAnalysisStore):
    """SQL通信の代わりに保存payloadとサーバ時刻を返す既存Store代替。"""

    def __init__(self, *, duplicate=False, confirmed=None, tamper=False):
        """既存ID、締切超過、改変を切り替える。"""
        self.settings = SimpleNamespace()
        self.payload = None
        self.duplicate = duplicate
        self.confirmed = confirmed or NOW.isoformat()
        self.tamper = tamper

    def get_prediction_record(self, prediction_id):
        """保存前は未登録、保存後は読み戻した予想を返す。"""
        if self.duplicate:return SimpleNamespace()
        if self.payload is None:raise LookupError('not found')
        p = self.payload
        return SimpleNamespace(race_id=p['race_id'], prediction={'wrong': True} if self.tamper else p['prediction_json'],
                               pre_race_snapshot=p['pre_race_snapshot'], budget=p['budget'], prediction_tickets=[])

    def upsert_prediction_record(self, payload):
        """保存要求を保持し、実購入券が空であることを確認する。"""
        assert payload['prediction_tickets'] == [] and payload['budget'] == 0
        self.payload = deepcopy(payload)

    def _connect(self, *, read_only=False):
        """commit後のSELECTだけを受けるcontextを返す。"""
        assert read_only
        return self

    def __enter__(self):
        """読み戻し用のcontextへ入る。"""
        return self

    def __exit__(self, *args):
        """SQL接続を作らずcontextを終了する。"""

    def _raw(self, sql, params):
        """既存receiptとcommit後サーバ時刻のSELECT結果を返す。"""
        assert sql.startswith('SELECT') and 'SYSUTCDATETIME' in sql
        return SimpleNamespace(fetchone=lambda: (canonical_json(self.payload), NOW.isoformat(), self.confirmed))


def test_SQL_save_verifies_receipt_server_time_and_restores_context(monkeypatch):
    """空の実購入券とcommit後サーバ時刻を照合し、idempotency文脈を呼出後に戻す。"""
    from jra_srb import idempotency
    output, _, _, _ = forecast()
    monkeypatch.setattr(live, 'now_utc', lambda: NOW)
    monkeypatch.setattr(idempotency, 'register_request', lambda *a: None)
    store = FakeStore()
    report = live.save_reference(output, store)
    assert report['readback_verified'] and report['actual_tickets'] == 0
    assert report['forecast_sha256'] == digest(output)
    assert idempotency.current_key.get() is None


@pytest.mark.parametrize('kind,reason', [('duplicate', 'already_exists'), ('late', 'after_cutoff'), ('tamper', 'readback_mismatch')])
def test_SQL_save_rejects_existing_late_or_changed_content(monkeypatch, kind, reason):
    """既存予想の上書き、保存完了の締切超過、読戻し改変を拒否する。"""
    from jra_srb import idempotency
    output, _, _, _ = forecast()
    monkeypatch.setattr(live, 'now_utc', lambda: NOW)
    monkeypatch.setattr(idempotency, 'register_request', lambda *a: None)
    store = FakeStore(duplicate=kind == 'duplicate', tamper=kind == 'tamper',
                      confirmed=(live.timestamp(output['decision_cutoff'])+timedelta(seconds=1)).isoformat() if kind == 'late' else None)
    with pytest.raises(ResearchError, match=reason):live.save_reference(output, store)
    if kind == 'duplicate':assert store.payload is None


def official_result():
    """全8頭の正常一意着順と100円あたり1,110円の明示馬連払戻を返す。"""
    return {'race_id': IDENTITY.api_race_id, 'source': 'https://www.jra.go.jp/result',
            'fetched_at': (NOW+timedelta(hours=4)).isoformat(),
            'results': [{'horse_no': f'{i:02d}', 'rank': str(i), 'horse_name': f'馬{i}'} for i in range(1, 9)],
            'payouts': [{'bet_type': 'quinella', 'combination': '1-2', 'payout': '1,110円'},
                        {'bet_type': 'win', 'combination': '1', 'payout': '320円'}]}


def test_settlement_accounts_saved_stakes_without_imputing_closing_price():
    """参考区分は利益0円、適格な保存賭金は実払戻×口数で精算し、原予想を変えない。"""
    output, _, _, _ = forecast()
    original = deepcopy(output)
    report = live.settle(output, official_result())
    assert all(x['profit_yen'] == 0 for x in report['policies'].values())
    assert report['closing_price'] is None and not report['adopted']
    assert output == original
    # 精算純関数の会計を検証する合成適格予想。実CLIは適格区分を生成しない。
    output['quality']['performance_eligible'] = True
    output['policies']['J23']['stake_yen'] = 600
    report = live.settle(output, official_result())
    assert report['policies']['J23']['payout_yen'] == 6660
    assert report['policies']['J23']['profit_yen'] == 6060


@pytest.mark.parametrize('change', ['tie', 'missing', 'other_race', 'wrong_payout', 'before_post'])
def test_unresolved_results_are_not_counted_as_losses(change):
    """同着・欠落・別競走・精算不一致・発走前取得を外れ0円へ変換しない。"""
    output, _, _, _ = forecast()
    result = official_result()
    if change == 'tie':result['results'][1]['rank'] = '1'
    elif change == 'missing':result['payouts'] = []
    elif change == 'other_race':result['race_id'] = 'other'
    elif change == 'wrong_payout':result['payouts'][0]['combination'] = '1-3'
    else:result['fetched_at'] = NOW.isoformat()
    with pytest.raises(ResearchError):live.settle(output, result)


def test_score_failure_is_saved_in_new_run_without_touching_original(tmp_path, monkeypatch):
    """同日以外の実行は依存処理に入らず、新規runに固定理由を残す。"""
    from jra_srb import jra_research_artifacts
    monkeypatch.setattr(jra_research_artifacts, 'RUN_ROOT', tmp_path)
    monkeypatch.setattr(live, 'now_utc', lambda: NOW+timedelta(days=1))
    with pytest.raises(ResearchError, match='same_day'):
        live.execute('2026-10-23', 'tokyo', 1, IDENTITY.api_race_id)
    run = next(tmp_path.iterdir())
    assert json.loads((run/'manifest.json').read_text(encoding='utf-8'))['status'] == 'failed'
    assert not (run/'metrics.json').exists()


def test_forecast_queries_exclude_result_operation():
    """推論用SQLには結果operationを含めず、評価入口だけで結果を読む。"""
    queries = []
    reader = SimpleNamespace(_small=lambda name, sql, params: queries.append(sql) or [])
    live.receipt_rows(reader, IDENTITY, NOW.isoformat())
    assert "IN (N'race_card',N'odds')" in queries[0] and "N'race_result'" not in queries[0]
    live.receipt_rows(reader, IDENTITY, NOW.isoformat(), result_only=True)
    assert "operation=N'race_result'" in queries[1]


@pytest.mark.parametrize('card_change', [False, True])
def test_complete_score_and_evaluation_preserve_original_run(tmp_path, monkeypatch, card_change):
    """入力から成果物保存、別runへの結果精算まで接続し、元予測の全ファイルSHA不変を確認する。"""
    from jra_srb import jra_research_artifacts

    class Reader:
        """SQLを使わない接続寿命の代替。"""

        def __init__(self, config):
            """接続設定だけを受ける。"""

        def __enter__(self):
            """readerのcontextへ入る。"""
            return self

        def __exit__(self, *args):
            """DBを開かずcontextを終了する。"""

    def history(runners, identity, artifacts):
        """対象結果を使わない合成履歴と、カードの馬番号に対応するIDを返す。"""
        current = [dict(horse_no=r['horse_no'], horse_id=f'{i:010d}', age=3, weight=57., frame=i)
                   for i, r in enumerate(runners, 1)]
        return live.features.previous.TwentyStates(), current, {'input_digest': 'a'*64}

    monkeypatch.setattr(jra_research_artifacts, 'RUN_ROOT', tmp_path)
    monkeypatch.setattr(live, 'existing_run', lambda run_id: tmp_path/run_id)
    monkeypatch.setattr(live, 'ResearchReader', Reader)
    monkeypatch.setattr(live, '_preflight', lambda *a: {'status': 'passed_mock'})
    monkeypatch.setattr(live, 'now_utc', lambda: NOW)
    monkeypatch.setattr(live, 'load_frozen', lambda day: ({'case': 'J23', 'coef': np.zeros(28), 'scale': np.ones(28)}, parameters(), {}))
    monkeypatch.setattr(live, 'build_history', history)
    reads = []

    def fresh_receipts(*args, **kwargs):
        """履歴構築後の再受領で負担重量が変わるケースを作る。"""
        reads.append(True)
        bundles = inputs()
        if card_change and len(reads) > 1:
            bundles[0].payload['card']['runners'][0]['weight_carried'] = '58.0'
        return [receipt(b) for b in bundles]

    monkeypatch.setattr(live, 'receipt_rows', fresh_receipts)
    if card_change:
        with pytest.raises(ResearchError, match='card_changed_during_history'):
            live.execute(IDENTITY.race_date, 'tokyo', 1, IDENTITY.api_race_id)
        assert json.loads((next(tmp_path.iterdir())/'manifest.json').read_text(encoding='utf-8'))['status'] == 'failed'
        return
    scored = live.execute(IDENTITY.race_date, 'tokyo', 1, IDENTITY.api_race_id)
    original = tmp_path/scored['run_id']
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir()}
    body = official_result()
    result_bundle = RuntimeBundle(IDENTITY, 'race_result', body['source'], 'receipt', 'f'*64,
                                  body['fetched_at'], body['fetched_at'], body['fetched_at'], digest(body), body)
    row = receipt(result_bundle)
    row['received_at_utc'] = body['fetched_at']
    monkeypatch.setattr(live, 'now_utc', lambda: NOW+timedelta(hours=4))
    monkeypatch.setattr(live, 'receipt_rows', lambda *a, **k: [row])
    report = live.evaluate(scored['run_id'])
    assert report['run_id'] != scored['run_id']
    assert report['forecast_sql_verification']['status'] == 'local_reference_only'
    assert report['policies']['J23']['stake_yen'] == 0
    assert not report['performance_eligible']
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir()}


def test_result_rechecks_the_SQL_forecast_receipt(monkeypatch):
    """事後評価でSQL保存時の本文と受領時刻を再検証し、変更を拒否する。"""
    from jra_srb import idempotency
    output, _, _, _ = forecast()
    monkeypatch.setattr(live, 'now_utc', lambda: NOW)
    monkeypatch.setattr(idempotency, 'register_request', lambda *a: None)
    store = FakeStore()
    saved = live.save_reference(output, store)
    row = {'operation': 'prediction_record', 'race_id': output['race_id'],
           'payload_json': canonical_json(store.payload), 'received_at_utc': NOW.isoformat()}
    reader = SimpleNamespace(_small=lambda *a: [row])
    assert live.verify_saved_receipt(reader, {'sql_save': saved}, output)['readback_verified']
    row['payload_json'] = '{}'
    with pytest.raises(ResearchError, match='receipt_changed'):
        live.verify_saved_receipt(reader, {'sql_save': saved}, output)
