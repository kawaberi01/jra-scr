"""概要: SQL readerの限定route・二巡照合・秘密設定と入力条件を検証する。
作成日: 2026-10-15
入力: 合成readerとJSON設定。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_research_reader.py
注意事項: 実DBへ接続せず、不正SQL/旧DBへの経路を拒否する。
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib

import pytest

from jra_research_helpers import config_fixture, race_rows
from jra_srb.jra_research_contracts import ResearchConfig, ResearchError
from jra_srb.jra_research_reader import ResearchReader, research_connection_string
from jra_srb.jra_research_sources import load_dataset


class FakeReader:
    """SQLと同じ入力を返し、禁止された取得や二巡間変更を検出する。"""

    def __init__(self, *, change=None):
        """初期行・quality・変更種別を用意する。"""
        self.rows = race_rows()
        self.pass_number = 0
        self.change = change
        self.tables = []
        self.report = {"read_consistency": "chunked_unproven", "source": {"source_snapshot_id": 31},
                       "build_identity_sha256": "build", "schema_digest": "schema", "index_digest": "index"}

    @contextmanager
    def read_transaction(self):
        """二巡の抽出を区別する。"""
        self.pass_number += 1
        yield

    def keyset(self, table, *, maximum):
        """候補レースまたは結果を合成行から返す。"""
        self.tables.append(table)
        if table == "history.races":
            row = {**self.rows["race"], "__migration_source_rowid": 1}
            if self.pass_number == 2 and self.change == "status":
                row["status"] = "pending"
            if self.pass_number == 2 and self.change == "candidate":
                row["venue_code"] = "05"
            yield row
        elif table == "history.labels":
            yield from self.rows["labels"]

    def race_rows(self, table, keys):
        """許可されたレース行だけを取得したことを記録する。"""
        self.tables.append(table)
        mapping = {"history.entries": "entries", "prediction.features_asof": "features", "market.odds_asof_index": "markets", "history.payouts": "payouts"}
        return deepcopy(self.rows[mapping[table]])


def test_score_does_not_read_outcome_or_depend_on_result_status():
    """scoreの二巡間にfinal状態が変わっても結果を参照せず成功する。"""
    reader = FakeReader(change="status")
    data = load_dataset(reader, config_fixture(), score_key=reader.rows["race"]["race_key"])
    assert len(data.races) == 1 and not data.outcomes
    assert "history.labels" not in reader.tables and "history.payouts" not in reader.tables
    assert reader.pass_number == 2


def test_input_change_between_passes_rejects_dataset():
    """二巡で入力が変われば使用せず終了コード5で停止する。"""
    with pytest.raises(ResearchError, match="source_changed") as error:
        load_dataset(FakeReader(change="candidate"), config_fixture())
    assert error.value.exit_code == 5


def test_reader_rejects_nonselect_and_invalid_routes():
    """研究readerへ任意更新・labels hash route・巨大キーを渡せない。"""
    reader = ResearchReader(config_fixture(), "not-used")
    with pytest.raises(ResearchError, match="non_select_rejected"):
        with reader._cursor("bad", "DELETE FROM history.races"):
            pass
    with pytest.raises(ResearchError, match="invalid_race_table"):
        reader.race_rows("history.labels", ["x"])
    with pytest.raises(ResearchError, match="invalid_key_batch"):
        reader.race_rows("history.entries", ["x"] * 501)


@pytest.mark.parametrize("damage", ["overlap", "compact_date", "horizon", "unknown_key", "memory", "model_nan", "schema_bool", "snapshot_bool"])
def test_config_rejects_ambiguous_or_unsafe_settings(damage):
    """日付・分割・時点・上限の意味変更を明示拒否する。"""
    value = deepcopy(config_fixture().raw)
    if damage == "overlap":
        value["splits"]["dev"] = value["splits"]["train"]
    elif damage == "compact_date":
        value["date_from"] = "20200101"
    elif damage == "horizon":
        value["horizon"] = "T10"
    elif damage == "memory":
        value["limits"]["memory_bytes"] = -1
    elif damage == "model_nan":
        value["model"]["C"] = float("nan")
    elif damage == "schema_bool":
        value["schema_version"] = True
    elif damage == "snapshot_bool":
        value["source_policy"]["snapshot_id"] = True
    else:
        value["sqlite_fallback"] = True
    with pytest.raises(ResearchError) as error:
        ResearchConfig.parse(value)
    assert error.value.exit_code == 2


def test_secret_file_rejects_writer_and_api_configuration(tmp_path, monkeypatch):
    """研究専用ファイルからwriter設定を読まない。"""
    path = tmp_path / "research.env"
    path.write_text("JRA_SRB_SQLSERVER_WRITER_CONNECTION_STRING=secret\n", encoding="utf-8")
    monkeypatch.delenv("JRA_SRB_RESEARCH_READER_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("JRA_SRB_RESEARCH_ENV_FILE", str(path))
    with pytest.raises(ResearchError, match="invalid_research_secret_file"):
        research_connection_string()


@pytest.mark.parametrize("phase", ["execute", "fetch_or_consume"])
def test_sql_failure_keeps_safe_phase_and_elapsed_without_secrets(phase):
    """SQL失敗の段階・時間・引数件数を残し、例外本文と秘密を転記しない。"""
    class Cursor:
        """実DBを呼ばず、指定段階のdriver相当失敗を再現する。"""

        def execute(self, sql, params):
            """実行段階の試験だけ失敗させる。"""
            self.execute_calls = getattr(self, "execute_calls", 0) + 1
            if phase == "execute":
                raise RuntimeError("[HY000] password=do-not-log; source body")

        def close(self):
            """テストcursorを解放する。"""
            self.closed = True

    class Connection:
        """合成cursorだけを返す。"""

        def cursor(self):
            """外部接続を持たないcursorを返す。"""
            return cursor

    cursor = Cursor()
    reader = ResearchReader(config_fixture(), "do-not-log")
    reader.connection = Connection()
    with pytest.raises(ResearchError, match="sql_query_failed") as caught:
        with reader._cursor("race:history.payouts", "SELECT 1 WHERE ?=?", ("secret-param", "secret-param")):
            raise RuntimeError("[HY000] password=do-not-log; source body")
    details = caught.value.details
    assert details["phase"] == phase
    assert details["sqlstate"] == "HY000"
    assert details["parameter_count"] == 2
    assert details["elapsed_seconds"] >= 0
    assert "secret-param" not in repr(details) and "do-not-log" not in repr(details)
    assert "source body" not in repr(details)
    assert cursor.closed and len(reader.query_metrics) == 1
    assert cursor.execute_calls == 1
