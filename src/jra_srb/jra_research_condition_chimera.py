"""概要: 予想論の部品を共通/競走条件別/季節別に学習する研究用馬連モデル。
作成日: 2026-10-24
入力: 前日までの時計/相手水準/適性/ローテーション特徴と、訓練時だけ正解組。
出力: 保存可能な係数・条件件数・最適化情報、全馬連と馬別2着内確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_condition_chimera.py --help
注意事項: オッズはモデル入力にしない。歴史公表時点の証明や実用採用を意味しない。
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import date

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from .jra_research_chimera import pairs
from .jra_research_chimera_twenty_fit import TwentyStates
from .jra_research_r1_live import require
from .jra_research_resources import check_memory


FEATURES = (
    'recent_clock', 'best_clock', 'clock_trend', 'opponent_rating', 'relative_form',
    'distance_fit', 'course_fit', 'pace_fit', 'style_fit', 'log_history', 'rest',
    'no_history', 'distance_change', 'surface_change', 'starts_180d',
)
BLOCKS = {'clock': (0, 1, 2), 'opponent': (3, 4), 'aptitude': (5, 6, 7, 8),
          'rotation': (9, 10, 11, 12, 13, 14)}
PROTOCOL = 'spec350-condition-chimera-v1'
MEMORY_LIMIT = 2**31
MIN_CONTEXT_RACES = 100
PRE_RACE_FIELDS = ('race_id', 'race_date', 'course', 'surface', 'distance', 'horses', 'x')


def distance_band(distance):
    """実距離mを事前固定の5距離帯へ変換する。"""
    require(800 <= int(distance) <= 4000, 'condition_distance_range')
    return int(np.searchsorted([1400, 1800, 2200, 2600], int(distance), side='left'))


def season(day):
    """対象日の月から冬0/春1/夏2/秋3を返す。"""
    return (date.fromisoformat(day).month % 12)//3


def clean_record(record):
    """公開属性・馬番号・前日特徴だけを許可し、結果・価格・市場を除く。"""
    return {key: record[key] for key in PRE_RACE_FIELDS}


class ConditionStates(TwentyStates):
    """既存時計履歴に過去の距離変更と180日出走回数を追加する。"""

    def __init__(self):
        """既存状態と直前条件・過去180日の日付一覧を初期化する。"""
        super().__init__()
        self.previous_conditions = {}
        self.recent_starts = {}

    def condition_public(self, race):
        """対象結果を読まずに、固定15馬特徴を作る。

        Args:
            race: 対象日の条件、馬IDを含む出走属性。結果欄は参照しない。
        Returns:
            馬番順のfloat32行列。履歴なしは中立値と明示フラグを使う。
        """
        public = super().public(race)
        extra = []
        for runner in race['runners']:
            hid = runner['horse_id']
            previous = self.previous_conditions.get(hid)
            starts = self.recent_starts.get(hid, ())
            require(all(v < race['ordinal'] for v in starts), 'condition_same_day_history')
            count = sum(v >= race['ordinal']-180 for v in starts)
            extra.append([np.clip((race['distance']-previous[0])/400, -3, 3) if previous else 0,
                          float(race['surface'] != previous[1]) if previous else 0,
                          np.log1p(count)/3])
        x = np.column_stack((public['x'], public['extra'][:, 20:23], extra)).astype(np.float32)
        require(x.shape == (len(race['runners']), 15) and np.isfinite(x).all(), 'condition_feature_shape')
        return x

    def update_day(self, races):
        """同日全予測後に正常結果を反映し、距離履歴と180日窓も更新する。"""
        super().update_day(races)
        for race, _, _ in races:
            for runner in race['runners']:
                hid = runner['horse_id']
                self.previous_conditions[hid] = (race['distance'], race['surface'])
                starts = self.recent_starts.setdefault(hid, deque())
                while starts and starts[0] < race['ordinal']-180:
                    starts.popleft()
                starts.append(race['ordinal'])


def contexts(record, case):
    """共通係数に加える階層条件を列挙し、希少条件は後段で親へ戻す。"""
    require(case in ('C0', 'C1', 'C2'), 'condition_unknown_case')
    if case == 'C0':
        return ()
    course, surface, band = int(record['course']), int(record['surface']), distance_band(record['distance'])
    require(1 <= course <= 10 and surface in (0, 1), 'condition_invalid_context')
    out = [f'sd:{surface}:{band}', f'cs:{course}:{surface}', f'csd:{course}:{surface}:{band}']
    if case == 'C2':
        s = season(record['race_date'])
        out.extend((f'season:{s}', f'csds:{course}:{surface}:{band}:{s}'))
    return tuple(out)


def pair_matrix(record, columns):
    """馬特徴から対称なペア平均/絶対差を作り、競走内の一様平均で中心化する。"""
    x = np.asarray(record['x'], dtype=np.float32)
    require(x.ndim == 2 and x.shape == (len(record['horses']), 15)
            and 8 <= len(x) <= 18 and np.isfinite(x).all(), 'condition_invalid_horse_features')
    require(len(set(record['horses'])) == len(x), 'condition_duplicate_horse')
    x = x[:, columns]
    left, right = pairs(len(x)).T
    a, b = x[left], x[right]
    matrix = np.column_stack(((a+b)/2, np.abs(a-b)))
    return matrix-matrix.mean(axis=0)


def pack(records, case, columns):
    """訓練行列と条件別のペア行範囲を作り、訓練内尺度と件数を固定する。"""
    require(bool(records), 'condition_empty_training')
    counts = np.asarray([len(pairs(len(r['horses']))) for r in records], dtype=np.int32)
    starts = np.cumsum(np.r_[0, counts[:-1]])
    x = np.empty((int(counts.sum()), 2*len(columns)), dtype=np.float32)
    all_contexts = [contexts(r, case) for r in records]
    numbers = Counter(c for cc in all_contexts for c in cc)
    names = ['common']+sorted(c for c, n in numbers.items() if n >= MIN_CONTEXT_RACES)
    ids = {name: i for i, name in enumerate(names)}
    memberships = defaultdict(list)
    for i, (r, start, count, cc) in enumerate(zip(records, starts, counts, all_contexts, strict=True)):
        x[start:start+count] = pair_matrix(clean_record(r), columns)
        for c in cc:
            if c in ids:
                memberships[ids[c]].append(i)
    # 二次モーメントは小分け演算。全行のfloat64コピーを避ける。
    squares = np.zeros(x.shape[1])
    for begin in range(0, len(x), 50000):
        block = x[begin:begin+50000].astype(np.float64)
        squares += np.einsum('ij,ij->j', block, block)
    scale = np.maximum(np.sqrt(squares/len(x)), 1e-5)
    x /= scale.astype(np.float32)
    indices = {}
    for c, races in memberships.items():
        indices[c] = np.concatenate([np.arange(starts[i], starts[i]+counts[i], dtype=np.int32) for i in races])
    target = np.asarray([r['winner'] for r in records], dtype=np.int32)
    require(np.all((target >= 0)&(target < counts)), 'condition_invalid_target')
    check_memory(MEMORY_LIMIT)
    return {'x': x, 'counts': counts, 'starts': starts, 'groups': np.repeat(np.arange(len(records)), counts),
            'targets': starts+target, 'indices': indices, 'scale': scale, 'names': names,
            'context_counts': dict(numbers), 'nr': len(records)}


def objective(flat, data):
    """階層係数の競走等重み対数損失と解析勾配を計算する。

    Notes:
        共通項L2=0.01、条件差分L2=0.1。条件の巨大な展開行列は作らない。
    """
    x = data['x']
    coef = flat.reshape(len(data['names']), x.shape[1])
    logits = np.zeros(len(x))
    for begin in range(0, len(x), 50000):
        logits[begin:begin+50000] = x[begin:begin+50000].astype(np.float64) @ coef[0]
    for c, indices in data['indices'].items():
        for begin in range(0, len(indices), 50000):
            ix = indices[begin:begin+50000]
            logits[ix] += x[ix].astype(np.float64) @ coef[c]
    maxima = np.maximum.reduceat(logits, data['starts'])
    weights = np.exp(logits-maxima[data['groups']])
    totals = np.add.reduceat(weights, data['starts'])
    losses = maxima+np.log(totals)-logits[data['targets']]
    weights /= totals[data['groups']]
    weights[data['targets']] -= 1
    weights /= data['nr']
    penalty = np.full((len(coef), 1), .1)
    penalty[0] = .01
    gradient = penalty*coef
    for begin in range(0, len(x), 50000):
        gradient[0] += x[begin:begin+50000].astype(np.float64).T @ weights[begin:begin+50000]
    for c, indices in data['indices'].items():
        for begin in range(0, len(indices), 50000):
            ix = indices[begin:begin+50000]
            gradient[c] += x[ix].astype(np.float64).T @ weights[ix]
    return float(losses.mean()+np.sum(penalty*coef*coef)/2), gradient.ravel()


def fit(records, case, omitted=None):
    """期間を限定済みの教師だけで1構成を学習する。

    Args:
        records: 正解付きの訓練競走。評価期間は呼出側で分離する。
        case: C0/C1/C2の固定構成。
        omitted: 部品除去診断時だけ除くBLOCKSの名前。
    Returns:
        保存可能な係数、尺度、条件、訓練来歴、収束証跡。
    Raises:
        ResearchError: 入力不正、メモリ上限、最適化失敗。
    """
    require(omitted is None or omitted in BLOCKS, 'condition_unknown_ablation')
    columns = [i for i in range(15) if omitted is None or i not in BLOCKS[omitted]]
    data = pack(records, case, columns)
    with threadpool_limits(limits=1):
        result = minimize(objective, np.zeros(len(data['names'])*data['x'].shape[1]),
                          args=(data,), jac=True, method='L-BFGS-B',
                          options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6, 'maxcor': 10})
    require(bool(result.success) and np.isfinite(result.x).all(), 'condition_optimizer_failed')
    check_memory(MEMORY_LIMIT)
    return {'protocol': PROTOCOL, 'case': case, 'omitted': omitted, 'columns': columns,
            'features': list(FEATURES), 'scale': data['scale'],
            'coef': result.x.reshape(len(data['names']), -1), 'contexts': data['names'],
            'context_counts': data['context_counts'], 'min_context_races': MIN_CONTEXT_RACES,
            'train_races': len(records), 'trained_from': min(r['race_date'] for r in records),
            'trained_through': max(r['race_date'] for r in records),
            'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)},
            'market_input': False}


def predict(model, record):
    """保存係数と前日特徴だけから全馬連確率を返し、未知条件は共通/親係数へ戻す。"""
    require(model['protocol'] == PROTOCOL and model['features'] == list(FEATURES), 'condition_model_contract')
    clean = clean_record(record)
    require(model['trained_through'] < clean['race_date'], 'condition_future_training')
    x = pair_matrix(clean, model['columns'])/model['scale'].astype(np.float32)
    ids = {name: i for i, name in enumerate(model['contexts'])}
    beta = model['coef'][0].copy()
    for c in contexts(clean, model['case']):
        if c in ids:
            beta += model['coef'][ids[c]]
    p = softmax(x @ beta)
    require(np.isfinite(p).all() and np.all(p > 0) and abs(p.sum()-1) < 1e-9, 'condition_invalid_probability')
    return p


def forecast(model, record):
    """全馬連順位と2着内周辺順位を返す。馬別値は勝率と混同しない。"""
    p = predict(model, record)
    indices = pairs(len(record['horses']))
    marginal = np.zeros(len(record['horses']))
    for index, (a, b) in enumerate(indices):
        marginal[a] += p[index]
        marginal[b] += p[index]
    return {'race_id': record['race_id'], 'race_date': record['race_date'], 'case': model['case'],
            'research_only': True, 'probability_type': 'quinella_and_top2_marginal',
            'trained_through': model['trained_through'],
            'pair_ranking': [{'horses': [record['horses'][a], record['horses'][b]], 'probability': float(p[i])}
                             for i in np.argsort(-p, kind='stable') for a, b in [indices[i]]],
            'horse_ranking': [{'horse_no': record['horses'][i], 'top2_probability': float(marginal[i])}
                              for i in np.argsort(-marginal, kind='stable')],
            'active_contexts': [c for c in contexts(record, model['case']) if c in model['contexts']],
            'fallback_contexts': [c for c in contexts(record, model['case']) if c not in model['contexts']]}
