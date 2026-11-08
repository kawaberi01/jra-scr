"""概要: TTL cache・結果収集job・名前空間付き結果保存をSQL Serverへ保存する。
作成日: 2026-10-15
入力: SQL設定、既存cache/job/ResultStorage契約の呼出し。
出力: SQL Serverの運用データ、従来の応答モデル。
実行例: uv run pytest -q tests/test_sqlserver_storage.py
注意事項: SQLite・起動時DDLは使わない。JSONLの明示exportは別の既存経路を使う。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
import pickle

from .batch import ResultStorage, SQLiteRaceResultStorage
from .cache import SQLiteTTLCache
from .jobs import ResultCollectionJobRegistry
from .models import RaceResult, StoredRaceResultPage
from .sqlserver_db import SqlServerConnection
from .storage_config import SqlServerSettings
from .idempotency import current_key, entity_id, request_digest
from .sqlserver_db import SqlServerStorageError


class SqlServerTTLCache(SQLiteTTLCache):
    """hit・expiry・allow_expiredを保った再生成可能なSQL cacheを提供する。"""

    def __init__(self, settings: SqlServerSettings):
        """設定だけを保持し、cacheの起動時作成を行わない。"""
        self.settings = settings

    def _connect(self) -> SqlServerConnection:
        """期限切れ削除と取得を同一transactionで扱う専用接続を返す。"""
        return SqlServerConnection(self.settings, ("cache_entries",))

    def set(self, key: str, value, ttl_seconds: int) -> None:
        """同一cache keyの値と期限を原子的に置き換える。"""
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO cache_entries(cache_key,value_blob,expires_at) VALUES(?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET value_blob=excluded.value_blob,expires_at=excluded.expires_at""",
                (key, pickle.dumps(value), (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()),
            )


class SqlServerJobRegistry(ResultCollectionJobRegistry):
    """既存job状態・再起動回復をSQLへ保存し、要求ごとに永続状態を読み直す。"""

    def __init__(self, settings: SqlServerSettings):
        """SQLからjobを復元する。SQLiteパスやDDLは利用しない。"""
        self.settings = settings
        super().__init__(None)
        self._load_jobs()
        self._recover_interrupted_jobs()

    @property
    def persistent(self) -> bool:
        """SQL registryはSQLiteパスを持たなくても永続化される。"""
        return True

    def _connect(self) -> SqlServerConnection:
        """job操作専用の短いSQL接続を作る。"""
        return SqlServerConnection(self.settings, ("result_collection_jobs",))

    def list_jobs(self):
        """別要求による状態更新を反映してjob一覧を返す。"""
        self._load_jobs()
        return super().list_jobs()

    def get_job(self, job_id: str):
        """SQLの現在のjob状態を読み戻し、見つからなければ既存404へ伝える。"""
        self._load_jobs()
        return super().get_job(job_id)

    def _new_job_id(self) -> str:
        """任意再試行キーがある場合だけ同じjob IDを生成する。"""
        return entity_id("result_collection_job", "")

    def create_job(self, request, storage, output):
        """明示キーで同じjobの二重作成を防ぎ、キー未指定の新規作成は維持する。"""
        if current_key.get() is None:
            return super().create_job(request, storage, output)
        digest = request_digest("result_collection_job", "")
        job_id = self._new_job_id()
        with self._connect() as connection:
            locked = connection._raw(
                "DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=?,@LockMode='Exclusive',"
                "@LockOwner='Transaction',@LockTimeout=30000; SELECT @result AS lock_result;",
                ("jra-job:" + digest.hex(),),
            ).fetchone()
            if locked is None or locked[0] < 0:
                raise SqlServerStorageError("job creation serialization failed")
            existing = connection.execute("SELECT 1 FROM result_collection_jobs WHERE job_id=?", (job_id,)).fetchone()
            if existing is not None:
                return self.get_job(job_id)
            return super().create_job(request, storage, output)

    async def run_job(self, job_id, service, storage_factory):
        """queued jobだけを原子的に取得し、同じjobの並行実行を防ぐ。"""
        with self._connect() as connection:
            claimed = connection._raw(
                "UPDATE api_runtime.result_collection_jobs WITH (UPDLOCK, ROWLOCK) "
                "SET status=N'running' OUTPUT INSERTED.job_id WHERE job_id=? AND status=N'queued'",
                (job_id,),
            ).fetchone()
        if claimed is not None:
            await super().run_job(job_id, service, storage_factory)


class SqlServerRaceResultStorage(ResultStorage):
    """従来outputごとの結果保存をSQL上の名前空間で独立させる。"""

    def __init__(self, settings: SqlServerSettings, namespace: str):
        """明示outputの識別子を保持し、ファイルやDBを作らない。"""
        self.settings = settings
        self.namespace = namespace

    def _connect(self, *, read_only=False):
        """結果保存に必要な1表だけを許可した接続を返す。"""
        return SqlServerConnection(self.settings, ("stored_race_results",), read_only=read_only)

    def has_race(self, race_id: str) -> bool:
        """同じ名前空間に指定レースの保存があるかを返す。"""
        return self.get_result(race_id) is not None

    def write_result(self, target_date: date, course: str, race_no: int, result: RaceResult) -> None:
        """レース単位で結果JSONを冪等に保存する。"""
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO stored_race_results(storage_namespace,race_id,race_date,course,race_no,result_json)
                VALUES(?,?,?,?,?,?) ON CONFLICT(storage_namespace,race_id) DO UPDATE SET
                race_date=excluded.race_date,course=excluded.course,race_no=excluded.race_no,result_json=excluded.result_json""",
                (self.namespace, result.race_id, target_date.isoformat(), str(course), race_no,
                 json.dumps(result.model_dump(mode="json"), ensure_ascii=False)),
            )

    def get_result(self, race_id: str):
        """名前空間とレースを完全一致させて従来の応答モデルを返す。"""
        with self._connect(read_only=True) as connection:
            row = connection.execute(
                "SELECT race_id,race_date,course,race_no,result_json FROM stored_race_results WHERE storage_namespace=? AND race_id=?",
                (self.namespace, race_id),
            ).fetchone()
        return SQLiteRaceResultStorage._row_to_record(row)

    def list_results(self, from_date=None, to_date=None, course=None):
        """従来の開催日・場・レース番号順で名前空間内の全件を返す。"""
        return self._list(from_date, to_date, course, None, 0)[0]

    def list_results_page(self, from_date=None, to_date=None, course=None, limit=100, offset=0):
        """名前空間で分離した件数と安定したページを返す。"""
        items, total = self._list(from_date, to_date, course, limit, offset)
        return StoredRaceResultPage(items=items, total=total, limit=limit, offset=offset)

    def _list(self, from_date, to_date, course, limit, offset):
        """共通filterを一覧と件数に適用する。"""
        where, params = SQLiteRaceResultStorage._build_filters(from_date, to_date, course)
        where.insert(0, "storage_namespace=?")
        params.insert(0, self.namespace)
        clause = " WHERE " + " AND ".join(where)
        with self._connect(read_only=True) as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM stored_race_results" + clause, params).fetchone()[0])
            query = "SELECT race_id,race_date,course,race_no,result_json FROM stored_race_results" + clause + " ORDER BY race_date,course,race_no,race_id"
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params += [limit, offset]
            rows = connection.execute(query, params).fetchall()
        return [record for row in rows if (record := SQLiteRaceResultStorage._row_to_record(row)) is not None], total
