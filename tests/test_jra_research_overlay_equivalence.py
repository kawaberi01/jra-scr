"""概要: overlayの単勝・ワイド各50候補を旧mainの計算ASTと照合する。
作成日: 2026-10-16
入力: 旧scriptの限定ASTと、同一の合成入力・ラベル・明示精算。
出力: pytestによる全候補summary/採否の数値比較結果。
実行例: uv run pytest -q tests/test_jra_research_overlay_equivalence.py
注意事項: 旧script全体のimport、DB接続、旧成果物の読取・上書きは行わない。
"""

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from jra_srb import jra_research_overlay as overlay
from jra_srb.jra_research_artifacts import RUN_ROOT
from test_jra_research_history_purity import guarded_history_io
from test_jra_research_overlay import _extract


ROOT = Path(__file__).resolve().parents[1]


def _legacy_candidates(kind, rows):
    """旧mainの分割・学習・候補集計だけを実行し、I/O文を含めず返す。"""
    wide = ROOT / "scripts/evaluate_market_price_overlay.py"
    source = wide if kind == "wide" else ROOT / "scripts/evaluate_win_price_overlay.py"
    namespace = {"Any": Any, "dataclass": dataclass, "defaultdict": defaultdict,
                 "np": np, "SimpleImputer": SimpleImputer, "StandardScaler": StandardScaler,
                 "LogisticRegression": LogisticRegression, "make_pipeline": make_pipeline}
    _extract(wide, {"CS"}, namespace)
    names = {"TRAIN_END", "DEV_END", "TAKE_RATE", "OVERLAY_THRESHOLDS", "_matrix", "_summary"}
    names |= {"PairRow", "MIN_WIDE_ODDS", "MAX_WIDE_ODDS"} if kind == "wide" else {
        "HorseRow", "MIN_WIN_ODDS", "MAX_WIN_ODDS"}
    _extract(source, names, namespace)
    old_rows = []
    for row, target, payout in rows:
        common = (row.race_id, row.race_date, row.selection_key, row.features, target,
                  row.market_probability)
        old_rows.append(namespace["PairRow"](*common, payout) if kind == "wide" else
                        namespace["HorseRow"](*common, row.price, payout))
    namespace["rows"] = old_rows
    tree = ast.parse(source.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    assignments = {node.targets[0].id: i for i, node in enumerate(main.body)
                   if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
    body = main.body[assignments["train"]:assignments["report"]]
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(ast.Module(body=body, type_ignores=[])))
    exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["candidates"]


@pytest.mark.parametrize("kind,width,take", [("win", 20, 0.8), ("wide", 40, 0.775)])
def test_all_fifty_candidates_match_legacy_model_and_summary(kind, width, take):
    """同一合成入力から旧mainと新評価の全50候補・採否が一致する。"""
    triples = []
    for index in range(108):
        day = "2025-05-01" if index < 36 else "2025-08-01" if index < 72 else "2025-11-01"
        key = str(index % 3 + 1) if kind == "win" else (str(index % 3 + 1), "8")
        price = (3.0, 5.0, 20.0, 30.0)[index % 4]
        features = tuple(None if j == 0 and index % 7 == 0 else float((index * 3 + j) % 11)
                         for j in range(width))
        row = overlay.OverlayRow(f"r{index // 3}", day, key, features, take / price, price, kind)
        target = int(index % 3 == 0)
        payout = (0, 180, 420, 0, 2500, 0)[index % 6]
        triples.append((row, target, payout))
    dataset = overlay.OverlayDataset(tuple(row for row, _, _ in triples),
                                     tuple(target for _, target, _ in triples),
                                     tuple(payout for _, _, payout in triples))
    with guarded_history_io(RUN_ROOT, ROOT / "configs/research/cross_market_disagreement_sql_v1.json") as attempts:
        actual = overlay.evaluate(dataset)
    assert attempts == []
    expected = _legacy_candidates(kind, triples)
    assert len(expected) == actual["candidate_count"] == 50
    for old, new in zip(expected, actual["candidates"], strict=True):
        assert {key: new[key] for key in old if key not in {"dev", "holdout"}} == {
            key: value for key, value in old.items() if key not in {"dev", "holdout"}}
        for split in ("dev", "holdout"):
            assert {key: new[split][key] for key in old[split]} == old[split]
            assert new[split]["settlement_unknown"] == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), complex(1, 1), True])
def test_nonfinite_or_nonreal_feature_is_rejected_before_imputation(value):
    """明示None以外の非有限・非実数を欠損へ黙変換しない。"""
    row = overlay.OverlayRow("r1", "2025-01-01", "1", (value,) + (1.0,) * 19,
                             0.8 / 5, 5.0, "win")
    with pytest.raises(overlay.ResearchError, match="nonfinite_overlay_feature"):
        overlay._matrix([row])
