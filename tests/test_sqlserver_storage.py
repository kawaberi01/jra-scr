"""概要: SQL方言・設定・行形式・単一backend選択の互換境界を検証する。
作成日: 2026-10-15
入力: 疑似SQLと環境設定。外部接続は使用しない。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_sqlserver_storage.py
注意事項: SQL Serverと既存SQLiteには書き込まない。
"""

import pytest

from jra_srb.sqlserver_db import StorageResult, StorageRow, compile_sql
from jra_srb.storage_config import SqlServerSettings, storage_backend


def test_backend_does_not_reinterpret_sqlite_path():
    """SQL backendに必要な設定欠落を旧DBへのfallbackで隠さない。"""
    assert storage_backend({"JRA_SRB_ANALYSIS_DB_PATH": "Server=example"}) == "sqlite"
    with pytest.raises(ValueError, match="READER_CONNECTION_STRING"):
        SqlServerSettings.from_env({"JRA_SRB_ANALYSIS_DB_PATH": "Server=example"})
    with pytest.raises(ValueError, match="must be sqlite or sqlserver"):
        storage_backend({"JRA_SRB_STORAGE_BACKEND": "unknown"})


def test_settings_hide_secrets_and_require_database():
    """秘密をreprへ表示せず、DB名の明示を必須にする。"""
    env = {"JRA_SRB_SQLSERVER_READER_CONNECTION_STRING": "reader-secret",
           "JRA_SRB_SQLSERVER_WRITER_CONNECTION_STRING": "writer-secret"}
    with pytest.raises(ValueError, match="DATABASE"):
        SqlServerSettings.from_env(env)
    settings = SqlServerSettings.from_env({**env, "JRA_SRB_SQLSERVER_DATABASE": "jra_unified"})
    assert "secret" not in repr(settings)


def test_row_preserves_mapping_and_tuple_contract():
    """dict変換・名前参照・位置参照・tuple展開の既存契約を維持する。"""
    row = StorageRow(("日本語", None, 0), ("name", "missing", "zero"))
    assert dict(row) == {"name": "日本語", "missing": None, "zero": 0}
    assert row["name"] == row[0] == "日本語"
    assert tuple(row) == ("日本語", None, 0)
    result = StorageResult([row])
    assert result.fetchone() == row
    assert result.fetchone() is None
    assert result.fetchall() == []


def test_paging_keeps_argument_meaning_after_tsql_reordering():
    """LIMIT/OFFSET変換とhash条件で増えた引数を正しい順番で束縛する。"""
    sql, indices = compile_sql("SELECT * FROM races WHERE race_id=? ORDER BY course LIMIT ? OFFSET ?", ("races",))
    assert "OFFSET ? ROWS FETCH FIRST ? ROWS ONLY" in sql
    assert tuple(("race", 100, 200)[i] for i in indices) == ("race", "race", 200, 100)


def test_question_marks_inside_literals_are_not_parameters():
    """SQL文字列内の?を引数として取り違えない。"""
    sql, indices = compile_sql("SELECT '?' AS literal, ? AS value", ())
    assert "'?'" in sql
    assert indices == (0,)


def test_upsert_preserves_coalesce_and_serializes_conflicts():
    """更新式の意味を保持し、同じキーの並行upsertをSQL側で排他する。"""
    sql, indices = compile_sql(
        "INSERT INTO races(race_id,race_name) VALUES(?,?) ON CONFLICT(race_id) DO UPDATE SET race_name=coalesce(excluded.race_name,races.race_name)",
        ("races",),
    )
    assert "WITH (HOLDLOCK)" in sql
    assert "COALESCE([excluded].[race_name], [races].[race_name])" in sql
    assert "__hash_race_id" in sql
    assert indices == (0, 1)


def test_utc_comparison_null_order_and_row_order_are_explicit():
    """JST/UTCの同時刻、NULL後置、元の明細順を明示したSQLを作る。"""
    sql, indices = compile_sql(
        "SELECT * FROM odds_entries WHERE julianday(fetched_at)<=julianday(?) ORDER BY popularity IS NULL,popularity,rowid",
        ("odds_entries",),
    )
    assert "SWITCHOFFSET" in sql
    assert "'+00:00'" in sql
    assert "CASE WHEN [popularity] IS NULL THEN 1 ELSE 0 END" in sql
    assert "[__api_rowid]" in sql
    assert indices == (0,)


@pytest.mark.parametrize("sql", ["DROP TABLE races", "SELECT * FROM other_table", "SELECT 1; DELETE FROM races", "SELECT * FROM raw.races"])
def test_runtime_connection_cannot_escape_its_table_contract(sql):
    """DDL・複数文・移送表へのアクセスを通常Store接続から拒否する。"""
    with pytest.raises(ValueError):
        compile_sql(sql, ("races",))
