"""概要: S2共通スコア検算を再利用し、S2Bの全負例教師目的も独立検算する。
作成日: 2026-11-05
入力: 完了したS2B runと既存の検算済み入力。
出力: 独立検算と検算方式・訓練variantの記録。
実行例: uv run --frozen --extra ml python scripts/verify_jra_rank_current_all.py
注意事項: ファイル/比較キーS2は共通スキーマ。全負例への変更以外は元検算を維持する。
"""

import argparse
from pathlib import Path

import joblib
import numpy as np

import verify_jra_rank_current as previous


def training_objective(fitted, records):
    """真のスコア差から全非正解組の平均損失とL2を再計算する。"""
    assert fitted['case'] == 'S2B' and fitted['negative_top'] == 'all'
    assert fitted['training_protocol'] == 'spec436-current-all-negative-rank-S2B-v1'
    losses, comparisons = [], 0
    for r in records:
        values = previous.scores(fitted, r, enforce_date=False)
        negative = [i for i in range(len(values)) if i != r['winner']]
        comparisons += len(negative)
        losses.append(float(np.mean(np.logaddexp(0, values[negative]-values[r['winner']]))))
    beta = fitted['coef']
    return float(np.mean(losses)+(.1*np.square(beta[0]).sum()+np.square(beta[1:]).sum())/2), comparisons


def verify(folder):
    """variantを照合し、教師目的以外はS2全件検算をそのまま実行する。"""
    manifest_sha = previous.reuse.sha(folder/'manifest.json')
    original_verifier = previous.reuse.sha(Path(previous.__file__))
    protocol = previous.reuse.read(folder/'protocol.json')
    assert protocol['cases'] == ['S2B'] and protocol['negative_top'] == 'all' and protocol['family_schema'] == 'S2'
    for year in [2023, 2024, 2025, 2026]:
        fitted = joblib.load(folder/f'{year}_S2.joblib')
        assert fitted['case'] == 'S2B' and fitted['negative_top'] == 'all'
    previous.training_objective = training_objective
    previous.__file__ = __file__
    previous.verify(folder)
    previous.reuse.save(folder/'verification-method.json', {'status': 'passed', 'variant': 'S2B_all_negatives',
        'family_schema': 'S2', 'shared_verifier_sha256': original_verifier,
        'variant_verifier_sha256': previous.reuse.sha(Path(__file__)),
        'manifest_unchanged': previous.reuse.sha(folder/'manifest.json') == manifest_sha,
        'training_objective_override': 'all nonwinning pairs; independent raw score differences',
        'score_settlement_bootstrap_decision_verification_unchanged': True, 'refits': 0})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=previous.ROOT/'artifacts/jra_research/rank_current_S2B_20261105')
    verify(parser.parse_args().run)
