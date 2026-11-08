"""概要: 研究専用readerで既存SQL版を検査し、固定SELECTを分割実行する。
作成日: 2026-10-15
入力: 研究reader環境変数、研究専用秘密ファイル、非秘密の実験設定。
出力: schema/権限/採用版の診断、分割されたSQL行。
実行例: uv run python scripts/run_jra_research.py preflight --config configs/research/cross_pool_sql_masked_v2.json
注意事項: SQL更新・API起動・別DBへのfallbackなし。秘密値やdriver例外本文を出力しない。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Iterator

from .jra_research_contracts import EXPECTED_FEATURE_NAMES, ResearchConfig, ResearchError, canonical_json, digest
from .jra_research_resources import check_memory


TABLE_COLUMNS = {
    "history.races": ("race_key", "race_date", "venue_code", "race_no", "status", "start_time_status", "feature_eligibility"),
    "history.entries": ("race_key", "horse_no", "horse_id"),
    "prediction.features_asof": ("race_key", "horse_no", "horizon", "market_cutoff_at", "o1_announced_at", "o2_announced_at", "features_json", "masked_feature_names_json", "feature_status", "source_o1_sha256", "source_o2_sha256"),
    "market.odds_asof_index": ("race_key", "horizon", "market", "cutoff_at", "announced_at", "content_sha256", "selection_status", "parser_version", "entries_json"),
    "history.labels": ("race_key", "horse_no", "rank", "abnormal_code", "official_win_settlement", "settlement_status", "se_sha256", "hr_sha256"),
    "history.payouts": ("race_key", "market", "slot", "selection_raw", "payout_raw", "payout_yen", "slot_status", "hr_sha256"),
    "ops.source_build_manifest": ("key", "value_json"),
}
OPS_TABLES = ("ops.source_database", "ops.source_snapshot", "ops.current_source_snapshot", "ops.source_table", "ops.import_batch")
SET_OPTIONS = (
    "SET NOCOUNT ON; SET XACT_ABORT ON; SET ANSI_NULLS ON; SET ANSI_PADDING ON; "
    "SET ANSI_WARNINGS ON; SET ARITHABORT ON; SET CONCAT_NULL_YIELDS_NULL ON; "
    "SET QUOTED_IDENTIFIER ON; SET NUMERIC_ROUNDABORT OFF; SET LOCK_TIMEOUT 10000;"
)


def research_connection_string() -> str:
    """API設定に触れず、研究専用のreader設定だけを取得する。

    Notes:
        環境変数を優先する。未指定時だけdata/storage/research.envを読む。
        ファイルはGit管理外で、readerキー以外を許可しない。
    """
    value = os.environ.get("JRA_SRB_RESEARCH_READER_CONNECTION_STRING", "").strip()
    if value:
        return value
    path = Path(os.environ.get("JRA_SRB_RESEARCH_ENV_FILE", "data/storage/research.env"))
    if path.is_file():
        entries = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, text = line.partition("=")
            if not separator or key.strip() != "JRA_SRB_RESEARCH_READER_CONNECTION_STRING" or entries:
                raise ResearchError("invalid_research_secret_file", 3)
            entries[key.strip()] = text.strip()
        value = entries.get("JRA_SRB_RESEARCH_READER_CONNECTION_STRING", "")
    if not value:
        raise ResearchError("missing_research_reader", 3)
    return value


def _json_cell(value):
    """SQLのbinary/datetime値を秘密を含まないJSON向け実値へ変換する。"""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class ResearchReader:
    """1研究実行の接続を所有し、固定された読取routeだけを提供する。"""

    def __init__(self, config: ResearchConfig, connection_string: str | None = None):
        """設定と明示reader文字列を保持し、まだ接続しない。"""
        self.config, self._secret = config, connection_string
        self.connection = None
        self.report = {}
        self.query_metrics = []
        self.scan_rows = {}

    def __enter__(self):
        """SQLへ接続し、必要SETだけをsession内へ適用する。"""
        try:
            import mssql_python
            self.connection = mssql_python.connect(self._secret or research_connection_string(), autocommit=True)
            self.connection.timeout = self.config.raw["limits"]["query_timeout_seconds"]
            cursor = self.connection.cursor()
            try:
                cursor.execute(SET_OPTIONS)
            finally:
                cursor.close()
            return self
        except ResearchError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ResearchError("sql_connection_failed", 3) from None

    def __exit__(self, exc_type, exc, traceback):
        """例外の有無によらず接続を閉じる。"""
        self.close()

    def close(self) -> None:
        """研究接続を閉じ、未完了読取transactionはrollbackする。"""
        if self.connection is not None:
            try:
                if not self.connection.autocommit:
                    self.connection.rollback()
            finally:
                self.connection.close()
                self.connection = None

    @contextmanager
    def _cursor(self, query_id: str, sql: str, params=()):
        """固定SELECTのcursorを所有し、非秘密の実行診断を残す。"""
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ResearchError("non_select_rejected", 3)
        started, cursor = time.monotonic(), self.connection.cursor()
        bound_params = tuple(params)
        metric = {"query_id": query_id, "parameter_count": len(bound_params), "phase": "execute"}
        try:
            cursor.execute(sql, bound_params)
            metric["phase"] = "fetch_or_consume"
            yield cursor
            metric["status"] = "passed"
        except ResearchError:
            metric["status"] = "failed"
            raise
        except Exception as error:
            metric["status"] = "failed"
            state = getattr(error, "sqlstate", None)
            if not state and error.args and re.fullmatch(r"[A-Z0-9]{5}", str(error.args[0])):
                state = str(error.args[0])
            if not state:
                for argument in error.args:
                    match = re.search(r"\[([A-Z0-9]{5})\]", str(argument))
                    if match:
                        state = match.group(1)
                        break
            raise ResearchError("sql_query_failed", 3, query_id=query_id,
                                sqlstate=state if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state) else None,
                                error_type=type(error).__name__, phase=metric["phase"],
                                elapsed_seconds=round(time.monotonic() - started, 3),
                                parameter_count=len(bound_params)) from None
        finally:
            cursor.close()
            metric["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.query_metrics.append(metric)

    def _small(self, query_id: str, sql: str, params=()) -> list[dict]:
        """小規模なメタデータSELECTを最大1万行で取得する。"""
        with self._cursor(query_id, sql, params) as cursor:
            names = [column[0] for column in cursor.description]
            rows = cursor.fetchmany(10001)
            if len(rows) > 10000:
                raise ResearchError("metadata_row_limit", 3, query_id=query_id)
            return [{name: _json_cell(value) for name, value in zip(names, row, strict=True)} for row in rows]

    def preflight(self) -> dict:
        """DB/権限/列・索引・版・生成契約を既存SELECTで検査する。"""
        identity = self._small("identity", "SELECT DB_NAME() database_name,CURRENT_USER database_user,IS_SRVROLEMEMBER('sysadmin') sysadmin,IS_ROLEMEMBER('db_owner') db_owner,IS_ROLEMEMBER('db_ddladmin') db_ddladmin,IS_ROLEMEMBER('db_datawriter') db_datawriter")[0]
        if identity["database_name"] != "jra_unified" or any(identity[k] != 0 for k in ("sysadmin", "db_owner", "db_ddladmin", "db_datawriter")):
            raise ResearchError("unexpected_database_or_privilege", 3)
        permissions = []
        for scope, name, allowed, denied in (
            ("DATABASE", "jra_unified", (), ("CONTROL", "ALTER ANY SCHEMA", "CREATE TABLE")),
            *(("SCHEMA", schema, (), ("ALTER", "CONTROL")) for schema in ("history", "market", "prediction", "ops")),
            *(("OBJECT", table, ("SELECT",), ("INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL")) for table in (*TABLE_COLUMNS, *OPS_TABLES)),
        ):
            for permission in (*allowed, *denied):
                result = self._small("permission", "SELECT HAS_PERMS_BY_NAME(?,?,?) permitted", (name, scope, permission))[0]["permitted"]
                if result != int(permission in allowed):
                    raise ResearchError("permission_contract_failed", 3, scope=scope, object=name, permission=permission)
                permissions.append((scope, name, permission, result))
        source = self._small("source", "SELECT d.source_key,s.source_snapshot_id,s.source_database_id,s.status,s.schema_catalog_sha256 FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (self.config.snapshot,))
        if len(source) != 1 or source[0]["source_key"] != self.config.raw["source_policy"]["source_key"] or source[0]["status"] != "verified":
            raise ResearchError("unverified_source", 3)
        schema, indexes, computed, routes = [], [], [], {}
        for table, required in TABLE_COLUMNS.items():
            columns = self._small("schema", "SELECT c.name,t.name type_name,c.max_length,c.is_nullable FROM sys.columns c JOIN sys.types t ON c.user_type_id=t.user_type_id WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id", (table,))
            column_names = {row["name"] for row in columns}
            missing = (set(required) | {"__migration_source_snapshot_id", "__migration_source_rowid"}) - column_names
            if missing:
                raise ResearchError("missing_schema_columns", 3, table=table, columns=sorted(missing))
            index_rows = self._small("indexes", "SELECT i.name,i.is_unique,i.is_disabled,i.is_hypothetical,i.filter_definition,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
            groups = {}
            for row in index_rows:
                if not row["is_disabled"] and not row["is_hypothetical"] and not row["filter_definition"]:
                    groups.setdefault(row["name"], []).append(row["column_name"])
            if table in {"history.races", "history.labels", "ops.source_build_manifest"}:
                prefix = ["__migration_source_snapshot_id", "__migration_source_rowid"]
                route = "snapshot_rowid_keyset"
            else:
                prefix = ["__migration_source_snapshot_id", "__unified_race_sha256"]
                route = "snapshot_race_hash"
                definitions = self._small("computed", "SELECT name,definition FROM sys.computed_columns WHERE object_id=OBJECT_ID(?) AND name='__unified_race_sha256'", (table,))
                if len(definitions) != 1 or not definitions[0]["definition"]:
                    raise ResearchError("missing_hash_definition", 3, table=table)
                computed.append({"table": table, **definitions[0]})
                definition = definitions[0]["definition"].lower()
                if not all(token in definition for token in ("sha2_256", "varbinary", "race_key")):
                    raise ResearchError("unexpected_hash_definition", 3, table=table)
            if not any(cols[:2] == prefix for cols in groups.values()):
                raise ResearchError("missing_index_route", 3, table=table, route=route)
            if route == "snapshot_rowid_keyset" and not any(
                row["is_unique"] and groups.get(row["name"], []) == prefix for row in index_rows):
                raise ResearchError("keyset_requires_unique_index", 3, table=table)
            routes[table] = route
            schema.append({"table": table, "columns": columns})
            indexes.append({"table": table, "indexes": index_rows})
        manifest_rows = list(self.keyset("ops.source_build_manifest", maximum=10000))
        manifest = {row["key"]: json.loads(row["value_json"]) for row in manifest_rows}
        build, status = manifest.get("build_identity", {}), manifest.get("run_status", {})
        if status.get("status") != "complete" or status.get("research_dataset_complete") is not True:
            raise ResearchError("incomplete_build", 3)
        if set(status.get("feature_columns", [])) != EXPECTED_FEATURE_NAMES:
            raise ResearchError("unexpected_feature_definition", 3)
        if not build or str(build.get("config", {}).get("schema_version")) != "2" or build.get("config", {}).get("odds_parser_version") != "jv-o1o2-v2":
            raise ResearchError("unexpected_build_identity", 3)
        expected = self.config.raw["source_policy"].get("build_identity_sha256")
        if expected and digest(build) != expected:
            raise ResearchError("build_identity_changed", 3)
        isolation = self._small("isolation", "SELECT snapshot_isolation_state,is_read_committed_snapshot_on FROM sys.databases WHERE name=DB_NAME()")[0]
        if self.config.raw["quality"]["require_atomic_snapshot"] and isolation["snapshot_isolation_state"] != 1:
            raise ResearchError("atomic_snapshot_unavailable")
        self.report = {"identity": identity, "source": source[0], "schema_digest": digest(schema),
                       "index_digest": digest(indexes), "computed_digest": digest(computed), "routes": routes,
                       "build_identity_sha256": digest(build), "build_identity": build, "build_status": status,
                       "permission_checks": len(permissions), "isolation": isolation,
                       "read_consistency": "snapshot_transaction" if isolation["snapshot_isolation_state"] == 1 else "chunked_unproven"}
        return self.report

    def keyset(self, table: str, *, maximum: int) -> Iterator[dict]:
        """既存版/rowid索引で許可表だけを有界・一巡で走査する。"""
        allowed = {"history.races", "history.labels", "ops.source_build_manifest"}
        if table not in allowed:
            raise ResearchError("invalid_keyset_table", 3)
        fields = ("__migration_source_rowid", *TABLE_COLUMNS[table])
        previous, seen = None, 0
        while True:
            size = min(self.config.raw["limits"]["fetch_rows"], maximum - seen + 1)
            quoted = ",".join(f"[{x}]" for x in fields)
            sql = f"SELECT TOP (?) {quoted} FROM {table} WHERE __migration_source_snapshot_id=?"
            params = [size, self.config.snapshot]
            if previous is not None:
                sql += " AND __migration_source_rowid>?"
                params.append(previous)
            sql += " ORDER BY __migration_source_rowid"
            with self._cursor("keyset:" + table, sql, params) as cursor:
                rows = cursor.fetchmany(size)
            if not rows:
                break
            check_memory(self.config.raw["limits"]["memory_bytes"])
            for raw in rows:
                row = dict(zip(fields, raw, strict=True))
                identifier = row["__migration_source_rowid"]
                if identifier is None or previous is not None and identifier <= previous:
                    raise ResearchError("invalid_keyset_rowid", 3, table=table)
                seen += 1
                self.scan_rows[table] = self.scan_rows.get(table, 0) + 1
                if seen > maximum:
                    raise ResearchError("scan_row_limit", 4, table=table, maximum=maximum)
                previous = identifier
                yield row

    def race_rows(self, table: str, keys: list[str]) -> list[dict]:
        """版+UTF16LE race hash+元値の厳密一致で最大500raceを抽出する。"""
        if table not in TABLE_COLUMNS or table in {"history.races", "history.labels", "ops.source_build_manifest"}:
            raise ResearchError("invalid_race_table", 3)
        if not keys or len(keys) > self.config.raw["limits"]["batch_races"] or len(keys) != len(set(keys)):
            raise ResearchError("invalid_key_batch", 3)
        values, params = [], []
        for key in keys:
            values.append("(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))")
            params.extend((hashlib.sha256(key.encode("utf-16le")).digest(), key))
        params.append(self.config.snapshot)
        fields = TABLE_COLUMNS[table]
        sql = "SELECT " + ",".join(f"t.[{x}]" for x in fields)
        sql += f" FROM {table} t JOIN (VALUES {','.join(values)}) k(hash_value,race_key) ON t.__unified_race_sha256=k.hash_value AND CONVERT(varbinary(max),t.race_key)=CONVERT(varbinary(max),k.race_key) WHERE t.__migration_source_snapshot_id=?"
        if table in {"prediction.features_asof", "market.odds_asof_index"}:
            sql += " AND t.horizon=?"
            params.append(self.config.raw["horizon"])
        rows = []
        with self._cursor("race:" + table, sql, params) as cursor:
            while batch := cursor.fetchmany(self.config.raw["limits"]["fetch_rows"]):
                rows.extend(dict(zip(fields, raw, strict=True)) for raw in batch)
                check_memory(self.config.raw["limits"]["memory_bytes"])
                if len(rows) > 500000:
                    raise ResearchError("batch_row_limit", 4, table=table)
        if any(row["race_key"] not in keys for row in rows):
            raise ResearchError("race_hash_mismatch", 3)
        return rows

    @contextmanager
    def read_transaction(self):
        """既存設定が許せば一つのSNAPSHOT transactionで抽出する。"""
        atomic = self.report["read_consistency"] == "snapshot_transaction"
        if atomic:
            self.connection.autocommit = False
            cursor = self.connection.cursor()
            try:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
            finally:
                cursor.close()
        try:
            yield
        finally:
            if atomic:
                self.connection.rollback()
                self.connection.autocommit = True
