"""概要: 30仮説研究の最大125列・7894競走18頭を合成し、メモリ制約を検証する。
作成日: 2026-10-22
入力: なし。SQL接続や実レース原文は使用しない。
出力: diagnosticsの合成負荷検証JSONと標準出力。
実行例: uv run --frozen --extra ml python scripts/check_jra_chimera_thirty_resources.py
注意事項: 合成約121万ペアを一時メモリ内に作る。性能測定件数には数えない。
"""
from pathlib import Path
import json
import os
import sys
import time

for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_variable] = '1'

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def main():
    """実データ以上の最大群別行列で、尺度/尤度/勾配と2GiB制約を検査する。"""
    import numpy as np
    from threadpoolctl import threadpool_limits
    from jra_srb import jra_research_chimera_thirty_model as model
    from jra_srb import jra_research_chimera_thirty_features as features
    from jra_srb.jra_research_resources import check_memory
    from jra_srb.jra_research_chimera_thirty import atomic_json
    started = time.monotonic()
    rng = np.random.default_rng(241)
    market = np.full(153, 1/153)
    base = {'x': rng.normal(size=(18, 12)).astype(np.float32), 'basic': np.zeros((18, 8), np.float32),
            'addition': np.zeros((18, features._column), np.float32), 'market': market,
            'pl': market, 'styles': np.full(18, .5), 'density': .3, 'group': 0,
            'winner': 0, 'race_date': '2024-01-01'}
    records = [{**base, 'group': i % 4, 'winner': i % 153} for i in range(7894)]
    with threadpool_limits(limits=1):
        data = model.pack(records, 'J25')
        scale = model.training_scale(data['x'])
        data['x'] /= scale.astype(np.float32)
        loss, grad = model.objective(np.zeros(125), data, 'J25')
        assert np.isfinite(loss) and np.isfinite(grad).all()
    result = {'status': 'passed', 'synthetic_only': True, 'races': 7894,
              'pairs': len(data['x']), 'columns': data['x'].shape[1], 'loss': loss,
              'memory_after_bytes': check_memory(features.LIMIT), 'limit_bytes': features.LIMIT,
              'elapsed_seconds': time.monotonic()-started, 'real_fits': 0, 'research_cells': 0}
    atomic_json(features.RECORD_ROOT/'diagnostics/20261022-thirty-resource-probe.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
