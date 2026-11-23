"""概要: 共通条件共有の時点境界と、市場合意選抜の規則を検証する。
作成日: 2026-11-15
入力: 合成レース・価格・元設定。
出力: pytestの確認結果。
実行例: uv run pytest -q tests/test_jra_shared_and_consensus.py
注意事項: 外部通信・DB・当日結果参照なし。
"""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_jra_shared_parts import share_config, shared_pool
from run_jra_plan_consensus import select_horses, choose
from jra_srb.jra_race_conditions import load_config


def test_sharing_excludes_same_year_and_keeps_only_relative_features():
    """対象日前であっても同年他レースを共有せず、絶対条件を共有しない。"""
    rows = [dict(race_date=d, evaluation_eligible=ok) for d, ok in
            [("2024-11-01", True), ("2025-11-01", False), ("2026-01-01", True), ("2027-01-01", True)]]
    assert shared_pool(rows, {"race_date": "2026-11-15"}) == rows[:1]
    original = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    before = deepcopy(original)
    selected = share_config(original)
    assert [f for fs in selected["groups"].values() for f in fs] == ["previous_rank", "interval", "distance_change", "weight_change"]
    assert original == before


def test_market_pool_changes_plan_without_changing_probabilities():
    """人気の集合内でモデル順を保ち、馬評価を変更しない。"""
    runners = [dict(horse_no=str(i), probability_top3=(10-i)/15) for i in range(1, 10)]
    quotes = {i: float(11-i) for i in range(1, 10)}
    original = deepcopy(runners)
    assert select_horses(runners, quotes, "original") == [1, 2, 3]
    assert select_horses(runners, quotes, "half") == [5, 6, 7]
    assert select_horses(runners, quotes, "third") == [7, 8, 9]
    assert select_horses(runners, quotes, "market") == [9, 8, 7]
    assert runners == original
    with pytest.raises(AssertionError):
        select_horses(runners, {i:q for i,q in quotes.items() if i!=9}, "half")


def test_choose_uses_capture_and_never_payout():
    """高配当で候補を選ばず、同じ捕捉なら基準を保持する。"""
    rows = [dict(policy=p, captured=1, payout_yen=999999 if p == "market" else 0)
            for p in ("original", "half", "third", "market")]
    assert choose(rows) == "original"
    rows[1]["captured"] = 2
    assert choose(rows) == "half"
