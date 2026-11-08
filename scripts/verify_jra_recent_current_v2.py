"""概要: float32への丸め前の中心化演算をそろえてS1を独立検算する。
作成日: 2026-10-27
入力: 完了済みS1 run、元検算器と保存された不一致診断。
出力: independent-verification.jsonと検算方式のSHA記録。
実行例: uv run --frozen --extra ml python scripts/verify_jra_recent_current_v2.py
注意事項: 許容差・特徴・係数は変えず、sumと内積の縮約順の違いだけを是正する。
"""

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np

import verify_jra_recent_current as previous


def independent_matrix(record):
    """属性・前走ペアを別に列挙し、保存モデルと同じ内積/float32境界を守る。"""
    q = np.asarray(record['market'], dtype=float)
    pl = np.asarray(record['pl'], dtype=float)
    attrs = np.asarray(record['attributes'], dtype=np.float32)
    recent = np.asarray(record['recent'], dtype=np.float32)
    base_rows, recent_rows = [], []
    for index, (a, b) in enumerate(combinations(range(len(attrs)), 2)):
        base_rows.append([np.log(q[index]), np.clip(np.log(pl[index]/q[index]), -10, 10),
                          *((attrs[a]+attrs[b])/np.float32(2)).tolist(), *np.abs(attrs[a]-attrs[b]).tolist()])
        recent_rows.append([*((recent[a]+recent[b])/np.float32(2)).tolist(), *np.abs(recent[a]-recent[b]).tolist()])
    base = np.asarray(base_rows, dtype=float)
    base -= np.dot(q, base)
    # 一次実装と同じfloat32結合後にfloat64中心化する。特徴式自体は独立列挙。
    x = np.column_stack((base.astype(np.float32), np.asarray(recent_rows, dtype=np.float32))).astype(float)
    x -= np.dot(q, x)
    return x.astype(np.float32)


def verify(folder):
    """元検算の特徴・確率・精算を維持し、丸め順だけ修正して実行する。"""
    before = previous.reuse.sha(folder/'manifest.json')
    prior_sha = previous.reuse.sha(Path(previous.__file__))
    previous.independent_matrix = independent_matrix
    previous.__file__ = __file__
    previous.verify(folder)
    previous.reuse.save(folder/'verification-method.json', {
        'status': 'passed', 'method': 'independent pair enumeration with dot/float32 cast boundaries',
        'v1_verifier_sha256': prior_sha, 'v2_verifier_sha256': previous.reuse.sha(Path(__file__)),
        'original_manifest_sha256': before, 'manifest_unchanged': previous.reuse.sha(folder/'manifest.json') == before,
        'probability_atol': 1e-12, 'probability_rtol': 1e-11, 'tolerance_relaxed': False,
        'features_or_models_changed': False, 'refits': 0,
        'resolved_diagnostic_sha256': previous.reuse.sha(folder/'verification-mismatch-diagnostic.json')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=previous.ROOT/'artifacts/jra_research/recent_current_S1_20261027')
    verify(parser.parse_args().run)
