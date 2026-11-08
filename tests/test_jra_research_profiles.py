"""概要: 全研究族の登録と未実装の明示、研究入力の純粋性を検証する。
作成日: 2026-10-15
入力: profile registryと合成設定。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_research_profiles.py
注意事項: 未実装profileを別モデルで成功扱いしない。
"""

import sqlite3

import httpx
import pytest

from jra_research_helpers import config_fixture, dataset_fixture
from jra_srb.jra_research_contracts import PROFILE_ID, ResearchError
from jra_srb.jra_research_evaluation import evaluate, train_models
from jra_srb.jra_research_profiles import profiles, require_profile


def test_all_fifteen_families_remain_visible():
    """初期モデルだけで他の研究族を一覧から消さない。"""
    records = profiles()
    assert {record["family"] for record in records} == {f"R{i:02d}" for i in range(1, 16)}
    assert len({record["profile_id"] for record in records}) == len(records)
    require_profile(PROFILE_ID)
    by_id = {record["profile_id"]: record for record in records}
    assert by_id["ten_trials_sql_v1"]["variants"] == [f"V{i}" for i in range(92, 102)]
    assert by_id["second_ten_sql_v1"]["variants"] == [f"V{i}" for i in range(102, 112)]
    assert by_id["v91_compat_sql_v1"]["variants"] == ["V91A", "V91B", "V91_selected"]
    with pytest.raises(ResearchError, match="profile_not_implemented"):
        require_profile("v91_compat_sql_v1")


def test_training_and_evaluation_do_not_open_db_or_http(monkeypatch):
    """計算段階から旧DBや外部取得へ後退する呼出を拒否する。"""
    def forbidden(*args, **kwargs):
        """計算中の外部データ取得を失敗にする。"""
        raise AssertionError("unexpected data access")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    config, dataset = config_fixture(), dataset_fixture()
    models = train_models(dataset, config)
    metrics, predictions = evaluate(dataset, config, models)
    assert metrics["splits"]["evaluation"]["cross"]["races"] == 1
    assert len(predictions) == 9
