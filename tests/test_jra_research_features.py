"""概要: SQL研究の時点・ロスター・マスク・市場数式と結果分離を検証する。
作成日: 2026-10-15
入力: 合成O1/O2・特徴量・ロスター。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_research_features.py
注意事項: DB・HTTP・旧データファイルへ接続しない。
"""

import json

import pytest

from jra_research_helpers import input_fixture, race_rows
from jra_srb.jra_research_contracts import ResearchError, digest, timestamp


def test_input_is_independent_of_target_outcome():
    """対象結果とfinal状態を変えても予測入力の内容を変えない。"""
    rows = race_rows()
    before = input_fixture(rows)
    rows["race"]["status"] = "pending"
    rows["labels"] = []
    rows["payouts"] = []
    assert input_fixture(rows) == before
    assert "rank" not in before.content()


@pytest.mark.parametrize("damage,reason", [("roster", "roster_mismatch"), ("pair", "duplicate_key"),
                                           ("time", "after_cutoff"), ("mask", "unexpected_mask"),
                                           ("formula", "market_feature_mismatch"), ("unknown_name", "unexpected_mask")])
def test_contract_damage_is_not_silently_filled(damage, reason):
    """入力不整合を自動補完せず理由付きで拒否する。"""
    rows = race_rows()
    if damage == "roster":
        rows["entries"].pop()
    elif damage == "pair":
        entries = json.loads(rows["markets"][1]["entries_json"])
        entries.append(entries[0])
        rows["markets"][1]["entries_json"] = json.dumps(entries)
    elif damage == "time":
        rows["markets"][0]["announced_at"] = "2020-01-01T09:31+09:00"
    elif damage == "mask":
        rows["features"][0]["masked_feature_names_json"] = "[]"
    else:
        values = json.loads(rows["features"][0]["features_json"])
        if damage == "formula":
            values["normalized_win_market_share"] = .99
        else:
            values["unknown_column"] = values.pop("age_scaled")
        rows["features"][0]["features_json"] = json.dumps(values)
    with pytest.raises(ResearchError, match=reason):
        input_fixture(rows)


def test_market_scope_ignores_place_inside_o1():
    """O1に混在する複勝明細を単勝の分母へ入れない。"""
    rows = race_rows()
    original = input_fixture(rows)
    entries = json.loads(rows["markets"][0]["entries_json"])
    entries.append({"market": "place", "selection_key": "01", "odds_low_x10": 10, "odds_status_low": "numeric"})
    rows["markets"][0]["entries_json"] = json.dumps(entries)
    changed = input_fixture(rows)
    assert changed.features == original.features
    assert changed.odds == original.odds


def test_timestamp_requires_timezone_and_accepts_minutes():
    """分単位表記をUTCへ変換し、timezone欠損を拒否する。"""
    assert timestamp("2020-01-01T09:30+09:00") == timestamp("2020-01-01T00:30:00Z")
    with pytest.raises(ResearchError, match="invalid_timestamp"):
        timestamp("2020-01-01T09:30")
