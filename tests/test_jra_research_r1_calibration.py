"""概要: R1校正研究の期間分離・端点・価格推定・選択時の結果非依存を確認する。
作成日: 2026-10-18
入力: 合成の確率・価格・結果。外部接続なし。
出力: pytest検証結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_r1_calibration.py
注意事項: 実R1の学習・API/SQL接続は行わない。
"""

import numpy as np
import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_r1_calibration import (
    aggregate_reliability, calibrated, discounts, fit_calibrator, fit_price_model,
    paired_interval, price_band, reliability, select_pair,
)


def record(day="2025-10-04"):
    """市場とR1が異なる小さな競走を作る。"""
    return {"race_date": day, "market": np.asarray([.5, .3, .2]),
            "r1_probability": np.asarray([.8, .15, .05]), "target": np.asarray([1., 0., 0.]),
            "keys": [("01", "02"), ("01", "03"), ("02", "03")],
            "prices": np.asarray([5., 10., 20.]), "payouts": {("01", "02"): 400}}


def test_calibration_endpoints_preserve_market_and_r1():
    """縮約0は市場、1はR1、温度1もR1となり合計1を維持する。"""
    r = record()
    assert np.allclose(calibrated(r, {"variant": "C2", "coefficient": 0}), r["market"])
    for variant in ("C0", "C1", "C2"):
        p = calibrated(r, {"variant": variant, "coefficient": 1})
        assert np.allclose(p, r["r1_probability"])
        assert np.isclose(p.sum(), 1)


@pytest.mark.parametrize("variant", ["C0", "C1", "C2"])
def test_calibration_rejects_development_and_evaluation_fit(variant):
    """開発・評価データを校正fitへ渡すと停止する。"""
    for day in ("2025-09-30", "2025-11-01", "2026-01-01"):
        with pytest.raises(ResearchError, match="fit_boundary"):
            fit_calibrator([record(day)], variant)


def test_optimizer_evaluates_endpoints():
    """一方向に改善する場合に境界値を微小係数で置き換えない。"""
    records = [record() for _ in range(10)]
    fitted = fit_calibrator(records, "C1")
    assert fitted["coefficient"] == 2
    shrink = fit_calibrator(records, "C2")
    assert shrink["coefficient"] == 1


def test_price_fit_is_conditional_and_uses_only_training_period():
    """価格補正の学習期限・標本数・上限を確認する。"""
    training = [record("2025-09-06") for _ in range(120)]
    fitted = fit_price_model(training)
    assert fitted["available"]
    assert fitted["fit_hits"] == 120
    assert np.allclose(discounts(np.asarray([5., 10., 80., 81.]), fitted), [.8, .8, .8, 1])
    assert "conditional_on_hit" in fitted["interpretation"]
    with pytest.raises(ResearchError, match="price_fit_boundary"):
        fit_price_model([record("2026-01-01")])
    assert all(b["discount"] == 1 for b in fit_price_model(training[:2])["bands"])


def test_price_adjustment_changes_decision_without_changing_probability():
    """価格補正だけで条件判定が変わり、結果を入力にしないことを確認する。"""
    probabilities, prices = np.asarray([.11, .06]), np.asarray([10., 20.])
    before = probabilities.copy()
    assert select_pair(probabilities, prices, np.ones(2)) == 1
    assert select_pair(probabilities, prices, np.asarray([.8, .8])) is None
    assert np.array_equal(probabilities, before)


def test_fixed_bins_cover_all_pairs_and_never_mix_candidate_pool():
    """全ペアと購入前候補の集計を独立に保つ。"""
    p, y = np.asarray([.005, .02, .2, .775]), np.asarray([0., 0., 0., 1.])
    all_pairs = aggregate_reliability([reliability(p, y)])
    pool = aggregate_reliability([reliability(p, y, [2, 3])])
    assert sum(r["pairs"] for r in all_pairs) == 4
    assert sum(r["pairs"] for r in pool) == 2
    assert sum(r["hits"] for r in all_pairs) == 1
    assert np.isclose(sum(r["predicted_hits"] for r in all_pairs), 1)
    assert [price_band(v) for v in (3.9, 4, 10, 20, 40, 80, 80.1)] == [None, 0, 1, 2, 3, 3, None]


def test_paired_intervals_use_days_and_keep_all_races():
    """日単位再標本化と空の追加期間の表示を確認する。"""
    rows = [{"race_date": d, "loss": {"C0": 3., "C1": 2.9}} for d in ("2026-01-01", "2026-01-01", "2026-01-02")]
    result = paired_interval(rows, "C1")
    assert result["races"] == 3 and result["days"] == 2
    assert np.allclose(result["loss_delta_95"], [-.1, -.1])
    assert paired_interval([], "C1")["loss_delta_95"] is None


def movement_module():
    """追加の価格診断CLIを実行せずに純関数だけ読み込む。"""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts/audit_jra_r1_odds_movement.py"
    spec = importlib.util.spec_from_file_location("r1_movement_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_movement_checks_cutoffs_and_complete_pair_graph():
    """時点順序・全ペア完全性を満たす価格だけを比較する。"""
    import json
    from itertools import combinations

    module = movement_module()
    rows = []
    for horizon, minute, price in (("T30", "00", 120), ("T10", "20", 110)):
        entries = [{"market": "quinella", "odds_status_low": "numeric", "selection_key": f"{i:02d}{j:02d}",
                    "odds_low_x10": price} for i, j in combinations(range(1, 9), 2)]
        rows.append({"horizon": horizon, "selection_status": "selected", "parser_version": "jv-o1o2-v2",
                     "content_sha256": "a" * 64, "cutoff_at": f"2025-10-04T05:{minute}:00+00:00",
                     "announced_at": f"2025-10-04T05:{minute}:00+00:00", "entries_json": json.dumps(entries)})
    earlier, later = module.compare_markets(rows)
    assert len(earlier) == len(later) == 28
    assert earlier[("01", "02")] == 12 and later[("01", "02")] == 11
    rows[1]["announced_at"] = "2025-10-04T05:21:00+00:00"
    with pytest.raises(ResearchError, match="invalid_market"):
        module.compare_markets(rows)
    rows[1]["announced_at"] = rows[1]["cutoff_at"]
    for row in rows:
        row["entries_json"] = "[]"
    with pytest.raises(ResearchError, match="incomplete_pair_graph"):
        module.compare_markets(rows)
