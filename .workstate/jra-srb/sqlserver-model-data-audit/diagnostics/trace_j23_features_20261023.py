"""概要: 固定24競走のJ23内部補正をSQL履歴から再構築し、元予測一致後に寄与を診断する。
作成日: 2026-10-23
入力: 事前固定protocol、元runの月別モデル/保存行、既存読取専用SQL設定。
出力: j23_feature_trace_20261023の進捗・24事例診断・検証/失敗記録。
実行例: uv run --frozen --extra ml python -u -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/trace_j23_features_20261023.py
注意事項: 900秒/2GiB/年50万行/計200万行以内。学習・原本保存・SQL更新・API取得なし。
"""

from collections import defaultdict
import gc
import hashlib
from itertools import combinations
import json
from pathlib import Path
import time

import joblib
import numpy as np
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from jra_srb import jra_research_chimera_thirty_features as f
from jra_srb import jra_research_chimera_thirty_model as learner
from jra_srb.jra_research_contracts import ResearchError, digest, timestamp
from jra_srb.jra_research_history import HistoryConfig
from jra_srb.jra_research_r1_calibration import select_pair
from jra_srb.jra_research_r1_live import LiveAnnualReader, require
from jra_srb.jra_research_resources import check_memory


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT/'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'
OUT = ROOT/'artifacts/jra_research/j23_feature_trace_20261023'
START = time.monotonic()
LIMIT = 2**31


def write(name, value, *, progress=False):
    """原文を含まない診断JSONを新規保存し、進捗ファイルだけを更新する。

    Args:
        name: OUT直下の診断ファイル名。
        value: 有限JSONへ変換できる診断値。
        progress: Trueの場合だけ一時ファイルから既存進捗を置換する。
    Raises:
        FileExistsError: 新規成果物が既に存在する。
    """
    path = OUT/name
    if progress:
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        temporary.replace(path)
    else:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def guard():
    """時間・実メモリの固定上限を超えたら処理を停止する。"""
    require(time.monotonic()-START <= 900, 'trace_wall_time_limit')
    return check_memory(LIMIT)


def sha(path):
    """元ファイル実内容のSHA256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sources(targets):
    """対象月の保存行と固定モデルをSHA検査し、以後の原本不変照合に備える。

    Returns:
        月/方式別のモデルと保存行、再検査用のファイルSHA。
    Raises:
        ResearchError: 元セルまたはモデルSHAが不一致。
    Notes:
        joblibを読む前に元セルのモデルSHAと照合する。ファイルは変更しない。
    """
    models, rows, hashes = {}, {}, {}
    for month in sorted({t['race_key'][:4]+'-'+t['race_key'][4:6] for t in targets}):
        for case in ('J23', 'J01', 'R1', 'M0'):
            path = SOURCE/'cells'/f'{month}_{case}.json'
            cell = json.loads(path.read_text(encoding='utf-8-sig'))
            require(digest({k: v for k, v in cell.items() if k != 'cell_sha256'}) == cell['cell_sha256'], 'trace_source_cell_changed')
            rows[(month, case)] = {r['race_key']: r for r in cell['rows']}
            hashes[str(path.relative_to(ROOT))] = sha(path)
            if case != 'M0':
                model_path = path.parent/cell['model_file']
                require(model_path.parent == path.parent and sha(model_path) == cell['model_sha256'], 'trace_model_changed')
                hashes[str(model_path.relative_to(ROOT))] = sha(model_path)
                models[(month, case)] = joblib.load(model_path)
    return models, rows, hashes


def market_preflight(reader):
    """元市場版・必要列・snapshot/race索引の存在を有界metadata照会で検査する。

    Raises:
        ResearchError: 固定31版、SELECT専用権限、必要列、索引のいずれかが不成立。
    """
    source = reader._small('trace:market_source',
                           'SELECT d.source_key,s.status FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?', (31,))
    require(source == [{'source_key': 'prediction-full-20261008', 'status': 'verified'}], 'trace_market_source_changed')
    for table in ('market.odds_asof_index', 'history.payouts'):
        for permission in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'ALTER', 'CONTROL'):
            value = reader._small('trace:market_permission', 'SELECT HAS_PERMS_BY_NAME(?,?,?) permitted', (table, 'OBJECT', permission))
            require(value[0]['permitted'] == int(permission == 'SELECT'), 'trace_market_permission')
        cols = reader._small('trace:market_columns', 'SELECT name FROM sys.columns WHERE object_id=OBJECT_ID(?)', (table,))
        require(set(f.old.base.FIELDS[table]) <= {r['name'] for r in cols}, 'trace_market_schema')
        idx = reader._small('trace:market_indexes', 'SELECT i.name,c.name col FROM sys.indexes i JOIN sys.index_columns ic ON i.object_id=ic.object_id AND i.index_id=ic.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND ic.key_ordinal>0 AND i.is_disabled=0 AND i.is_hypothetical=0 AND i.has_filter=0 ORDER BY i.index_id,ic.key_ordinal', (table,))
        groups = defaultdict(list)
        for row in idx:
            groups[row['name']].append(row['col'])
        require(any(v[:2] == ['__migration_source_snapshot_id', '__unified_race_sha256'] for v in groups.values()), 'trace_market_index')


def read_market(reader, race):
    """1対象だけのT30単勝/馬連/HRを既存索引と元検査関数で照合する。

    Returns:
        馬番順ペア、倍率価格、市場確率、PL確率、本文SHA/判断時刻の証跡。
    Raises:
        ResearchError: SQL失敗、時点/馬集合/発売/払戻の不整合。
    Notes:
        入力はメモリ内だけに保持し、SQLを更新しない。
    """
    key = race['key']
    rows = f.inputs.indexed_rows(reader, [key], 'market.odds_asof_index', f.old.base.FIELDS['market.odds_asof_index'],
                                "AND t.market IN(N'quinella',N'win') AND t.horizon=N'T30'")
    payouts = f.inputs.indexed_rows(reader, [key], 'history.payouts', f.old.base.FIELDS['history.payouts'],
                                   "AND t.market=N'quinella' AND t.slot_status=N'published'")
    pair_rows = [r for r in rows if r['market'] == 'quinella']
    win_rows = [r for r in rows if r['market'] == 'win']
    prices = f.inputs.validate_inputs(race, pair_rows, payouts)
    require(len(win_rows) == 1, 'trace_missing_win')
    w, q = win_rows[0], pair_rows[0]
    require(w['selection_status'] == 'selected' and w['parser_version'] == 'jv-o1o2-v2'
            and bool(w['content_sha256']) and timestamp(w['announced_at']) <= timestamp(w['cutoff_at'])
            and timestamp(w['cutoff_at']) == timestamp(q['cutoff_at']), 'trace_win_cutoff_or_identity')
    win = f.inputs.numeric_market(w, 'win')
    numbers = [r['horse_no'] for r in race['runners']]
    require(set(win) == set(numbers), 'trace_win_roster')
    keys = list(combinations(numbers, 2))
    quoted = np.asarray([prices[k] for k in keys])
    market = 1/quoted;market /= market.sum()
    pl = f.pl_pairs(np.asarray([1/win[n] for n in numbers]))
    return keys, quoted, market, pl, {'market_sha256': q['content_sha256'], 'win_sha256': w['content_sha256'],
                                     'hr_sha256': payouts[0]['hr_sha256'], 'cutoff': q['cutoff_at']}


def inspect(reader, states, race, target, models, originals):
    """元4方式を再現した対象だけについて、固定J23の補正寄与と実際の履歴品質を診断する。

    Args:
        reader: 元市場版を検査済みのSELECT専用reader。
        states: 対象日の結果が未反映の時計/馬履歴状態。
        race: 解析済み対象競走。正解は推論後の再現検査だけで使う。
        target: 事前固定した層化事例の属性。
        models: 対象月より前に学習済みのSHA確認済みモデル。
        originals: 同じ競走の元保存行。
    Returns:
        元予測一致の証跡と、正解/元選択ペアだけの補正・履歴要約。
    Raises:
        ResearchError: 元4方式の再現、選択、独立分解、経験量の定義が不一致。
    Notes:
        固定係数で項を0にする診断は再学習した除外比較ではない。
    """
    guard()
    key, month = race['key'], race['day'][:7]
    public = states.public(race)
    quality = f.old.States.public(states, race)
    x = np.column_stack((public['x'], public['extra'][:, 20:23])).astype(np.float32)
    keys, prices, market, pl, market_evidence = read_market(reader, race)
    record = {'x': x, 'basic': states.legacy_features(race)[:, f.old.residual.BASIC].astype(np.float32),
              'addition': np.empty((len(x), 0)), 'styles': np.zeros(len(x)), 'density': 0., 'group': 0,
              'market': market, 'pl': pl}
    winners = tuple(r['horse_no'] for r in race['runners'] if r['rank'] <= 2)
    winner = keys.index(winners)
    replay = {}
    predicted = {}
    for case in ('J23', 'J01', 'R1', 'M0'):
        p = market.copy() if case == 'M0' else learner.predict(models[(month, case)], learner.clean_record(record))
        old = originals[(month, case)][key]
        loss = float(-np.log(p[winner]))
        brier = float((p@p-2*p[winner]+1)/len(p))
        require(winner == old['winner'] and len(p) == old['pair_count']
                and abs(p[winner]-old['winning_probability']) < 1e-12
                and abs(loss-old['loss']) < 1e-12 and abs(brier-old['brier']) < 1e-14,
                'trace_prediction_replay_mismatch')
        replay[case] = {'winning_probability_difference': float(p[winner]-old['winning_probability']),
                        'loss_difference': loss-old['loss'], 'brier_difference': brier-old['brier']}
        predicted[case] = p
    p = predicted['J23']
    chosen = select_pair(p, prices, np.ones(len(p)))
    old = originals[(month, 'J23')][key]
    require(chosen == old['chosen'] and (chosen is None or abs(p[chosen]-old['ticket_probability']) < 1e-12
            and float(prices[chosen]) == old['ticket_odds']), 'trace_chosen_replay_mismatch')
    model = models[(month, 'J23')]
    matrix = learner.matrix(record, 'J23')/model['scale'].astype(np.float32)
    contributions = matrix*model['coef']
    logits = np.log(market)+contributions.sum(axis=1)
    require(np.allclose(p, softmax(logits), rtol=1e-12, atol=1e-14), 'trace_logit_decomposition_mismatch')
    parts = {'base_25': contributions[:, :25].sum(axis=1),
             'pl_gap': contributions[:, 25], 'gap_clock': contributions[:, 26], 'gap_experience': contributions[:, 27]}
    full_loss = float(-np.log(p[winner]))
    effect = {}
    for name, part in parts.items():
        without = softmax(logits-part)
        effect[name] = {'winner_centered_logit': float(part[winner]),
                        'chosen_centered_logit': float(part[chosen]) if chosen is not None else None,
                        'loss_added_by_term': full_loss-float(-np.log(without[winner]))}
    extra = parts['pl_gap']+parts['gap_clock']+parts['gap_experience']
    effect['three_extra_terms'] = {'loss_added_by_term': full_loss-float(-np.log(softmax(logits-extra)[winner]))}
    horses = []
    for i, runner in enumerate(race['runners']):
        h = states.horses.get(runner['horse_id'])
        past = list(h.last) if h else []
        count = h.n if h else 0
        require(abs(float(x[i, 9])-float(np.float32(np.clip(np.log1p(count)/5, -5, 5)))) < 1e-7, 'trace_experience_semantics')
        horses.append({'horse_no': runner['horse_no'], 'normal_starts': count, 'experience_proxy': float(x[i, 9]),
                       'clock_mean': float(x[i, 0]), 'days_since_last': race['ordinal']-past[-1][0] if past else None,
                       'recent_clock_sd': float(np.std([v[1] for v in past])) if len(past) >= 2 else None,
                       'actual_clock_reliability': float(quality['rel'][i, 0])})

    def pair_details(index):
        """実馬番号と、補正に使うペア特徴/予測確率の診断要約を返す。"""
        if index is None:
            return None
        a, b = keys[index]
        left, right = [next(i for i, r in enumerate(race['runners']) if r['horse_no'] == n) for n in (a, b)]
        return {'horses': [a, b], 'p_J23': float(p[index]), 'p_market': float(market[index]), 'p_PL': float(pl[index]),
                'p_J23_to_market': float(p[index]/market[index]), 'PL_to_market': float(pl[index]/market[index]),
                'gap': float(np.clip(np.log(pl[index]/market[index]), -10, 10)),
                'clock_mean': float((x[left, 0]+x[right, 0])/2),
                'experience_proxy': float((x[left, 9]+x[right, 9])/2),
                'actual_reliability': float((horses[left]['actual_clock_reliability']+horses[right]['actual_clock_reliability'])/2),
                'horse_history': [horses[left], horses[right]]}

    return {'race_key': key, 'race_date': race['day'], 'stratum': target['stratum'], 'replay': replay,
            'market_evidence': market_evidence, 'J23_loss': full_loss,
            'M0_loss': originals[(month, 'M0')][key]['loss'], 'R1_loss': originals[(month, 'R1')][key]['loss'],
            'J01_loss': originals[(month, 'J01')][key]['loss'],
            'winner_pair': pair_details(winner), 'chosen_pair': pair_details(chosen), 'parts': effect,
            'extra_effective_coefs': (model['coef'][-3:]/model['scale'][-3:]).tolist(),
            'winner_probability_sum': float(p.sum()), 'new_model_fit': False}


def main():
    """既存履歴を一巡して24競走の入力を再現し、失敗時は後続寄与診断を停止する。"""
    protocol = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    targets = {t['race_key']: t for t in protocol['targets']}
    states, years, results = f.previous.TwentyStates(), {}, []
    maximum_day = max(targets)[:8]
    scanned = 0
    reader = None
    stage = 'load_sources'
    try:
        models, originals, hashes = load_sources(protocol['targets'])
        historical = json.loads((f.old.AUDIT/'audit.json').read_text(encoding='utf-8-sig'))
        config = HistoryConfig.load(ROOT/'configs/research/history_sql_v1.json')
        stage = 'preflight'
        with threadpool_limits(limits=1), LiveAnnualReader(config) as reader:
            preflight = reader.preflight()
            market_preflight(reader)
            write('preflight.json', preflight)
            for year in range(2003, 2027):
                guard()
                stage = f'history_{year}'
                raw, audit = reader.year_before(year, '2026-10-18')
                require(audit['input_digest'] == historical['annual'][str(year)]['source_audit']['input_digest'], 'trace_annual_input_changed')
                scanned += audit.get('scanned_RA', 0)+audit.get('scanned_SE', 0)
                require(scanned <= 2000000, 'trace_total_row_limit')
                daily = defaultdict(list)
                for key, source in sorted(raw.items()):
                    if key[:8] > maximum_day:
                        continue
                    race, reason = f.old.native.parse_race(key, source)
                    if reason:
                        continue
                    ra = source['RA'][2]
                    seconds = {r['horse_no']: f.old.clock_seconds(source['SE'][r['horse_no']][2][338:342]) for r in race['runners']}
                    going = f.old.native.number(ra[888:889] if race['surface'] == 0 else ra[889:890])
                    require(going in (1, 2, 3, 4), 'trace_going')
                    laps = [f.old.native.number(ra[890+i*3:893+i*3])/10 for i in range(25)]
                    race['closing_total'] = sum([v for v in laps if v > 0][-3:]) if race['pace'] is not None else None
                    daily[race['day']].append((race, seconds, going))
                del raw
                for day, updates in sorted(daily.items()):
                    guard()
                    for race, _, _ in updates:
                        if race['key'] in targets:
                            stage = 'replay_'+race['key']
                            results.append(inspect(reader, states, race, targets[race['key']], models, originals))
                            write('partial-results.json', {'matched': len(results), 'rows': results}, progress=True)
                    states.update_day(updates)
                years[str(year)] = audit
                used = guard()
                write('state.json', {'status': 'running', 'year': year, 'matched': len(results), 'scanned_rows': scanned,
                                     'memory_bytes': used, 'elapsed_seconds': time.monotonic()-START}, progress=True)
                print(json.dumps({'year': year, 'matched': len(results), 'scanned_rows': scanned, 'elapsed': round(time.monotonic()-START, 1)}), flush=True)
                del daily
                gc.collect()
            query_metrics = reader.query_metrics
        require({r['race_key'] for r in results} == set(targets), 'trace_target_not_reconstructed')
        require(all(sha(ROOT/p) == h for p, h in hashes.items()), 'trace_original_changed')
        verification = {'status': 'passed', 'targets': len(results), 'source_unchanged': True,
                        'all_four_models_replayed': True, 'source_sha256': hashes, 'annual': years,
                        'scanned_rows': scanned, 'sql_query_count': len(query_metrics), 'query_metrics': query_metrics,
                        'elapsed_seconds': time.monotonic()-START, 'model_fits': 0, 'sql_writes': 0}
        write('results.json', {'protocol': protocol, 'verification': verification, 'rows': results})
        write('state.json', {'status': 'passed', 'matched': len(results), 'elapsed_seconds': time.monotonic()-START}, progress=True)
        print('all24 original predictions matched; feature decomposition saved', flush=True)
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError('trace_failed', 4, error_type=type(error).__name__)
        write('failure.json', {'stage': stage, 'reason': safe.reason, 'details': safe.details,
                               'matched': len(results), 'elapsed_seconds': time.monotonic()-START,
                               'query_metrics': reader.query_metrics if reader else []})
        write('state.json', {'status': 'failed', 'stage': stage, 'matched': len(results), 'reason': safe.reason}, progress=True)
        print(json.dumps({'status': 'failed', 'stage': stage, 'reason': safe.reason, 'details': safe.details}), flush=True)
        raise SystemExit(safe.exit_code) from None


if __name__ == '__main__':
    main()
