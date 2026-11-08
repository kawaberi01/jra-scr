"""概要: 明示migrationに対応するSQL Server業務列・索引契約を読み取る。
作成日: 2026-10-15
入力: 同梱のsqlserver_runtime_schema.json。
出力: 読取専用のテーブル契約。
実行例: uv run python -c "from jra_srb.sqlserver_schema import TABLES; print(len(TABLES))"
注意事項: DB接続・DDL実行は行わない。
"""

import json
from importlib.resources import files


CONTRACT = json.loads(files("jra_srb").joinpath("config/sqlserver_runtime_schema.json").read_text(encoding="utf-8"))
TABLES = {table["name"]: table for table in CONTRACT["tables"]}
ANALYSIS_TABLES = tuple(name for name, table in TABLES.items() if table.get("source", {}).get("key") == "analysis-current")
