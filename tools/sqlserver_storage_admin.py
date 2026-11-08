"""概要: API運用schemaの明示適用・SQL採用版のseed・照合を段階別に行う。
作成日: 2026-10-15
入力: 接続先、管理者用の外部秘密ファイル、版管理されたDDL・列契約。
出力: api_runtime領域と秘密を含まない監査JSON。
実行例: uv run python tools/sqlserver_storage_admin.py --help
注意事項: jra_unified限定。既存移送表は参照のみ。API起動から呼び出さない。
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import math

import mssql_python

from jra_srb.sqlserver_db import SET_OPTIONS
from jra_srb.sqlserver_schema import CONTRACT, TABLES


ROOT = Path(__file__).resolve().parents[1]


def read_env(path: Path) -> dict[str, str]:
    """明示ファイルから秘密をメモリ内へ読み、値を出力しない。"""
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name and not name.startswith("#"):
            values[name] = value.strip().strip('"').strip("'")
    return values


def execute(connection, sql, params=()):
    """管理用の単一cursorを実行し、呼出側へ返す。"""
    cursor = connection.cursor()
    cursor.execute(sql, tuple(params))
    return cursor


def scalar(connection, sql, params=()):
    """管理用SQLの先頭値だけを取得しcursorを閉じる。"""
    cursor = execute(connection, sql, params)
    try:
        row = cursor.fetchone()
        return row[0] if row is not None else None
    finally:
        cursor.close()


def command(connection, sql, params=()):
    """戻り行のない管理SQLを実行してcursorを閉じる。"""
    execute(connection, sql, params).close()


def connect(args):
    """管理専用loginを使い、指定DBへ接続する。通常APIとは共有しない。"""
    if args.database != "jra_unified":
        raise ValueError("管理対象は既存jra_unifiedに限定されています")
    values = read_env(args.admin_secrets_file)
    password = values[args.admin_secret_name].replace("}", "}}")
    connection = mssql_python.connect(
        f"Server={args.server};Database={args.database};UID={args.admin_user};PWD={{{password}}};Encrypt=yes;TrustServerCertificate=yes;",
        autocommit=False,
    )
    connection.timeout = 300
    command(connection, SET_OPTIONS)
    if scalar(connection, "SELECT DB_NAME()") != args.database:
        connection.close()
        raise ValueError("実接続DBが指定と異なります")
    return connection


def current_sources(connection) -> dict[str, int]:
    """verifiedの採用版だけをsource_keyから解決する。"""
    cursor = execute(connection,
        "SELECT d.source_key,cs.source_snapshot_id,s.status FROM ops.current_source_snapshot cs "
        "JOIN ops.source_database d ON d.source_database_id=cs.source_database_id "
        "JOIN ops.source_snapshot s ON s.source_snapshot_id=cs.source_snapshot_id "
        "WHERE d.source_key IN (N'analysis-current',N'jobs-current')")
    rows = cursor.fetchall()
    cursor.close()
    if len(rows) != 2 or any(row[2] != "verified" for row in rows):
        raise ValueError("必要な採用snapshotがverifiedではありません")
    return {row[0]: int(row[1]) for row in rows}


def state(connection, key: str):
    """運用領域の状態を読む。領域未作成ならNoneを返す。"""
    if not scalar(connection, "SELECT OBJECT_ID(N'api_runtime.storage_state')"):
        return None
    value = scalar(connection, "SELECT value_json FROM api_runtime.storage_state WHERE state_key=?", (key,))
    return json.loads(value) if value else None


def save_state(connection, key: str, value: dict):
    """管理操作の状態を原子的に保存し、APIの通常roleには更新を許可しない。"""
    command(connection,
        "MERGE api_runtime.storage_state WITH(HOLDLOCK) AS t USING(SELECT ? state_key,? value_json) s ON t.state_key=s.state_key "
        "WHEN MATCHED THEN UPDATE SET value_json=s.value_json,updated_at_utc=SYSUTCDATETIME() "
        "WHEN NOT MATCHED THEN INSERT(state_key,value_json) VALUES(s.state_key,s.value_json);",
        (key, json.dumps(value, ensure_ascii=False)))


def plan(connection) -> dict:
    """対象・件数目安・割当容量・schema状態を読み取り専用で返す。"""
    cursor = execute(connection, "SELECT name,CONVERT(bigint,size)*8192 size_bytes,CONVERT(bigint,FILEPROPERTY(name,'SpaceUsed'))*8192 used_bytes FROM sys.database_files")
    files = [list(row) for row in cursor.fetchall()]
    cursor.close()
    return {"database": scalar(connection, "SELECT DB_NAME()"), "sources": current_sources(connection),
            "runtime_tables": len(TABLES), "source_tables": sum("source" in table for table in TABLES.values()),
            "schema_version": state(connection, "schema"), "baseline": state(connection, "baseline"), "database_files": files,
            "ddl_sha256": hashlib.sha256((ROOT / "migrations/sqlserver/001_api_runtime.sql").read_bytes()).hexdigest()}


def apply_schema(connection) -> dict:
    """確認した版管理DDLだけを明示適用し、既存移送表は変更しない。"""
    if state(connection, "schema"):
        raise ValueError("schemaは適用済みです。再適用で既存定義を上書きしません")
    text = (ROOT / "migrations/sqlserver/001_api_runtime.sql").read_text(encoding="utf-8")
    for batch in re.split(r"(?im)^GO\s*$", text):
        if batch.strip():
            command(connection, batch)
    value = {"version": CONTRACT["version"], "applied_at_utc": datetime.now(UTC).isoformat(),
             "ddl_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "tables": list(TABLES)}
    save_state(connection, "schema", value)
    connection.commit()
    return value


def apply_receipts(connection) -> dict:
    """業務writer未公開の段階で受領履歴の版管理DDLを追加する。"""
    if not state(connection, "schema"):
        raise ValueError("先に001のschemaを適用してください")
    text = (ROOT / "migrations/sqlserver/002_write_receipts.sql").read_text(encoding="utf-8")
    command(connection, text)
    value = {"version": 2, "applied_at_utc": datetime.now(UTC).isoformat(),
             "ddl_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "table": "write_receipts"}
    save_state(connection, "migration_002", value)
    connection.commit()
    return value


def apply_request_keys(connection) -> dict:
    """任意POST再試行キーの台帳を明示migrationとして追加する。"""
    text = (ROOT / "migrations/sqlserver/003_request_keys.sql").read_text(encoding="utf-8")
    command(connection, text)
    value = {"version": 3, "applied_at_utc": datetime.now(UTC).isoformat(),
             "ddl_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "table": "request_keys"}
    save_state(connection, "migration_003", value)
    connection.commit()
    return value


def publish(connection, args) -> dict:
    """最終source不変性を再確認し、ready状態とローカルSQL設定を明示採用する。"""
    baseline = state(connection, "baseline")
    if baseline is None or baseline.get("status") != "final_sqlite_verified":
        raise ValueError("最終SQLite照合の完了が必要です")
    for rows in baseline["source_files"].values():
        if file_state(Path(rows[0]["path"])) != rows:
            raise ValueError("最終照合後に旧SQLiteが変更されています")
    if not state(connection, "migration_002") or not state(connection, "migration_003"):
        raise ValueError("受領履歴と再試行キーのmigrationが未完了です")
    if args.runtime_env_file is None or args.publish_env_file is None or args.publish_env_file.exists():
        raise ValueError("未配置のpublish先と検証済みruntime設定を明示してください")
    settings = read_env(args.runtime_env_file)
    if settings.get("JRA_SRB_STORAGE_BACKEND") != "sqlserver" or settings.get("JRA_SRB_SQLSERVER_DATABASE") != args.database:
        raise ValueError("publish設定のbackend/DBが不正です")
    if args.writer_stop_evidence is None:
        raise ValueError("writer停止の現物確認記録が必要です")
    evidence = json.loads(args.writer_stop_evidence.read_text(encoding="utf-8-sig"))
    if evidence.get("active_writer_processes") != [] or evidence.get("daily_task_state") != "Disabled":
        raise ValueError("writer停止または日次task停止を確認できません")
    value = {**baseline, "status": "ready", "published_at_utc": datetime.now(UTC).isoformat(),
             "writer_stop_evidence": str(args.writer_stop_evidence), "normal_backend": "sqlserver"}
    save_state(connection, "baseline", value)
    connection.commit()
    args.publish_env_file.parent.mkdir(parents=True, exist_ok=True)
    with args.publish_env_file.open("x", encoding="utf-8") as output:
        output.write(args.runtime_env_file.read_text(encoding="utf-8") + "JRA_SRB_RESULTS_STORAGE=sqlserver\n")
    return {"status": "ready", "published_at_utc": value["published_at_utc"],
            "runtime_env_file": str(args.publish_env_file), "source_cutoff": value["verified_at_utc"]}


def export_recovery(connection, args) -> dict:
    """停止したSQL writerの全運用行を新規SQLite回収ファイルへ可逆にexportする。"""
    if args.recovery_path is None or args.recovery_path.exists():
        raise ValueError("未使用のrecovery出力パスを明示してください")
    path = args.recovery_path.with_suffix(args.recovery_path.suffix + ".partial")
    if path.exists():
        raise ValueError("未完了の回収ファイルが存在します。先に証跡を確認してください")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    target = sqlite3.connect(path)
    counts = {}
    try:
        command(connection, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        for name, table in TABLES.items():
            columns = [column["name"] for column in table["columns"]]
            definitions = ",".join(f'"{column["name"]}" {column["type"]}' for column in table["columns"])
            target.execute(f'CREATE TABLE "{name}"({definitions})')
            select = ",".join(f"[{column}]" for column in columns)
            cursor = execute(connection, f"SELECT __api_rowid,{select} FROM api_runtime.[{name}] ORDER BY __api_rowid")
            insert = f'INSERT INTO "{name}"(rowid,' + ",".join(f'"{column}"' for column in columns) + ") VALUES(" + ",".join("?" for _ in range(len(columns) + 1)) + ")"
            count = 0
            while rows := cursor.fetchmany(10000):
                target.executemany(insert, [tuple(row) for row in rows])
                count += len(rows)
            cursor.close()
            if target.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] != count:
                raise ValueError("recovery exportの件数が一致しません")
            counts[name] = count
            target.commit()
        audit_tables = {
            "write_receipts": ("request_sha256", "operation,race_id,payload_json", "received_at_utc"),
            "request_keys": ("key_sha256", "request_fingerprint", "received_at_utc"),
            "storage_state": ("state_key", "value_json", "updated_at_utc"),
        }
        for name, (key, fields, timestamp) in audit_tables.items():
            cursor = execute(connection, f"SELECT ROW_NUMBER() OVER(ORDER BY [{key}]),[{key}],{fields},CONVERT(nvarchar(40),[{timestamp}],127) AS [{timestamp}] FROM api_runtime.[{name}] ORDER BY [{key}]")
            columns = [column[0] for column in cursor.description][1:]
            target.execute(f'CREATE TABLE "sql_{name}"(' + ",".join(f'"{column}"' for column in columns) + ")")
            count = 0
            while rows := cursor.fetchmany(10000):
                target.executemany(f'INSERT INTO "sql_{name}"(rowid,' + ",".join(f'"{column}"' for column in columns) + ") VALUES(" + ",".join("?" for _ in range(len(columns) + 1)) + ")", [tuple(row) for row in rows])
                count += len(rows)
            cursor.close()
            counts["sql_" + name] = count
            target.commit()
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("recovery exportのSQLite整合性が確認できません")
    finally:
        target.close()
        connection.rollback()
    path.replace(args.recovery_path)
    return {"path": str(args.recovery_path), "counts": counts,
            "status": "exported_for_recovery", "requires_writer_stopped": True}


def verify_table(connection, table: dict, snapshot: int) -> int:
    """source rowidで全業務列のNULLとバイト値を照合し、対象版の件数を返す。"""
    name, source = table["name"], table["source"]
    source_name = f"[{source['schema']}].[{source['table']}]"
    target_name = f"[api_runtime].[{name}]"
    columns = [column["name"] for column in table["columns"]]
    differences = []
    for column in columns:
        a, b = f"s.[{column}]", f"t.[{column}]"
        differences.append(f"({a} IS NULL AND {b} IS NOT NULL) OR ({a} IS NOT NULL AND {b} IS NULL) OR CONVERT(varbinary(max),{a})<>CONVERT(varbinary(max),{b})")
    count = int(scalar(connection, f"SELECT COUNT_BIG(*) FROM {source_name} WHERE __migration_source_snapshot_id=?", (snapshot,)))
    target_count = int(scalar(connection, f"SELECT COUNT_BIG(*) FROM {target_name}"))
    mismatch = scalar(connection,
        f"SELECT TOP(1) 1 FROM {source_name} s FULL JOIN {target_name} t ON t.__api_rowid=s.__migration_source_rowid "
        "AND s.__migration_source_snapshot_id=? WHERE (s.__migration_source_snapshot_id=? OR s.__migration_source_snapshot_id IS NULL) "
        "AND (s.__migration_source_rowid IS NULL OR t.__api_rowid IS NULL OR " + " OR ".join(differences) + ")",
        (snapshot, snapshot))
    if target_count != count or mismatch:
        raise ValueError(f"seed照合不一致: {name}")
    return count


def seed(connection) -> dict:
    """採用済みSQLのAPI業務行だけを運用領域へ移し、元表は保持する。"""
    if not state(connection, "schema"):
        raise ValueError("先にschemaを明示適用してください")
    baseline = state(connection, "baseline")
    if baseline and baseline.get("status") == "ready":
        raise ValueError("通常writer開始可能なbaselineは再seedできません")
    sources = current_sources(connection)
    counts = {}
    for name, table in TABLES.items():
        if "source" not in table:
            continue
        source = table["source"]
        snapshot = sources[source["key"]]
        target = f"[api_runtime].[{name}]"
        columns = ",".join(f"[{column['name']}]" for column in table["columns"])
        if not scalar(connection, f"SELECT TOP(1) 1 FROM {target}"):
            command(connection, f"SET IDENTITY_INSERT {target} ON")
            command(connection,
                f"INSERT {target}(__api_rowid,__seed_source_snapshot_id,{columns}) "
                f"SELECT __migration_source_rowid,__migration_source_snapshot_id,{columns} "
                f"FROM [{source['schema']}].[{source['table']}] WHERE __migration_source_snapshot_id=?", (snapshot,))
            command(connection, f"SET IDENTITY_INSERT {target} OFF")
        counts[name] = verify_table(connection, table, snapshot)
        save_state(connection, "seed_progress", {"sources": sources, "verified_tables": counts})
        connection.commit()
    if current_sources(connection) != sources:
        raise ValueError("seed中に採用snapshotが変更されました")
    value = {"version": CONTRACT["version"], "status": "seed_verified", "sources": sources,
             "counts": counts, "verified_at_utc": datetime.now(UTC).isoformat()}
    save_state(connection, "baseline", value)
    connection.commit()
    return value


def provision_logins(connection, args) -> dict:
    """既存loginへ触れず、運用schemaだけを使えるreader/writerを新設する。"""
    if args.runtime_env_file is None:
        raise ValueError("秘密保存先--runtime-env-fileが必要です")
    if args.runtime_env_file.exists():
        raise ValueError("既存の秘密設定ファイルを上書きしません")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{1,80}", args.login_prefix):
        raise ValueError("login prefixが不正です")
    names = [args.login_prefix + suffix for suffix in ("_reader", "_writer")]
    if any(scalar(connection, "SELECT SUSER_ID(?)", (name,)) for name in names):
        raise ValueError("対象loginは既に存在します")
    passwords = [secrets.token_urlsafe(40) + "aA1!" for _ in names]
    for name, password, role in zip(names, passwords, ("jra_api_reader", "jra_api_writer"), strict=True):
        command(connection, f"CREATE LOGIN [{name}] WITH PASSWORD=N'{password}', CHECK_POLICY=ON, DEFAULT_DATABASE=[jra_unified]")
        command(connection, f"CREATE USER [{name}] FOR LOGIN [{name}]")
        command(connection, f"ALTER ROLE [{role}] ADD MEMBER [{name}]")
    lines = ["JRA_SRB_STORAGE_BACKEND=sqlserver", f"JRA_SRB_SQLSERVER_DATABASE={args.database}"]
    for role, name, password in zip(("READER", "WRITER"), names, passwords, strict=True):
        lines.append(f"JRA_SRB_SQLSERVER_{role}_CONNECTION_STRING=Server={args.server};Database={args.database};UID={name};PWD={{{password}}};Encrypt=yes;TrustServerCertificate=yes;")
    args.runtime_env_file.parent.mkdir(parents=True, exist_ok=True)
    with args.runtime_env_file.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    connection.commit()
    return {"logins": names, "roles": ["jra_api_reader", "jra_api_writer"], "runtime_env_file": str(args.runtime_env_file)}


def cell_bytes(value) -> bytes:
    """既存取込typed-row-v1と同じ型・長さ付き表現でSQLite実値を表す。"""
    if value is None:
        return b"N"
    if isinstance(value, int):
        return b"I" + struct.pack(">q", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("非有限REALは移行できません")
        return b"F" + struct.pack(">d", value)
    if isinstance(value, str):
        payload, tag = value.encode("utf-8"), b"T"
    else:
        payload, tag = bytes(value), b"B"
    return tag + struct.pack(">Q", len(payload)) + payload


def row_digest(names, values) -> bytes:
    """元列順・列名・型付き値を既存移送と同じSHA-256で照合する。"""
    digest = hashlib.sha256(b"typed-row-v1")
    for name, value in zip(names, values, strict=True):
        digest.update(cell_bytes(name))
        digest.update(cell_bytes(value))
    return digest.digest()


def file_state(path: Path) -> list:
    """sourceとWALの変更を検知するため、実体のサイズと更新時刻を記録する。"""
    result = []
    for item in (path, Path(str(path) + "-wal")):
        stat = item.stat() if item.exists() else None
        result.append({"path": str(item.resolve()), "size": stat.st_size if stat else None,
                       "mtime_ns": stat.st_mtime_ns if stat else None})
    return result


def sync_sqlite(connection, args) -> dict:
    """停止した旧writerの最終差分だけを運用領域へ適用し、旧DBをread-onlyで保持する。

    Notes:
        通常writer公開後は実行不可。既存移送の型付き行SHAを比較の基準とし、
        変更行だけを短いtable単位のtransactionで反映する。全量再投入をしない。
    """
    baseline = state(connection, "baseline")
    if baseline is None or baseline.get("status") not in {"seed_verified", "final_sqlite_verified"}:
        raise ValueError("停止済みwriterのseed_verified状態でだけ最終差分を適用できます")
    paths = {"analysis-current": args.analysis_sqlite, "jobs-current": args.jobs_sqlite}
    if any(path is None for path in paths.values()):
        raise ValueError("最終analysis/jobs SQLiteの両パスを明示してください")
    if scalar(connection, "SELECT COUNT_BIG(*) FROM api_runtime.write_receipts"):
        raise ValueError("運用領域に通常APIの受領履歴があり、最終SQLite同期は許可できません")
    sources = baseline["sources"]
    report = {}
    source_states = {}
    for source_key, path in paths.items():
        before = file_state(path)
        source_db = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            source_db.execute("BEGIN")
            for name, table in TABLES.items():
                if table.get("source", {}).get("key") != source_key:
                    continue
                snapshot = sources[source_key]
                source = table["source"]
                catalog = scalar(connection, "SELECT schema_json FROM ops.source_table WHERE source_snapshot_id=? AND source_table_name=?",
                                 (snapshot, source["table"]))
                names = [column["name"] for column in json.loads(catalog)["columns"]]
                sqlite_names = [row[1] for row in source_db.execute(f'PRAGMA table_info("{name}")')]
                if set(names) != set(sqlite_names) or set(names) != {column["name"] for column in table["columns"]}:
                    raise ValueError(f"最終SQLiteと契約の列が不一致: {name}")
                cursor = execute(connection,
                    f"SELECT __migration_source_rowid,__migration_source_row_sha256 FROM [{source['schema']}].[{source['table']}] WHERE __migration_source_snapshot_id=?",
                    (snapshot,))
                hashes = {}
                while rows := cursor.fetchmany(10000):
                    hashes.update((int(row[0]), bytes(row[1])) for row in rows)
                cursor.close()
                quoted = ",".join(f'"{column}"' for column in names)
                changed = []
                total = 0
                logical = hashlib.sha256()
                for row in source_db.execute(f'SELECT rowid,{quoted} FROM "{name}" ORDER BY rowid'):
                    rowid, values = int(row[0]), tuple(row[1:])
                    digest = row_digest(names, values)
                    logical.update(cell_bytes(rowid))
                    logical.update(digest)
                    total += 1
                    if hashes.pop(rowid, None) != digest:
                        changed.append((rowid, values, digest))
                target = f"[api_runtime].[{name}]"
                remove_ids = [*hashes, *(row[0] for row in changed)]
                for start in range(0, len(remove_ids), 500):
                    batch = remove_ids[start:start + 500]
                    command(connection, f"DELETE FROM {target} WHERE __api_rowid IN (" + ",".join("?" for _ in batch) + ")", batch)
                if changed:
                    columns = ",".join(f"[{column}]" for column in names)
                    command(connection, f"SET IDENTITY_INSERT {target} ON")
                    insert = f"INSERT {target}(__api_rowid,{columns}) VALUES(" + ",".join("?" for _ in range(len(names) + 1)) + ")"
                    cursor = connection.cursor()
                    try:
                        cursor.executemany(insert, [(rowid, *values) for rowid, values, digest in changed])
                    finally:
                        cursor.close()
                    command(connection, f"SET IDENTITY_INSERT {target} OFF")
                    for rowid, values, expected in changed:
                        cursor = execute(connection, f"SELECT {columns} FROM {target} WHERE __api_rowid=?", (rowid,))
                        actual = cursor.fetchone()
                        cursor.close()
                        if actual is None or row_digest(names, actual) != expected:
                            raise ValueError(f"最終差分の全値読戻し不一致: {name}")
                if scalar(connection, f"SELECT COUNT_BIG(*) FROM {target}") != total:
                    raise ValueError(f"最終差分の件数不一致: {name}")
                report[name] = {"rows": total, "changed_or_inserted": len(changed), "deleted": len(hashes),
                                "logical_sha256": logical.hexdigest()}
                save_state(connection, "final_sqlite_progress", report)
                connection.commit()
                print(json.dumps({"event": "final_sqlite_table_verified", "table": name, **report[name]}), flush=True)
            source_db.rollback()
        finally:
            source_db.close()
        after = file_state(path)
        if before != after:
            raise ValueError("最終差分の採取中に旧SQLiteが変更されました。writer停止を再確認してください")
        source_states[source_key] = after
    value = {**baseline, "status": "final_sqlite_verified", "final_sqlite": report,
             "source_files": source_states, "verified_at_utc": datetime.now(UTC).isoformat()}
    save_state(connection, "baseline", value)
    connection.commit()
    return value


def main() -> int:
    """明示された管理段階だけを実行し、秘密を含まない監査結果を残す。"""
    parser = argparse.ArgumentParser(description="SQL Server API storage migration administrator")
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--admin-user", default="jra_owner")
    parser.add_argument("--admin-secret-name", default="JRA_SQLSERVER_OWNER_PASSWORD")
    parser.add_argument("--admin-secrets-file", type=Path, required=True)
    parser.add_argument("--action", choices=("plan", "apply-schema", "apply-receipts", "apply-request-keys", "seed", "provision-logins", "sync-sqlite", "publish", "export-recovery"), default="plan")
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--runtime-env-file", type=Path)
    parser.add_argument("--login-prefix", default="jra_srb_api")
    parser.add_argument("--analysis-sqlite", type=Path)
    parser.add_argument("--jobs-sqlite", type=Path)
    parser.add_argument("--publish-env-file", type=Path)
    parser.add_argument("--writer-stop-evidence", type=Path)
    parser.add_argument("--recovery-path", type=Path)
    args = parser.parse_args()
    connection = None
    report = {"action": args.action, "started_at_utc": datetime.now(UTC).isoformat()}
    try:
        connection = connect(args)
        result = {"plan": lambda: plan(connection), "apply-schema": lambda: apply_schema(connection), "apply-receipts": lambda: apply_receipts(connection),
                  "apply-request-keys": lambda: apply_request_keys(connection),
                  "seed": lambda: seed(connection), "provision-logins": lambda: provision_logins(connection, args),
                  "sync-sqlite": lambda: sync_sqlite(connection, args), "publish": lambda: publish(connection, args),
                  "export-recovery": lambda: export_recovery(connection, args)}[args.action]()
        report.update({"status": "succeeded", "result": result})
        code = 0
    except Exception as error:
        if connection is not None:
            connection.rollback()
        report.update({"status": "failed", "error_type": type(error).__name__})
        code = 1
    finally:
        if connection is not None:
            connection.close()
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"action": args.action, "status": report["status"], "audit_output": str(args.audit_output),
                      "error_type": report.get("error_type")}, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
