"""概要: 既存Store契約を、同一DB内の隔離schemaで実SQL Serverに対して検証する。
作成日: 2026-10-15
入力: JRA_SRB_SQLSERVER_INTEGRATION_ENV_FILEと管理者秘密ファイルのパス。
出力: pytest結果。専用検証schemaは終了時に削除する。
実行例: uv run pytest -q tests/test_sqlserver_integration.py
注意事項: 外部provider通信なし。既存業務表を更新せず、各testのDMLをrollbackする。
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
import re
from uuid import uuid4

import mssql_python
import pytest

from jra_srb import sqlserver_db
from jra_srb.sqlserver_auxiliary import SqlServerJobRegistry, SqlServerRaceResultStorage, SqlServerTTLCache
from jra_srb.sqlserver_db import SqlServerConnection
from jra_srb.sqlserver_db import SqlServerStorageError
from jra_srb.sqlserver_schema import TABLES
from jra_srb.sqlserver_store import SqlServerAnalysisStore
from jra_srb.storage_config import SqlServerSettings
from jra_srb.models import OddsEntry, RaceOdds, RaceResult, ResultEntry, ResultCollectionJobRequest, ResultStorageKind, ResultCollectionJobStatus
from jra_srb.idempotency import current_key, register_request, IdempotencyConflict
from jra_srb.models import MeetingRace, BetRecordCreateRequest
from jra_srb.models import RaceCard, Runner, PayoutEntry


ROOT = Path(__file__).resolve().parents[1]
ENABLED = bool(os.environ.get("JRA_SRB_SQLSERVER_INTEGRATION_ENV_FILE"))
pytestmark = pytest.mark.skipif(not ENABLED, reason="SQL integration connection files are not explicitly configured")


def _load_module(name: str, path: Path):
    """副作用のない既存test/helper定義をファイルから読み込む。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY = _load_module("sqlserver_existing_store_contract", ROOT / "tests/test_analysis_store.py")
CASES = [name for name, function in vars(LEGACY).items() if name.startswith("test_") and callable(function)
         and "sqlite3." not in inspect.getsource(function) and "schema" not in name
         and name != "test_analysis_store_upserts_card_and_appends_odds_snapshots"
         and "migrat" not in name and not any(mark.name == "parametrize" for mark in getattr(function, "pytestmark", []))]


@pytest.fixture(scope="module")
def sql_environment():
    """明示した管理接続で検証専用schemaを作成し、最後に専用schemaだけを削除する。"""
    admin = _load_module("sqlserver_admin_for_integration", ROOT / "tools/sqlserver_storage_admin.py")
    settings = SqlServerSettings.from_env(admin.read_env(Path(os.environ["JRA_SRB_SQLSERVER_INTEGRATION_ENV_FILE"])))
    values = admin.read_env(Path(os.environ["JRA_SRB_SQLSERVER_INTEGRATION_ADMIN_ENV_FILE"]))
    password = values["JRA_SQLSERVER_OWNER_PASSWORD"].replace("}", "}}")
    server = os.environ["JRA_SRB_SQLSERVER_INTEGRATION_SERVER"]
    schema = "api_verify_" + uuid4().hex[:16]
    assert re.fullmatch(r"api_verify_[a-f0-9]{16}", schema)
    connection = mssql_python.connect(
        f"Server={server};Database={settings.database};UID=jra_owner;PWD={{{password}}};Encrypt=yes;TrustServerCertificate=yes;",
        autocommit=False,
    )
    try:
        admin.command(connection, sqlserver_db.SET_OPTIONS)
        for filename in ("001_api_runtime.sql", "002_write_receipts.sql", "003_request_keys.sql"):
            text = (ROOT / "migrations/sqlserver" / filename).read_text(encoding="utf-8").replace("api_runtime", schema)
            for batch in re.split(r"(?im)^GO\s*$", text):
                if batch.strip():
                    admin.command(connection, batch)
        admin.command(connection, f"INSERT [{schema}].storage_state(state_key,value_json) VALUES(N'baseline',?)",
                      (json.dumps({"version": 1, "status": "ready"}),))
        connection.commit()
        yield settings, schema
    finally:
        connection.rollback()
        for name in ["request_keys", "write_receipts", *reversed(TABLES), "storage_state"]:
            admin.command(connection, f"IF OBJECT_ID(N'{schema}.{name}') IS NOT NULL DROP TABLE [{schema}].[{name}]")
        admin.command(connection, f"IF SCHEMA_ID(N'{schema}') IS NOT NULL EXEC(N'DROP SCHEMA [{schema}]')")
        connection.commit()
        connection.close()


@pytest.fixture
def isolated_sql(sql_environment, monkeypatch):
    """SQL実装の全固定参照先を検証schemaへ向ける。"""
    settings, schema = sql_environment
    sqlserver_db.compile_sql.cache_clear()
    monkeypatch.setattr(sqlserver_db, "SCHEMA", schema)
    original = SqlServerConnection._raw

    def isolated_raw(self, sql, params=()):
        """内部の固定管理SQLも検証schemaへ向け、通常領域への接続を防ぐ。"""
        return original(self, sql.replace("api_runtime.", schema + "."), params)

    monkeypatch.setattr(SqlServerConnection, "_raw", isolated_raw)
    try:
        yield settings, schema
    finally:
        sqlserver_db.compile_sql.cache_clear()


@pytest.fixture
def sql_store(isolated_sql, monkeypatch):
    """各testを一つのrollback専用transactionへ隔離し、実装SQLをそのまま実行する。"""
    settings, schema = isolated_sql
    connection = SqlServerConnection(settings, tuple(TABLES))

    class BorrowedConnection:
        """test全体のtransactionを、Storeの複数操作で共有する。"""

        def __enter__(self):
            """テスト専用接続を貸し出す。"""
            return connection

        def __exit__(self, exc_type, exc, traceback):
            """test末尾のrollbackまでcommitもcloseも行わない。"""
            return False

    def borrow(self, **kwargs):
        """Storeの操作ごとの接続取得をテスト専用接続へ向ける。"""
        return BorrowedConnection()

    for cls in (SqlServerAnalysisStore, SqlServerTTLCache, SqlServerJobRegistry, SqlServerRaceResultStorage):
        monkeypatch.setattr(cls, "_connect", borrow)
    store = SqlServerAnalysisStore(settings)
    try:
        yield store, settings
    finally:
        connection._connection.rollback()
        connection.close()
        sqlserver_db.compile_sql.cache_clear()


@pytest.mark.parametrize("case", CASES)
def test_existing_store_contract_on_sqlserver(case, sql_store, monkeypatch, request):
    """SQLite固有DDL検査を除く既存の業務Store契約をSQL Serverへ適用する。"""
    store, _ = sql_store
    monkeypatch.setattr(LEGACY, "AnalysisSQLiteStore", lambda path: store)
    function = getattr(LEGACY, case)
    arguments = {name: request.getfixturevalue(name) for name in inspect.signature(function).parameters}
    try:
        function(**arguments)
    except Exception as error:
        if isinstance(error, AssertionError):
            with store._connect() as connection:
                rows = connection.execute("SELECT race_id,race_grade FROM races").fetchall()
            error.add_note(f"isolated test races: {rows!r}")
        if error.__context__ is not None:
            # 接続文字列を含まない実行段階のdriver診断だけをtest失敗へ付ける。
            error.add_note(f"SQL operation diagnostic: {error.__context__}")
        raise


def test_identical_receipt_is_idempotent_but_correction_is_append_only(sql_store):
    """同一入力再試行は増殖せず、取得時刻が同じ訂正内容は別観測版を残す。"""
    store, _ = sql_store
    odds = RaceOdds(race_id="209912310501", bet_type="win",
                    entries=[OddsEntry(combination=["1"], odds="3.1")],
                    fetched_at=datetime(2099, 12, 31, tzinfo=UTC), source="fixture")
    store.write_odds(odds, bet_type="win")
    store.write_odds(odds, bet_type="win")
    store.write_odds(odds.model_copy(update={"cache_hit": True}), bet_type="win")
    assert store.count_rows("odds_snapshots") == 1
    assert store.count_rows("odds_entries") == 1
    corrected = odds.model_copy(update={"entries": [OddsEntry(combination=["1"], odds="3.2")]})
    store.write_odds(corrected, bet_type="win")
    assert store.count_rows("odds_snapshots") == 2
    assert store.count_rows("odds_entries") == 2


def test_failed_multi_table_write_rolls_back_receipt_and_parent(isolated_sql, monkeypatch):
    """途中失敗で結果親行と受領履歴がcommitされないことを実接続で確認する。"""
    settings, schema = isolated_sql
    original = SqlServerConnection.execute

    def fail_child(self, sql, params=()):
        """親行保存後の子行書込みだけを失敗させる。"""
        if "insert into result_entries" in sql.lower():
            raise RuntimeError("injected child write failure")
        return original(self, sql, params)

    monkeypatch.setattr(SqlServerConnection, "execute", fail_child)
    store = SqlServerAnalysisStore(settings)
    result = RaceResult(race_id="209912310502", race_name="rollback fixture",
                        results=[ResultEntry(rank="1", horse_no="1", horse_name="fixture")],
                        fetched_at=datetime(2099, 12, 31, tzinfo=UTC), source="fixture")
    with pytest.raises(RuntimeError, match="injected child"):
        store.write_result(result)
    with store._connect(read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM race_results WHERE race_id=?", (result.race_id,)).fetchone()[0] == 0
        assert connection._raw(f"SELECT COUNT(*) FROM [{schema}].write_receipts WHERE race_id=?", (result.race_id,)).fetchone()[0] == 0


def test_cache_expiry_stale_and_result_namespaces(sql_store):
    """期限切れcacheのstale参照と結果保存の名前空間分離をSQLで確認する。"""
    _, settings = sql_store
    cache = SqlServerTTLCache(settings)
    cache.set("fixture-key", {"日本語": [1, None]}, -1)
    stale = cache.get_with_status("fixture-key", allow_expired=True)
    assert stale.hit and stale.expired and stale.value == {"日本語": [1, None]}
    assert not cache.get_with_status("fixture-key").hit
    cache.set("fixture-key", "new-value", 60)
    assert cache.get("fixture-key") == "new-value"
    first = SqlServerRaceResultStorage(settings, "fixture-one")
    second = SqlServerRaceResultStorage(settings, "fixture-two")
    result = RaceResult(race_id="209912310503", results=[], fetched_at=datetime.now(UTC), source="fixture")
    first.write_result(date(2099, 12, 31), "tokyo", 3, result)
    first.write_result(date(2099, 12, 31), "tokyo", 3, result)
    assert first.get_result(result.race_id).result == result
    assert second.get_result(result.race_id) is None
    page = first.list_results_page(limit=1, offset=0)
    assert page.total == len(page.items) == 1


def test_job_round_trip_and_interrupted_recovery(sql_store):
    """jobがSQLから再読込でき、途中再起動を既存のfailed状態へ回復する。"""
    _, settings = sql_store
    registry = SqlServerJobRegistry(settings)
    request = ResultCollectionJobRequest(from_date=date(2099, 12, 31), to_date=date(2099, 12, 31), courses=["tokyo"])
    job = registry.create_job(request, ResultStorageKind.sqlserver, "fixture-jobs")
    assert registry.get_job(job.job_id).status == ResultCollectionJobStatus.queued
    registry._update(job.job_id, status=ResultCollectionJobStatus.running)
    restarted = SqlServerJobRegistry(settings)
    assert restarted.get_job(job.job_id).status == ResultCollectionJobStatus.failed
    assert "interrupted" in restarted.get_job(job.job_id).error


def test_reader_is_denied_business_writes(isolated_sql):
    """reader login自身がDBからINSERTを拒否されることを確認する。"""
    settings, schema = isolated_sql
    with SqlServerConnection(settings, ("races",), read_only=True) as connection:
        with pytest.raises(mssql_python.DatabaseError) as captured:
            connection._raw(f"INSERT [{schema}].races(race_id,race_date,course,race_no) VALUES(N'fixture',N'2099-12-31',N'tokyo',1)")
        assert "permission" in str(captured.value).lower()


def test_explicit_request_key_reuses_purchase_and_rejects_different_body(sql_store):
    """任意キーで購入再試行を同じ記録へ対応し、別bodyへの再利用を拒否する。"""
    store, settings = sql_store
    # register_requestは独立した接続を使うため、その仕様は別の実接続テストで確認する。
    token = current_key.set("purchase-fixture-key")
    try:
        request = BetRecordCreateRequest(race_id="209912310504", total_amount=100,
                                         decision_source="manual", tickets=[{"bet_type": "win", "selection": ["1"], "amount": 100}])
        first = store.create_bet_record(request)
        second = store.create_bet_record(request)
        assert first.bet_record_id == second.bet_record_id
        assert store.count_rows("bet_records") == 1
        assert store.count_rows("bet_record_tickets") == 1
    finally:
        current_key.reset(token)


def test_request_fingerprint_is_fixed_and_job_retries_are_idempotent(isolated_sql):
    """実接続で要求内容とjob IDを固定し、再送による二重jobを防ぐ。"""
    settings, _ = isolated_sql
    key = "job-fixture-" + uuid4().hex
    register_request(settings, key, b"a" * 32)
    register_request(settings, key, b"a" * 32)
    with pytest.raises(IdempotencyConflict):
        register_request(settings, key, b"b" * 32)
    registry = SqlServerJobRegistry(settings)
    request = ResultCollectionJobRequest(from_date=date(2099, 12, 31), to_date=date(2099, 12, 31), courses=["tokyo"])
    token = current_key.set(key)
    try:
        first = registry.create_job(request, ResultStorageKind.sqlserver, "retry-job-fixture")
        second = registry.create_job(request, ResultStorageKind.sqlserver, "retry-job-fixture")
        assert first.job_id == second.job_id
    finally:
        current_key.reset(token)


def test_concurrent_requests_use_independent_connections_and_one_receipt(isolated_sql):
    """同一レースの並行再試行が明細と受領履歴を増殖させないことを確認する。"""
    from concurrent.futures import ThreadPoolExecutor
    settings, schema = isolated_sql
    result = RaceResult(race_id="209912310505", race_name="concurrency fixture",
                        results=[ResultEntry(rank="1", horse_no="1", horse_name="fixture")],
                        fetched_at=datetime(2099, 12, 31, tzinfo=UTC), source="fixture")

    def save_result(_):
        """thread固有のStore接続で同じ受領入力を保存する。"""
        SqlServerAnalysisStore(settings).write_result(result)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save_result, range(4)))
    with SqlServerAnalysisStore(settings)._connect(read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM result_entries WHERE race_id=?", (result.race_id,)).fetchone()[0] == 1
        assert connection._raw(f"SELECT COUNT(*) FROM [{schema}].write_receipts WHERE race_id=?", (result.race_id,)).fetchone()[0] == 1


def test_http_purchase_retry_keeps_body_validation_and_record_identity(isolated_sql, monkeypatch):
    """HTTP bodyの検証を保ったまま再送を同じ購入へ対応し、異なる要求を409にする。"""
    from fastapi.testclient import TestClient
    import jra_srb.app as api
    settings, _ = isolated_sql
    previous = dict(api.app.dependency_overrides)
    monkeypatch.setattr(api, "storage_backend", lambda: "sqlserver")
    monkeypatch.setattr(api.SqlServerSettings, "from_env", classmethod(lambda cls: settings))
    api.app.dependency_overrides[api.get_analysis_store] = lambda: SqlServerAnalysisStore(settings)
    payload = {"race_id": "209912310506", "total_amount": 100, "decision_source": "manual",
               "tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}]}
    try:
        with TestClient(api.app) as client:
            headers = {"Idempotency-Key": "http-purchase-" + uuid4().hex}
            first = client.post("/bet-records", json=payload, headers=headers)
            second = client.post("/bet-records", json=payload, headers=headers)
            assert first.status_code == second.status_code == 201
            assert first.json() == second.json()
            conflict = client.post("/bet-records", json={**payload, "note": "different request"}, headers=headers)
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "idempotency_conflict"
    finally:
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(previous)


def test_history_features_read_sql_without_a_sqlite_file(isolated_sql, monkeypatch, tmp_path):
    """履歴特徴量が存在しないSQLiteパスへfallbackせず、SQLの過去結果を使う。"""
    from jra_srb.jra_history_dataset import build_history_dataset
    from jra_srb.jra_v_theory import _load_history
    settings, _ = isolated_sql
    monkeypatch.setenv("JRA_SRB_STORAGE_ENV_FILE", os.environ["JRA_SRB_SQLSERVER_INTEGRATION_ENV_FILE"])
    monkeypatch.setenv("JRA_SRB_STORAGE_BACKEND", "sqlserver")
    store = SqlServerAnalysisStore(settings)
    card = RaceCard(race_id="209812310501", race_name="history fixture", surface="turf", distance="1600",
                    runners=[Runner(horse_no="1", horse_name="履歴馬", jockey="fixture", trainer="fixture"),
                             Runner(horse_no="2", horse_name="履歴馬二", jockey="fixture", trainer="fixture")],
                    fetched_at=datetime(2098, 12, 31, tzinfo=UTC), source="https://www.jra.go.jp/fixture")
    store.write_card(date(2098, 12, 31), "tokyo", 1, card)
    result = RaceResult(race_id=card.race_id, results=[ResultEntry(rank="1", horse_no="1", horse_name="履歴馬"),
                                                     ResultEntry(rank="2", horse_no="2", horse_name="履歴馬二")],
                        payouts=[PayoutEntry(bet_type="単勝", combination="1", payout="100")],
                        fetched_at=datetime(2098, 12, 31, tzinfo=UTC), source="https://www.jra.go.jp/fixture")
    store.write_result(result)
    missing_path = tmp_path / "must-not-be-created.sqlite"
    records, _ = build_history_dataset(missing_path, through_date=date(2098, 12, 31))
    assert any(row["race_id"] == card.race_id for row in records)
    history = _load_history(missing_path, date(2099, 1, 1))
    assert "履歴馬" in history["horse"]
    assert not missing_path.exists()


def test_recovery_export_and_restore_preserve_values_and_old_constraints(isolated_sql, monkeypatch, tmp_path):
    """隔離SQLの全業務値を回収し、旧DBを上書きせず制約付きコピーへ復元する。"""
    from types import SimpleNamespace
    import sqlite3
    from jra_srb.analysis_store import AnalysisSQLiteStore
    from jra_srb.jobs import ResultCollectionJobRegistry
    settings, schema = isolated_sql
    admin = _load_module("sqlserver_recovery_export_test", ROOT / "tools/sqlserver_storage_admin.py")
    restore = _load_module("sqlserver_recovery_restore_test", ROOT / "tools/restore_sqlserver_recovery.py")
    original_execute = admin.execute

    def isolated_execute(connection, sql, params=()):
        """管理exportも検証schemaだけに限定する。"""
        return original_execute(connection, sql.replace("api_runtime.", schema + "."), params)

    monkeypatch.setattr(admin, "execute", isolated_execute)
    connection = mssql_python.connect(settings.writer_connection_string, autocommit=False)
    try:
        admin.command(connection, sqlserver_db.SET_OPTIONS)
        recovery_path = tmp_path / "recovery.sqlite"
        exported = admin.export_recovery(connection, SimpleNamespace(recovery_path=recovery_path))
    finally:
        connection.close()
    old_analysis = tmp_path / "old-analysis.sqlite"
    old_jobs = tmp_path / "old-jobs.sqlite"
    AnalysisSQLiteStore(old_analysis)
    ResultCollectionJobRegistry(old_jobs)
    before = old_analysis.read_bytes()
    with restore.readonly(recovery_path) as recovery:
        counts = restore.restore_copy(recovery, old_analysis, tmp_path / "restored-analysis.sqlite", "analysis-current")
        assert counts["races"] == exported["counts"]["races"]
        assert counts["result_entries"] == exported["counts"]["result_entries"]
        restore.restore_copy(recovery, old_jobs, tmp_path / "restored-jobs.sqlite", "jobs-current")
    assert old_analysis.read_bytes() == before
    with sqlite3.connect(tmp_path / "restored-analysis.sqlite") as restored:
        assert any(row[2] for row in restored.execute("PRAGMA index_list(races)"))


def test_parent_constraint_failure_rolls_back_scout_run(isolated_sql, monkeypatch):
    """親のないshadow観測を拒否し、先に保存したscout親・明細もrollbackする。"""
    settings, _ = isolated_sql
    original = SqlServerConnection.execute

    def invalidate_parent(self, sql, params=()):
        """観測の参照先だけを不存在runへ変更し、実装の親子検査を通す。"""
        if "insert into jra_live_shadow_observations" in sql.lower():
            params = list(params)
            params[1] = "nonexistent-parent-run"
        return original(self, sql, params)

    monkeypatch.setattr(SqlServerConnection, "execute", invalidate_parent)
    store = SqlServerAnalysisStore(settings)
    with pytest.raises(SqlServerStorageError, match="parent row"):
        LEGACY._save_live_shadow_observation(store, run_id="fk-rollback-fixture", observed_at=datetime.now(UTC), win_odds="3.2")
    with store._connect(read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jra_scout_runs WHERE run_id=?", ("fk-rollback-fixture",)).fetchone()[0] == 0


def test_prediction_input_version_is_frozen_across_current_updates_and_retries(sql_store):
    """current更新後も予想の入力・特徴量・モデル版を保持し、再送で上書きしない。"""
    store, _ = sql_store
    token = current_key.set("prediction-version-fixture")
    try:
        snapshot = {"card": {"runners": [{"horse_no": "1"}]}, "odds": {"1": 3.2},
                    "features": [0.1, 0.2], "model": {"version": "fixture-v1", "sha256": "a" * 64}}
        payload = {"prediction_id": "prediction-version-fixture", "race_id": "209912310507", "theory_version": "fixture-v1",
                   "pre_race_snapshot": snapshot, "prediction_json": {"ranking": ["1"]}, "prediction_tickets": []}
        store.upsert_prediction_record(payload)
        store.write_race(date(2099, 12, 31), "tokyo", MeetingRace(race_id=payload["race_id"], race_no=7, race_name="updated current"))
        changed = {**payload, "pre_race_snapshot": {"model": {"version": "fixture-v2"}}}
        store.upsert_prediction_record(changed)
        assert store.get_prediction_record(payload["prediction_id"]).pre_race_snapshot == snapshot
        assert store.canonical_prediction_record(changed) == payload
    finally:
        current_key.reset(token)
