"""概要: 固定V110/J23を保存入力から独立した研究参照として推論する。
作成日: 2026-10-23
入力: 来歴付きjra-original-candidate-input-v1 JSON、固定SHAの既存モデル。
出力: 原型の全馬連確率と最大1点、実購入0の新規参照成果物。
実行例: uv run --frozen --extra ml python scripts/score_jra_original_candidate.py --candidate J23 --input input.json --output artifacts/reference/new-run
注意事項: SQL/HTTP/学習なし。参照出力は独立性能評価に数えない。既存ファイルは上書きしない。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib
from itertools import combinations
import json
from pathlib import Path
import re
import sys

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from .jra_history_dataset import COURSE_CODES, FEATURE_NAMES
from .jra_research_artifacts import ROOT
from .jra_research_contracts import ResearchError, finite, horse_number, timestamp

SCHEMA = 'jra-original-candidate-input-v1'
REGISTRY = ROOT / 'artifacts/jra_research/original_candidates_compatibility_20261023/reference-config.json'
REGISTRY_SHA = 'e513eaf01ec563118efa3c294dbd24fe720b214f7a64fe2ed75586f682e4daa8'
JST = timezone(timedelta(hours=9))
COURSES = {name: code for code, name in COURSE_CODES.items()}


def require(condition, reason):
    """不正な入力や固定契約違反を秘密を含まない理由で拒否する。"""
    if not condition:
        raise ResearchError(reason, 2)


def file_sha(path):
    """指定したローカルファイルのSHA256を返す。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def registry():
    """初版の参照構成と元ソースを固定SHAで確認する。"""
    require(file_sha(REGISTRY) == REGISTRY_SHA, 'candidate_registry_changed')
    value = json.loads(REGISTRY.read_text(encoding='utf-8'))
    for name, expected in value['source_sha256'].items():
        require(file_sha(ROOT / name) == expected, 'candidate_source_changed')
    return value


def legacy(name):
    """既存研究と同じscripts moduleを読み、計算式を再利用する。"""
    folder = str(ROOT / 'scripts')
    if folder not in sys.path:
        sys.path.insert(0, folder)
    return importlib.import_module(name)


def load_model(candidate, contract):
    """任意joblibを受け取らず、固定モデルだけをSHA確認後にロードする。"""
    path = ROOT / contract['model']
    require(file_sha(path) == contract['model_sha256'], 'candidate_model_changed')
    model = joblib.load(path)
    if candidate == 'J23':
        require(model['case'] == 'J23' and model['trained_through'] == contract['training_max_date'],
                'candidate_model_identity')
        vectors = (np.asarray(model['coef']), np.asarray(model['scale']))
        require(all(v.shape == (28,) and np.isfinite(v).all() for v in vectors)
                and (vectors[1] > 0).all(), 'candidate_model_shape')
    else:
        require(model['training_max_date'] == contract['training_max_date']
                and model['enriched_feature_names'] == contract['features']
                and model['fixed_policy'] == {'group': 'all', 'threshold': 1.05}, 'candidate_model_identity')
        top = model['top3']
        require(top['feature'] == 'enriched' and all(np.asarray(top[k]).shape == (42,)
                and np.isfinite(top[k]).all() for k in ('coef', 'scale'))
                and (np.asarray(top['scale']) > 0).all(), 'candidate_model_shape')
    return model


def named_history(names, values):
    """43履歴値を列名で写し、欠測・重複・未知列を拒否する。"""
    require(isinstance(names, list) and isinstance(values, list)
            and len(names) == len(values) == len(FEATURE_NAMES)
            and len(set(names)) == len(names) and set(names) == set(FEATURE_NAMES),
            'candidate_history_columns')
    return {name: finite(value) for name, value in zip(names, values, strict=True)}


def validate_common(value, candidate, contract):
    """競走同定・時間順・履歴来歴を検査し、範囲外かどうか返す。"""
    require(candidate in ('J23', 'V110') and value['candidate'] == candidate and value['schema'] == SCHEMA,
            'candidate_input_schema')
    day, key = value['race_date'], value['race_id']
    require(date.fromisoformat(day).isoformat() == day and isinstance(key, str)
            and re.fullmatch(r'[0-9]{12}', key) is not None, 'candidate_identity')
    require(key[:8] == day.replace('-', '') and value['course'] in COURSES
            and key[8:10] == COURSES[value['course']] and type(value['race_no']) is int
            and 1 <= value['race_no'] <= 12 and int(key[10:]) == value['race_no'], 'candidate_identity')
    require(day > contract['training_max_date'], 'candidate_not_after_training')
    source = value['source']
    require(isinstance(source['generator'], str) and bool(source['generator'])
            and source['history_before'] == day and isinstance(source['history_policy'], str)
            and bool(source['history_policy']) and type(source['publication_verified']) is bool
            and type(source['card_verified']) is bool, 'candidate_source_contract')
    hashes = source['input_sha256']
    require(isinstance(hashes, dict) and bool(hashes) and all(isinstance(s, str)
            and re.fullmatch(r'[0-9a-f]{64}', s) for s in hashes.values()), 'candidate_source_digest')
    if 'history_latest_date' in source:
        require(date.fromisoformat(source['history_latest_date']).isoformat() < day, 'candidate_future_history')
    month = int(day[5:7])
    return (value['course'] in ('tokyo', 'nakayama') and month in (9, 10, 11)) if candidate == 'J23' else (
        value['course'] == 'tokyo' and month not in (6, 7, 8))


def market_time(start, announced, day):
    """時刻帯付き発走日時とT30以前の発表時刻を検査する。"""
    post = timestamp(start)
    require(post.astimezone(JST).date().isoformat() == day, 'candidate_post_date')
    require(timestamp(announced) <= post - timedelta(minutes=30), 'candidate_late_market')


def complete_markets(horses, win, pairs):
    """馬集合と全ペア価格を検査し、正規順の価格配列を返す。"""
    require(len(horses) >= 2 and len(set(horses)) == len(horses)
            and horses == sorted(horses, key=int), 'candidate_horse_order')
    expected = list(combinations(horses, 2))
    require(len(win) == len(horses) and set(win) == set(horses)
            and len(pairs) == len(expected) and set(pairs) == set(expected), 'candidate_incomplete_market')
    w = np.asarray([finite(win[k]) for k in horses])
    p = np.asarray([finite(pairs[k]) for k in expected])
    require((w >= 1).all() and (p >= 1).all(), 'candidate_invalid_price')
    return expected, w, p


def prepare_v110(value):
    """許可した前日履歴とT30市場だけを既存prepareへ渡す。"""
    payload = value['payload']
    r = payload['race']
    require(r['course'] == value['course'] and r['surface'] in ('turf', 'dirt')
            and finite(r['distance']) > 0, 'candidate_race_attributes')
    inp = payload['inputs']
    require(inp['history_as_of'] == value['race_date'] + 'T00:00:00+09:00', 'candidate_history_cutoff')
    runners = []
    for raw in inp['runners']:
        h = raw['history_features']
        require(set(h) == set(FEATURE_NAMES), 'candidate_history_columns')
        runners.append({'horse_no': horse_number(raw['horse_no']),
                        'history_features': {name: finite(h[name]) for name in FEATURE_NAMES}})
    horses = [row['horse_no'] for row in runners]
    require(len(set(horses)) == len(horses), 'candidate_duplicate_horse')
    horses.sort(key=int)
    runners.sort(key=lambda row: int(row['horse_no']))
    snapshot = inp['odds']['T-30m']
    win, pairs = {}, {}
    for raw in snapshot['win']['horses']:
        key = horse_number(raw['horse_no'])
        require(raw['status'] == 'numeric' and key not in win, 'candidate_invalid_win')
        win[key] = finite(raw['odds'])
    for raw in snapshot['quinella']['pairs']:
        key = tuple(sorted((horse_number(raw['horse_no_1']), horse_number(raw['horse_no_2'])), key=int))
        require(raw['status'] == 'numeric' and key[0] != key[1] and key not in pairs, 'candidate_duplicate_pair')
        pairs[key] = finite(raw['odds'])
    expected, _, _ = complete_markets(horses, win, pairs)
    for name in ('win', 'quinella'):
        market_time(r['start_at'], snapshot[name]['announced_at'], value['race_date'])
    clean = {'race_id': value['race_id'], 'race_date': value['race_date'],
             'race': {k: r[k] for k in ('course', 'surface', 'distance', 'start_at')},
             'inputs': {'runners': runners, 'history_as_of': inp['history_as_of'], 'odds': {'T-30m': {
                 'win': {'announced_at': snapshot['win']['announced_at'], 'horses': [
                     {'horse_no': k, 'odds': win[k], 'status': 'numeric'} for k in horses]},
                 'quinella': {'announced_at': snapshot['quinella']['announced_at'], 'pairs': [
                     {'horse_no_1': k[0], 'horse_no_2': k[1], 'odds': pairs[k], 'status': 'numeric'} for k in expected]}}}}}
    return legacy('jra_second_ten_model').prepare(clean)


def score_j23(model, value):
    """補正係数と月別結果を読まず、J23原型の元式だけで推論する。"""
    from . import jra_research_chimera_thirty_features as features
    from . import jra_research_chimera_thirty_model as learner
    from .jra_research_r1_calibration import select_pair

    raw = value['payload']
    horses = [horse_number(k) for k in raw['horses']]
    require(len(horses) >= 8, 'candidate_j23_field_size')
    require([horse_number(k) for k in raw['x_horses']] == horses, 'candidate_feature_horse_order')
    require(raw['features_race_date'] == value['race_date'] and re.fullmatch(
        r'[0-9a-f]{64}', raw['feature_definition_sha256']) is not None, 'candidate_feature_provenance')
    win, pairs = {}, {}
    for row in raw['win']:
        key = horse_number(row['horse_no'])
        require(key not in win, 'candidate_duplicate_horse')
        win[key] = row['odds']
    for row in raw['quinella']:
        key = tuple(horse_number(k) for k in row['horses'])
        require(len(key) == 2 and key not in pairs, 'candidate_duplicate_pair')
        pairs[key] = row['odds']
    keys, w, prices = complete_markets(horses, win, pairs)
    market_time(raw['start_at'], raw['win_announced_at'], value['race_date'])
    market_time(raw['start_at'], raw['quinella_announced_at'], value['race_date'])
    x = np.asarray([[finite(v) for v in row] for row in raw['x']], dtype=np.float32)
    require(x.shape == (len(horses), 12), 'candidate_j23_feature_shape')
    market = 1 / prices
    market /= market.sum()
    record = {'x': x, 'addition': np.empty((len(x), 0)), 'basic': np.empty((len(x), 0)),
              'styles': np.zeros(len(x)), 'density': 0., 'group': 0,
              'market': market, 'pl': features.pl_pairs(1 / w)}
    probability = learner.predict(model, learner.clean_record(record))
    chosen = select_pair(probability, prices, np.ones(len(prices)))
    return keys, prices, probability, chosen


def predict(value, candidate):
    """固定候補を推論し、原型確率と実購入0の参照結果を返す。

    Args:
        value: 来歴と候補別の保存入力。対象結果は推論へ渡さない。
        candidate: J23またはV110。省略・自動選択なし。
    Returns:
        範囲外skipまたは全ペア確率を含むruntime_validation_only参照。
    Raises:
        ResearchError: 入力/時刻/モデル/SHA契約に不正がある場合。
    """
    try:
        require(candidate in ('J23', 'V110'), 'candidate_required')
        all_contracts = registry()
        contract = all_contracts[candidate]
        in_scope = validate_common(value, candidate, contract)
        output = {'candidate': candidate, 'race_id': value['race_id'], 'race_date': value['race_date'],
                  'course': value['course'], 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                  'status': 'runtime_validation_only' if in_scope else 'skipped',
                  'reason': 'unproven_publication_and_receipt' if in_scope else 'outside_frozen_scope',
                  'model_sha256': contract['model_sha256'], 'training_max_date': contract['training_max_date'],
                  'registry_sha256': REGISTRY_SHA, 'performance_eligible': False, 'adopted': False,
                  'candidate_stake_yen': 0, 'stake_yen': 0, 'actual_tickets': [], 'new_fits': 0,
                  'pairs': [], 'chosen': None}
        if not in_scope:
            return output
        model = load_model(candidate, contract)
        with threadpool_limits(limits=1):
            if candidate == 'J23':
                keys, prices, probability, chosen = score_j23(model, value)
            else:
                record = prepare_v110(value)
                score = legacy('jra_second_ten_model').score_suite(model, record)['V110']
                ticket = legacy('jra_ten_trials_model').pick_ticket(record['pair'], score, 'quinella', model['fixed_policy'])
                keys = [tuple(k.split('-')) for k in record['pair']['keys']]
                prices, probability = record['pair']['price'], score['probability']
                chosen = ticket['index'] if ticket else None
        require(len(probability) == len(keys) and np.isfinite(probability).all()
                and (probability > 0).all() and abs(float(probability.sum()) - 1) < 1e-9,
                'candidate_probability_contract')
        market = 1 / np.asarray(prices)
        market /= market.sum()
        output['pairs'] = [{'horses': list(k), 'probability': float(p), 'market_probability': float(q),
                            'quoted_odds': float(price)}
                           for k, p, q, price in zip(keys, probability, market, prices, strict=True)]
        if chosen is not None:
            output['chosen'] = output['pairs'][chosen]
            output['candidate_stake_yen'] = 600
        return output
    except ResearchError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, OSError, IndexError):
        raise ResearchError('candidate_invalid_input_or_artifact', 2) from None


def write_json(path, value):
    """新規JSONをUTF-8で排他的に書き、非有限数値も拒否する。"""
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def execute(input_path, output_path, candidate):
    """保存入力の参照推論を新規dirへ書き、失敗時はcompleteを残さない。

    Notes:
        manifestを最後に排他保存する。途中失敗の部分ファイルは証跡として保持する。
        元ファイル/モデル/既存dirを更新せず、SQL/HTTPへ接続しない。
    """
    output_path = Path(output_path)
    try:
        output_path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise ResearchError('candidate_output_exists', 2) from None
    except OSError:
        raise ResearchError('candidate_output_unavailable', 4) from None
    try:
        raw = Path(input_path).read_bytes()
        value = json.loads(raw.decode('utf-8-sig'))
        result = predict(value, candidate)
        input_sha = hashlib.sha256(raw).hexdigest()
        provenance = {'input_sha256': input_sha, 'source': deepcopy(value['source']),
                      'source_claims_verified_by_this_entry': False, 'registry_sha256': REGISTRY_SHA,
                      'implementation_sha256': file_sha(__file__)}
        write_json(output_path / 'input-provenance.json', provenance)
        write_json(output_path / 'reference.json', result)
        write_json(output_path / 'manifest.json', {'status': 'complete', 'performance_eligible': False,
                   'reference_sha256': file_sha(output_path / 'reference.json'),
                   'input_provenance_sha256': file_sha(output_path / 'input-provenance.json'),
                   'actual_tickets': [], 'adopted': False})
        return result
    except Exception as error:
        reason = error.reason if isinstance(error, ResearchError) else 'candidate_execution_failed'
        try:
            write_json(output_path / 'failure.json', {'status': 'failed', 'reason': reason, 'adopted': False})
        except OSError:
            pass
        if isinstance(error, ResearchError):
            raise
        raise ResearchError(reason, 4) from None
