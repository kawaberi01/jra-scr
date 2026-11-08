"""概要: 独立JV参照による新しい登録証拠をR11 reader境界で検証する。
作成日: 2026-10-16
入力: 既存R11の合成登録行と、厳密な出典付き証拠。
出力: pytestの成功/拒否結果。
実行例: uv run pytest -q tests/test_jra_research_identity_reader.py
注意事項: SQL接続や登録表の更新は行わない。
"""

from copy import deepcopy
import json

import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_cross_market_sql import validate_registered_identity
from test_jra_research_cross_market_sql import mapping_fixture


def reference_mapping():
    """API元IDを保持し、保存済みfull16と独立JV座標が一致する証拠を作る。"""
    row = deepcopy(mapping_fixture()[0])
    row["evidence_json"] = json.dumps({
        "rule": "registered_full16_reference_v1_no_id_synthesis",
        "source_relation": "live.races", "original_id": row["source_original_id"],
        "stored_full_id": row["jv_race_key_full_16"], "stored_date": row["race_date"],
        "stored_race_no": row["race_no"], "source_venue_label": "コース：走路説明",
        "reference": {"source_snapshot_id": 31, "source_relation": "history.races",
                      "source_rowid": 101, "selected_sha256": "a" * 64,
                      "race_key_full": row["jv_race_key_full_16"], "race_date": row["race_date"],
                      "venue_code": row["venue_code"], "race_no": row["race_no"]}})
    return row


def test_new_reference_evidence_is_supported_without_changing_native_id():
    """明示された新方式を検証し、旧方式の有効な登録も引き続き認める。"""
    validate_registered_identity(reference_mapping())
    validate_registered_identity(mapping_fixture()[0])


@pytest.mark.parametrize("key,value", [("source_snapshot_id", 34), ("source_relation", "live.races"),
                                      ("venue_code", "06"), ("race_no", 12),
                                      ("selected_sha256", ""), ("source_rowid", True)])
def test_reference_provenance_changes_are_rejected(key, value):
    """出典の版/表/座標/本文SHAが変われば登録済みでも採用しない。"""
    row = reference_mapping()
    evidence = json.loads(row["evidence_json"])
    evidence["reference"][key] = value
    row["evidence_json"] = json.dumps(evidence)
    with pytest.raises(ResearchError):
        validate_registered_identity(row)
