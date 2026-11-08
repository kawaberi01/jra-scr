"""概要: 現行StoreのDDLと確認済みSQLインベントリからAPI運用schemaを生成する。
作成日: 2026-10-15
入力: srcのSQLite DDL定義、SQL Serverの読取専用インベントリJSON。
出力: 版管理するSQL migrationと業務列・キーのJSON契約。
実行例: uv run python tools/build_sqlserver_runtime_schema.py
注意事項: SQLもSQLiteも開かない。生成物はレビュー後に管理者が明示適用する。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import sqlglot
from sqlglot import exp


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "api_runtime"


def literal_schema(path: Path, class_name: str, method: str) -> list[exp.Expression]:
    """対象初期化メソッドにある文字列DDLを構文解析だけで取り出す。"""
    module = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    function = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method)
    statements = []
    for node in ast.walk(function):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "create table" in node.value.lower():
            statements.extend(sqlglot.parse(node.value, read="sqlite"))
    return statements


def table_contract(create: exp.Create) -> dict:
    """列・nullable・既定値・業務キーを失わずStore定義から抽出する。"""
    result = {"name": create.this.this.name, "columns": [], "primary_key": [], "unique": [], "indexes": [], "foreign_keys": []}
    for node in create.this.expressions:
        if isinstance(node, exp.ColumnDef):
            constraints = [item.kind for item in node.constraints]
            kind = node.kind.sql(dialect="sqlite").lower()
            column = {"name": node.name, "type": kind,
                      "nullable": not any(isinstance(item, exp.NotNullColumnConstraint) for item in constraints)}
            defaults = [item.this.sql(dialect="sqlite") for item in constraints if isinstance(item, exp.DefaultColumnConstraint)]
            if defaults:
                column["default"] = defaults[0]
            result["columns"].append(column)
            if any(isinstance(item, exp.PrimaryKeyColumnConstraint) for item in constraints):
                result["primary_key"].append(node.name)
            if any(isinstance(item, exp.UniqueColumnConstraint) for item in constraints):
                result["unique"].append([node.name])
        elif isinstance(node, exp.PrimaryKey):
            result["primary_key"] = [item.name for item in node.expressions]
        elif isinstance(node, exp.UniqueColumnConstraint):
            result["unique"].append([item.name for item in node.this.expressions])
        elif isinstance(node, exp.ForeignKey):
            reference = node.args["reference"]
            result["foreign_keys"].append({"columns": [item.name for item in node.expressions],
                                           "parent_table": reference.this.this.name,
                                           "parent_columns": [item.name for item in reference.this.expressions]})
    return result


def migration_sql(tables: list[dict]) -> str:
    """業務キーと探索用hash索引を持つ運用表の追加DDLを生成する。"""
    statements = [
        "-- 概要: API用の通常writer領域だけを追加する。既存移送表は変更しない。",
        "-- 作成日: 2026-10-15。入力: 確認済み業務列契約。出力: api_runtime schema。",
        "-- 実行例: 管理CLIから明示apply。注意事項: jra_unified限定、seedと採用確認が別途必要。",
        "IF DB_NAME() <> N'jra_unified' THROW 51000, 'Unexpected database', 1;",
        "SET XACT_ABORT ON;",
        "IF SCHEMA_ID(N'api_runtime') IS NULL EXEC(N'CREATE SCHEMA [api_runtime] AUTHORIZATION [dbo]');",
        "GO",
        "IF OBJECT_ID(N'api_runtime.storage_state') IS NULL CREATE TABLE [api_runtime].[storage_state] (",
        " [state_key] nvarchar(128) NOT NULL PRIMARY KEY, [value_json] nvarchar(max) NOT NULL,",
        " [updated_at_utc] datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME());",
        "GO",
        "IF DATABASE_PRINCIPAL_ID(N'jra_api_reader') IS NULL CREATE ROLE [jra_api_reader];",
        "IF DATABASE_PRINCIPAL_ID(N'jra_api_writer') IS NULL CREATE ROLE [jra_api_writer];",
        "GRANT SELECT ON OBJECT::[api_runtime].[storage_state] TO [jra_api_reader];",
        "GRANT SELECT ON OBJECT::[api_runtime].[storage_state] TO [jra_api_writer];",
        "GO",
    ]
    for table in tables:
        name = table["name"]
        definitions = [" [__api_rowid] bigint IDENTITY(1,1) NOT NULL PRIMARY KEY",
                       " [__seed_source_snapshot_id] bigint NULL"]
        for column in table["columns"]:
            kind = {"text": "nvarchar(max) COLLATE Latin1_General_100_BIN2", "integer": "bigint",
                    "real": "float(53)", "blob": "varbinary(max)"}[column["type"]]
            default = " DEFAULT " + column["default"] if "default" in column else ""
            definitions.append(f" [{column['name']}] {kind} {'NULL' if column['nullable'] else 'NOT NULL'}{default}")
        for column in table["hash_columns"]:
            definitions.append(f" [__hash_{column}] AS CONVERT(binary(32), HASHBYTES('SHA2_256', [{column}])) PERSISTED")
        statements.append(f"IF OBJECT_ID(N'{SCHEMA}.{name}') IS NULL BEGIN\nCREATE TABLE [{SCHEMA}].[{name}] (\n" + ",\n".join(definitions) + "\n);")
        keys = ([table["primary_key"]] if table["primary_key"] else []) + table["unique"]
        for index, key in enumerate(keys):
            columns = ", ".join(f"[{'__hash_' if item in table['hash_columns'] else ''}{item}]" for item in key)
            nonnull = " AND ".join(f"[{item}] IS NOT NULL" for item in key)
            statements.append(f"CREATE UNIQUE INDEX [UX_{name}_{index}] ON [{SCHEMA}].[{name}] ({columns}) WHERE {nonnull};")
        for index, key in enumerate(table["indexes"]):
            columns = ", ".join(f"[{'__hash_' if item in table['hash_columns'] else ''}{item}]" for item in key)
            statements.append(f"CREATE INDEX [IX_{name}_{index}] ON [{SCHEMA}].[{name}] ({columns});")
        statements += ["END;", f"GRANT SELECT ON OBJECT::[{SCHEMA}].[{name}] TO [jra_api_reader];",
                       f"GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[{SCHEMA}].[{name}] TO [jra_api_writer];", "GO"]
    return "\n".join(statements) + "\n"


def main() -> None:
    """現SQLの列対応を検査してから、再現可能な契約とmigrationを生成する。"""
    inventory = json.loads((ROOT / ".workstate/jra-srb/sqlserver-api-cutover/sqlserver-inventory.json").read_text(encoding="utf-8"))
    old_inventory = json.loads(Path("D:/develop/jra-van-data/data/audits/sqlserver2022-api-access-inventory-20261014.json").read_text(encoding="utf-8"))
    mapping = {source["source_table_name"]: (item["target_schema"], item["target_table"])
               for item in old_inventory["catalog_mappings"] for source in item["sources"]
               if source["source_key"] in {"analysis-current", "jobs-current"}}
    statements = literal_schema(ROOT / "src/jra_srb/analysis_store.py", "AnalysisSQLiteStore", "init_db")
    tables = [table_contract(stmt) for stmt in statements if isinstance(stmt, exp.Create) and stmt.kind == "TABLE"]
    for stmt in statements:
        if isinstance(stmt, exp.Create) and stmt.kind == "INDEX":
            index = stmt.this
            table = next(item for item in tables if item["name"] == index.args["table"].name)
            table["indexes"].append([column.this.name for column in index.args["params"].args["columns"]])
    tables += [table_contract(stmt) for stmt in literal_schema(ROOT / "src/jra_srb/jobs.py", "ResultCollectionJobRegistry", "_init_db") if isinstance(stmt, exp.Create) and stmt.kind == "TABLE"]
    tables += [table_contract(stmt) for stmt in literal_schema(ROOT / "src/jra_srb/cache.py", "SQLiteTTLCache", "_init_db") if isinstance(stmt, exp.Create) and stmt.kind == "TABLE"]
    exports = [table_contract(stmt) for stmt in literal_schema(ROOT / "src/jra_srb/batch.py", "SQLiteRaceResultStorage", "_init_db") if isinstance(stmt, exp.Create) and stmt.kind == "TABLE"][0]
    exports["name"] = "stored_race_results"
    exports["columns"].insert(0, {"name": "storage_namespace", "type": "text", "nullable": False})
    exports["primary_key"] = ["storage_namespace", "race_id"]
    exports["indexes"] = [["storage_namespace", "race_date", "course"]]
    tables.append(exports)
    next(table for table in tables if table["name"] == "odds_snapshots")["indexes"].append(
        ["race_id", "bet_type", "odds_timing", "fetched_at"]
    )
    joins = {"race_id", "jra_race_id", "netkeiba_race_id", "snapshot_id", "card_snapshot_id", "prediction_id", "evaluation_id", "bet_record_id", "run_id", "import_id"}
    for table in tables:
        indexed = set(table["primary_key"]) | joins
        for key in table["unique"] + table["indexes"]:
            indexed.update(key)
        table["hash_columns"] = [c["name"] for c in table["columns"] if c["type"] == "text" and c["name"] in indexed]
        first_keys = {key[0] for key in table["indexes"] + table["unique"] + [table["primary_key"]] if key}
        table["indexes"] += [[column] for column in table["hash_columns"] if column in joins and column not in first_keys]
        if table["name"] in mapping:
            schema, name = mapping[table["name"]]
            actual = {c["column_name"] for c in inventory["columns"] if c["schema_name"] == schema and c["table_name"] == name}
            missing = {c["name"] for c in table["columns"]} - actual
            if missing:
                raise ValueError(f"current SQL columns missing: {table['name']} {sorted(missing)}")
            table["source"] = {"schema": schema, "table": name, "key": "jobs-current" if name == "result_collection_jobs" else "analysis-current"}
    output = ROOT / "src/jra_srb/config/sqlserver_runtime_schema.json"
    output.write_text(json.dumps({"version": 1, "schema": SCHEMA, "tables": tables}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    directory = ROOT / "migrations/sqlserver"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "001_api_runtime.sql").write_text(migration_sql(tables), encoding="utf-8")
    rollback = [
        "-- 概要: 通常writer公開前だけに使える運用schemaのrollback。元表を変更しない。",
        "-- 作成日: 2026-10-15。入力: 本migrationの専用schema。出力: 追加schemaの削除。",
        "-- 実行例: API停止・未公開確認後に管理者が明示実行。注意事項: ready以後は禁止。",
        "IF DB_NAME() <> N'jra_unified' THROW 51000, 'Unexpected database', 1;",
        "IF EXISTS(SELECT 1 FROM api_runtime.storage_state WHERE state_key=N'baseline' AND JSON_VALUE(value_json,'$.status')=N'ready')",
        " THROW 51000, 'Export SQL-only changes before rollback after writer publication', 1;",
    ]
    rollback += [f"DROP TABLE [api_runtime].[{table['name']}];" for table in reversed(tables)]
    rollback[6:6] = [
        "IF OBJECT_ID(N'api_runtime.request_keys') IS NOT NULL DROP TABLE api_runtime.request_keys;",
        "IF OBJECT_ID(N'api_runtime.write_receipts') IS NOT NULL DROP TABLE api_runtime.write_receipts;",
    ]
    rollback += ["DROP TABLE [api_runtime].[storage_state];", "DROP SCHEMA [api_runtime];"]
    (directory / "001_rollback_before_writer.sql").write_text("\n".join(rollback) + "\n", encoding="utf-8")
    print(json.dumps({"version": 1, "tables": len(tables), "source_tables": sum("source" in table for table in tables)}))


if __name__ == "__main__":
    main()
