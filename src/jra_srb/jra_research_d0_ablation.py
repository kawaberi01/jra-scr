"""概要: D0の4部品を各1つ除去し、同じ共有学習器で再学習する。
作成日: 2026-10-25
入力: D0公開特徴、訓練時だけ正解、固定の除去部品名。
出力: 除去係数が0のD0互換モデルと馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_d0_ablation.py --help
注意事項: 旧モデル/既定変更なし。部品の代理情報まで消去するものではない。
"""

import numpy as np
from scipy.optimize import minimize
from threadpoolctl import threadpool_limits

from . import jra_research_attribute_chimera as base
from .jra_research_r1_live import require
from .jra_research_resources import check_memory

PROTOCOL = 'spec405-D0-retrained-ablation-v1'
BLOCKS = base.core.base.BLOCKS


def omitted_columns(block):
    """除去する平均/絶対差と依存する市場相互作用の列番号を返す。"""
    require(block in BLOCKS, 'd0_ablation_unknown_block')
    columns = [offset+i for offset in (2, 17) for i in BLOCKS[block]]
    if block == 'clock':
        columns.append(32)
    if block == 'rotation':
        columns.append(33)
    return sorted(columns)


def fit_packed(data, records, block):
    """1年分の元D0行列を再利用し、除去列をゼロにして1部品の除去を再学習する。

    Args:
        data: 元D0 pack。副作用として対象列を一時ゼロにするがfinallyで復元する。
        records: 当該packを作った教師。期間/件数をモデルへ保存する。
        block: 固定4部品の名前。
    Returns:
        元D0推論と互換の係数と除去列の来歴。
    Raises:
        ResearchError: 入力件数/収束/除去係数/メモリ制約の違反。
    """
    require(len(records) == data['nr'] and data['x'].shape[1] == 46, 'd0_ablation_pack_contract')
    columns = omitted_columns(block)
    original = data['x'][:, columns].copy()
    try:
        data['x'][:, columns] = 0
        with threadpool_limits(limits=1):
            result = minimize(base.core.objective, np.zeros(len(data['names'])*46), args=(data,), jac=True,
                method='L-BFGS-B', options={'maxiter': 250, 'ftol': 1e-10, 'gtol': 1e-6})
        require(result.success and np.isfinite(result.x).all(), 'd0_ablation_optimizer_failed')
        coef = result.x.reshape(-1, 46)
        require(np.count_nonzero(coef[:, columns]) == 0, 'd0_ablation_omitted_coef_nonzero')
        check_memory(base.core.base.MEMORY_LIMIT)
        return {'protocol': base.PROTOCOL, 'case': 'D0', 'ablation_protocol': PROTOCOL, 'omitted': block,
            'omitted_columns': columns, 'scale': data['scale'].copy(), 'coef': coef, 'contexts': list(data['names']),
            'context_counts': dict(data['context_counts']), 'attribute_names': list(base.ATTRIBUTES),
            'horse_features': list(base.core.base.FEATURES), 'train_races': len(records),
            'trained_from': min(r['race_date'] for r in records), 'trained_through': max(r['race_date'] for r in records),
            'optimizer': {'success': True, 'iterations': int(result.nit), 'loss': float(result.fun)}}
    finally:
        data['x'][:, columns] = original


def predict(fitted, record):
    """除去列0と来歴を確認し、元D0の結果遮断/日付境界付き推論を再利用する。"""
    require(fitted['ablation_protocol'] == PROTOCOL and fitted['omitted_columns'] == omitted_columns(fitted['omitted'])
        and np.count_nonzero(fitted['coef'][:, fitted['omitted_columns']]) == 0, 'd0_ablation_model_contract')
    return base.predict(fitted, record)
