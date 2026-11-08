"""概要: opt-inで既存SQLの権限・採用版・hash抽出と時点入力を検証する。
作成日: 2026-10-15
入力: JRA_SRB_RESEARCH_SQL_TESTS=1と研究reader設定。
出力: pytest検証結果。
実行例: 研究SQLテスト環境変数を設定し uv run pytest -q tests/test_jra_research_sqlserver_integration.py
注意事項: SELECTのみ。DBオブジェクトや業務データを作成・変更しない。
"""

import os

import pytest

from jra_srb.jra_research_contracts import ResearchConfig
from jra_srb.jra_research_features import build_input
from jra_srb.jra_research_reader import ResearchReader


pytestmark = pytest.mark.skipif(os.environ.get("JRA_SRB_RESEARCH_SQL_TESTS") != "1", reason="explicit SQL opt-in required")


def test_existing_sql_reader_and_computed_hash_route():
    """実効書込権限が無い接続で同版のInputRaceを構築できる。"""
    config = ResearchConfig.load("configs/research/cross_pool_sql_masked_v2_smoke.json")
    with ResearchReader(config) as reader:
        report = reader.preflight()
        assert report["identity"]["database_name"] == "jra_unified"
        assert report["identity"]["db_owner"] == report["identity"]["db_datawriter"] == 0
        key = "202501050601"
        race = {"race_key": key, "race_date": "2025-01-05", "venue_code": "06"}
        value = build_input(race, reader.race_rows("prediction.features_asof", [key]),
                            reader.race_rows("history.entries", [key]), reader.race_rows("market.odds_asof_index", [key]),
                            snapshot=config.snapshot, horizon="T30")
        assert value.race_key == key and len(value.horses) == 16
        assert all(len(row) == 9 for row in value.features)
