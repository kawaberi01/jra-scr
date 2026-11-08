"""概要: 学習分離・精度式・単勝払戻・返還・モデル互換性を検証する。
作成日: 2026-10-15
入力: 合成研究入力・結果・設定。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_research_evaluation.py
注意事項: 実DB・外部APIを利用しない。
"""

from dataclasses import replace
import math

import numpy as np
import pytest

from jra_research_helpers import config_fixture, dataset_fixture, input_fixture, race_rows
from jra_srb.jra_research_contracts import OutcomeBundle, ResearchError
from jra_srb.jra_research_evaluation import evaluate, probabilities, settle_win, summarize, train_models
from jra_srb.jra_research_sources import outcome_bundle


def test_actual_payout_is_not_the_hit_flag():
    """的中フラグ1を金額へ変換せず1230円の公式払戻を用いる。"""
    rows = race_rows()
    outcome = outcome_bundle(input_fixture(rows), rows["labels"], rows["payouts"])
    assert outcome.payouts == (1230, 0, 0, 0, 0)
    assert settle_win("official_HR_payout", 100, outcome.payouts[0])["net_yen"] == 1130
    assert settle_win("refund", 200, None) == {"stake_yen": 200, "payout_yen": 200, "net_yen": 0, "refund": True}
    with pytest.raises(ResearchError):
        settle_win("unknown", 100, None)


def test_dead_heat_keeps_individual_official_amounts():
    """同着の馬ごとの払戻を再按分しない。"""
    rows = race_rows()
    rows["labels"][1].update(rank=1, official_win_settlement=1)
    rows["payouts"].append({**rows["payouts"][0], "slot": 2, "selection_raw": "02", "payout_raw": "000000890", "payout_yen": 890})
    outcome = outcome_bundle(input_fixture(rows), rows["labels"], rows["payouts"])
    assert outcome.payouts[:2] == (1230, 890)


def test_metrics_match_hand_calculation_and_empty_tickets():
    """レースBrier/CEと購入0件nullが定義どおりになる。"""
    result = summarize([{"race_key": "x", "race_date": "2020-01-01", "probability": [.25, .75], "target": [1., 0.], "ticket": None}])
    assert result["log_loss"] == pytest.approx(-math.log(.25))
    assert result["brier"] == pytest.approx(1.125)
    assert result["tickets"] == 0 and result["roi"] is None


def test_training_uses_only_train_and_predict_does_not_read_outcome():
    """dev結果変更はモデルを変えず、score契約不一致を拒否する。"""
    config, dataset = config_fixture(), dataset_fixture()
    first = train_models(dataset, config)
    original = probabilities(first["cross"], dataset.races[1], build_identity_sha256="test-build")
    old = dataset.outcomes[dataset.races[1].race_key]
    dataset.outcomes[old.race_key] = replace(old, ranks=(5, 4, 3, 2, 1))
    second = train_models(dataset, config)
    assert np.allclose(original, probabilities(second["cross"], dataset.races[1], build_identity_sha256="test-build"))
    with pytest.raises(ResearchError, match="model_feature_contract_mismatch"):
        probabilities(first["cross"], dataset.races[1], build_identity_sha256="other-build")
    metrics, predictions = evaluate(dataset_fixture(), config, first)
    assert metrics["splits"]["evaluation"]["market"]["tickets"] == 0
    assert {p["variant"] for p in predictions} == {"market", "basic", "cross"}
