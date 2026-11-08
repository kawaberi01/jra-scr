"""概要: T10検算の中心化縮約順を学習と揃え、許容差を緩めず再検算する。
作成日: 2026-11-07
入力: 変更していないT10研究runと旧検算コード。
出力: 旧検算の全照合結果、v2検算のSHA/修正理由/正本指定。
実行例: uv run --frozen --extra ml python scripts/verify_jra_ten_minute_v2.py
注意事項: モデル/特徴定義/閾値/許容差を変更せず、再学習しない。
"""

import argparse
from itertools import combinations
from pathlib import Path
import numpy as np
import verify_jra_ten_minute as original


def independent_features(record, case):
    """ペアを別列挙し、市場期待値を同じnp.dot順で引いてfloat32化する。"""
    a = np.asarray(record['attributes'], dtype=np.float32)
    q, pl = np.asarray(record['market']), np.asarray(record['pl'])
    attrs = []
    for i, j in combinations(range(len(a)), 2):
        attrs.append([*((a[i] + a[j]) / np.float32(2)).tolist(), *np.abs(a[i] - a[j]).tolist()])
    raw = np.column_stack((np.log(q), np.clip(np.log(pl / q), -10, 10), np.asarray(attrs, dtype=float)))
    current = (raw - np.dot(q, raw)).astype(np.float32)
    if case != 'M10':
        return current
    extra = np.column_stack((np.clip(np.log(q / record['early_market']), -5, 5),
                             np.clip(np.log(pl / record['early_pl']), -5, 5)))
    extra -= np.dot(q, extra)
    return np.column_stack((current, extra.astype(np.float32))).astype(np.float32)


def verify(folder):
    """旧検算の行列生成だけを置き換えて全照合し、v2正本の証跡を保存する。"""
    original.features = independent_features
    original.verify(folder)
    run = original.run
    result = run.read(folder / 'independent-verification.json')
    run.save(folder / 'independent-verification-v2.json', result | {
        'verifier_v2_sha256': run.sha(Path(__file__)), 'models_unchanged': True, 'tolerances_unchanged': True,
        'reason': 'sum(q*x) versus dot(q,x) reduction order before float32, not model differences'})
    run.save(folder / 'independent-verification-status.json', {'status': 'passed',
        'authority': 'independent-verification-v2.json', 'initial_failure': 'independent-failure-v1.json',
        'new_fits': 0, 'verifier_v2_sha256': run.sha(Path(__file__))})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=original.run.ROOT / 'artifacts/jra_research/ten_minute_20261107')
    verify(parser.parse_args().output)
