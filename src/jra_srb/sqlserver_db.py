"""概要: StoreのSQLを解析し、SQL Serverの独立した短いtransactionで実行する。
作成日: 2026-10-15
入力: SQL Server設定、既存Storeのパラメーター付きSQL、業務値。
出力: 名前と位置で参照可能な行、commitまたはrollback。
実行例: uv run pytest -q tests/test_sqlserver_storage.py
注意事項: 起動時DDL、SQLite接続、接続共有、SQL障害時のfallbackを行わない。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import lru_cache
import json
import re
from typing import Any

import mssql_python
import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel
from sqlglot.tokens import TokenType

from .storage_config import SqlServerSettings
from .sqlserver_schema import TABLES, CONTRACT


SCHEMA = "api_runtime"
SET_OPTIONS = (
    "SET NOCOUNT ON; SET XACT_ABORT ON; SET ANSI_NULLS ON; SET ANSI_PADDING ON; "
    "SET ANSI_WARNINGS ON; SET ARITHABORT ON; SET CONCAT_NULL_YIELDS_NULL ON; "
    "SET QUOTED_IDENTIFIER ON; SET NUMERIC_ROUNDABORT OFF;"
)


class SqlServerStorageError(RuntimeError):
    """接続文字列やDB業務値を含まない永続化エラーを表す。"""


class StorageRow(tuple):
    """SQLiteと同じ名前参照・位置参照・値の反復を提供する。"""

    def __new__(cls, values: Sequence[Any], names: Sequence[str]):
        """列順と名前を持つ不変な行を作る。"""
        row = super().__new__(cls, values)
        row._names = tuple(names)
        return row

    def keys(self) -> tuple[str, ...]:
        """dict(row)が使用する列名を返す。"""
        return self._names

    def __getitem__(self, key):
        """列名または位置を使って値を取り出す。"""
        if isinstance(key, str):
            key = self._names.index(key)
        return super().__getitem__(key)


class StorageResult:
    """connectionを閉じた後も読める、取得済みの小さな結果集合を保持する。"""

    def __init__(self, rows: Sequence[StorageRow] = (), rowcount: int = -1):
        """取得済み行と影響行数を保持する。"""
        self._rows = list(rows)
        self._offset = 0
        self.rowcount = rowcount

    def fetchone(self) -> StorageRow | None:
        """未読の次の行を返し、末尾ではNoneを返す。"""
        if self._offset >= len(self._rows):
            return None
        row = self._rows[self._offset]
        self._offset += 1
        return row

    def fetchall(self) -> list[StorageRow]:
        """未読の残りの行を返す。"""
        rows = self._rows[self._offset:]
        self._offset = len(self._rows)
        return rows

    def __iter__(self):
        """未読の行を列順を保って反復する。"""
        return iter(self.fetchall())


def _number_parameters(sql: str) -> str:
    """文字列リテラルを除く?へ番号を付け、方言変換後の引数順を追跡する。"""
    placeholders = [t for t in sqlglot.tokenize(sql, read="sqlite") if t.token_type == TokenType.PLACEHOLDER]
    for number, token in reversed(list(enumerate(placeholders))):
        sql = sql[:token.start] + f":__jra_p{number}" + sql[token.end + 1:]
    return sql


def _convert_node(node: exp.Expression) -> exp.Expression:
    """日付、NULLの並び、数値変換、無名の派生表を明示T-SQLへ変換する。"""
    if isinstance(node, exp.Anonymous) and node.name.lower() == "julianday":
        argument = node.expressions[0].sql(dialect="tsql")
        return sqlglot.parse_one(
            "DATEDIFF_BIG(millisecond, CONVERT(datetimeoffset, '1970-01-01T00:00:00+00:00'), "
            f"SWITCHOFFSET(TRY_CONVERT(datetimeoffset, {argument}, 127), '+00:00')) / 86400000.0 + 2440587.5",
            read="tsql",
        )
    if isinstance(node, exp.Length):
        argument = node.this.sql(dialect="tsql")
        return sqlglot.parse_one(f"LEN(CONVERT(nvarchar(max), {argument}) + N'#') - 1", read="tsql")
    if isinstance(node, exp.Cast) and isinstance(node.this, exp.Column) and node.this.name == "horse_no":
        if node.args["to"].this in {exp.DataType.Type.INT, exp.DataType.Type.BIGINT}:
            value = node.this.sql(dialect="tsql")
            text = f"LTRIM(CONVERT(nvarchar(max), {value}))"
            body = f"CASE WHEN LEFT({text},1) IN ('+','-') THEN SUBSTRING({text},2,2147483647) ELSE {text} END"
            digits = f"LEFT({body}, PATINDEX('%[^0-9]%', {body} + N'X') - 1)"
            signed = f"CASE WHEN LEFT({text},1)='-' THEN N'-' ELSE N'' END + {digits}"
            return sqlglot.parse_one(f"CASE WHEN {value} IS NULL THEN NULL ELSE COALESCE(TRY_CONVERT(bigint,{signed}),0) END", read="tsql")
    if isinstance(node, exp.Ordered) and isinstance(node.this, (exp.Is, exp.Not)):
        condition = node.this.sql(dialect="tsql")
        node.set("this", sqlglot.parse_one(f"CASE WHEN {condition} THEN 1 ELSE 0 END", read="tsql"))
    if isinstance(node, exp.Subquery) and not node.alias and isinstance(node.parent, (exp.From, exp.Join)):
        node.set("alias", exp.TableAlias(this=exp.to_identifier("_derived")))
    if isinstance(node, exp.Column) and node.name.lower() == "rowid":
        node.set("this", exp.to_identifier("__api_rowid", quoted=True))
    return node


def _render(tree: exp.Expression) -> str:
    """黙って機能を落とさずT-SQLを生成し、識別子を引用する。"""
    if isinstance(tree, exp.Union) and tree.args.get("limit"):
        for query in tree.find_all(exp.Select):
            query.set("expressions", [exp.alias_(item, f"_union_value_{index}") if isinstance(item, exp.Literal) else item
                                      for index, item in enumerate(query.expressions)])
    return tree.transform(_convert_node).sql(dialect="tsql", identify=True, unsupported_level=ErrorLevel.RAISE)


def _add_hash_predicates(tree: exp.Expression) -> None:
    """業務値の完全一致条件へhash索引条件を添え、大きな明細表の走査を避ける。"""
    aliases = {table.alias_or_name: table.name for table in tree.find_all(exp.Table)}
    direct_tables = list(aliases.values())
    for condition in list(tree.find_all(exp.EQ)):
        if isinstance(condition.parent, exp.Update) or isinstance(condition.parent, exp.OnConflict):
            continue
        left, right = condition.this, condition.expression
        if not isinstance(left, exp.Column):
            continue
        table_name = aliases.get(left.table) if left.table else (direct_tables[0] if len(set(direct_tables)) == 1 else None)
        if left.name not in TABLES.get(table_name, {}).get("hash_columns", []):
            continue
        if isinstance(right, exp.Column):
            right_table = aliases.get(right.table)
            if right.name not in TABLES.get(right_table, {}).get("hash_columns", []):
                continue
            hashed_right = right.copy()
            hashed_right.set("this", exp.to_identifier("__hash_" + right.name, quoted=True))
        elif isinstance(right, (exp.Placeholder, exp.Literal)) and not (isinstance(right, exp.Literal) and not right.is_string):
            hashed_right = sqlglot.parse_one(
                f"CONVERT(binary(32), HASHBYTES('SHA2_256', CONVERT(nvarchar(max), {right.sql(dialect='tsql')})))",
                read="tsql",
            )
        else:
            continue
        hashed_left = left.copy()
        hashed_left.set("this", exp.to_identifier("__hash_" + left.name, quoted=True))
        condition.replace(exp.and_(condition.copy(), exp.EQ(this=hashed_left, expression=hashed_right)))


@lru_cache(maxsize=512)
def compile_sql(sql: str, tables: tuple[str, ...]) -> tuple[str, tuple[int, ...]]:
    """許可したStoreのSQLだけをT-SQLへ変換し、引数の並び替えを返す。

    Args:
        sql: Store内部で組み立てたSQL。業務値は?で渡す。
        tables: 接続が利用できる通常テーブル名。

    Raises:
        ValueError: 複数文、DDL、許可外テーブル、未対応のupsertの場合。
    """
    if sql.strip().lower() == "pragma foreign_keys = on":
        return "", ()  # SQLではPRAGMAを使わず、親子契約を同じ接続内で検査する。
    statements = sqlglot.parse(_number_parameters(sql), read="sqlite")
    if len(statements) != 1 or not isinstance(statements[0], (exp.Query, exp.Insert, exp.Update, exp.Delete)):
        raise ValueError("only one Store SELECT/INSERT/UPDATE/DELETE statement is allowed")
    tree = statements[0]
    for table in tree.find_all(exp.Table):
        if table.name not in tables or table.db or table.catalog:
            raise ValueError("table is outside the runtime storage contract")
        table.set("db", exp.to_identifier(SCHEMA, quoted=True))
    if isinstance(tree, exp.Insert) and tree.args.get("conflict") is not None:
        conflict = tree.args["conflict"]
        schema = tree.this
        if not isinstance(schema, exp.Schema) or not isinstance(tree.expression, exp.Values):
            raise ValueError("upsert requires an explicit column list and VALUES")
        columns = [column.name for column in schema.expressions]
        rows = tree.expression.expressions
        if len(rows) != 1:
            raise ValueError("multi-row upsert must use executemany")
        table = schema.this
        target = table.name
        keys = [key.this.name for key in conflict.args.get("conflict_keys", [])]
        if not keys or any(key not in columns for key in keys):
            raise ValueError("upsert requires supplied conflict keys")
        types = {column["name"]: {"text": "nvarchar(max)", "integer": "bigint", "real": "float(53)", "blob": "varbinary(max)"}[column["type"]]
                 for column in TABLES[target]["columns"]}
        source = ", ".join(f"CAST({_render(value)} AS {types[name]}) AS [{name}]"
                           for name, value in zip(columns, rows[0].expressions, strict=True))
        terms = [f"[{target}].[{key}] = [excluded].[{key}]" for key in keys]
        terms += [f"[{target}].[__hash_{key}] = CONVERT(binary(32), HASHBYTES('SHA2_256', CONVERT(nvarchar(max), [excluded].[{key}])))"
                  for key in keys if key in TABLES.get(target, {}).get("hash_columns", [])]
        on = " AND ".join(terms)
        updates = ", ".join(_render(item) for item in conflict.expressions)
        rendered = (
            f"MERGE [{SCHEMA}].[{target}] WITH (HOLDLOCK) AS [{target}] "
            f"USING (SELECT {source}) AS [excluded] ON {on} "
            + (f"WHEN MATCHED THEN UPDATE SET {updates} " if updates else "")
            + "WHEN NOT MATCHED THEN INSERT (" + ", ".join(f"[{x}]" for x in columns)
            + ") VALUES (" + ", ".join(f"[excluded].[{x}]" for x in columns) + ");"
        )
    else:
        if isinstance(tree, (exp.Query, exp.Update, exp.Delete)):
            _add_hash_predicates(tree)
        rendered = _render(tree)
    indices = tuple(int(x) for x in re.findall(r":__jra_p(\d+)", rendered))
    return re.sub(r":__jra_p\d+", "?", rendered), indices


class SqlServerConnection:
    """1操作専用connectionを所有し、正常終了だけをcommitする。"""

    def __init__(self, settings: SqlServerSettings, tables: tuple[str, ...], *, read_only: bool = False):
        """指定roleで接続し、DB名と過大な権限を実接続で検査する。"""
        self.tables = tables
        self.read_only = read_only
        self._closed = False
        self._connection = None
        self._verified_parents = set()
        try:
            connection_string = settings.reader_connection_string if read_only else settings.writer_connection_string
            self._connection = mssql_python.connect(connection_string, autocommit=False)
            self._connection.timeout = settings.timeout_seconds
            self._raw(SET_OPTIONS)
            row = self._raw("SELECT DB_NAME(), IS_ROLEMEMBER('db_owner'), IS_SRVROLEMEMBER('sysadmin')").fetchone()
            if row is None or row[0] != settings.database or row[1] == 1 or row[2] == 1:
                raise SqlServerStorageError("unexpected database or privileged API login")
            baseline = self._raw("SELECT value_json FROM api_runtime.storage_state WHERE state_key=N'baseline'").fetchone()
            baseline_state = json.loads(baseline[0]) if baseline else {}
            if baseline_state.get("status") != "ready" or baseline_state.get("version") != CONTRACT["version"]:
                raise SqlServerStorageError("SQL Server baseline has not been verified")
        except Exception:
            self.close()
            raise SqlServerStorageError("SQL Server connection or role validation failed") from None

    def _raw(self, sql: str, params: Sequence[Any] = ()) -> StorageResult:
        """内部T-SQLを実行し、cursorを必ず閉じて行を返す。"""
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql, tuple(params))
            if cursor.description is None:
                return StorageResult(rowcount=cursor.rowcount)
            columns = [(index, column[0]) for index, column in enumerate(cursor.description) if not str(column[0]).startswith("__")]
            names = [name for _, name in columns]
            return StorageResult([StorageRow([row[index] for index, _ in columns], names) for row in cursor.fetchall()], cursor.rowcount)
        finally:
            cursor.close()

    def execute(self, sql: str, params: Sequence[Any] = (), *, hash_join: bool = False) -> StorageResult:
        """単一SQLを実行し、明示したreader SELECTだけにHASH JOINを指定する。

        Args:
            sql: 許可表だけを参照するStore内部SQL。
            params: 元SQL順のパラメーター。
            hash_join: 大きな履歴結合での反復全走査を避ける明示指定。

        Raises:
            SqlServerStorageError: readerの更新、reader SELECT以外へのhint指定、SQL実行失敗。
        """
        statement, indices = compile_sql(sql, self.tables)
        if not statement:
            return StorageResult()
        if hash_join:
            if not self.read_only or not statement.lstrip().upper().startswith("SELECT"):
                raise SqlServerStorageError("hash join requires a reader SELECT")
            statement = statement.rstrip(";") + " OPTION (HASH JOIN)"
        if self.read_only and not statement.lstrip().upper().startswith("SELECT"):
            raise SqlServerStorageError("write requested through SQL reader")
        if statement.lstrip().upper().startswith(("INSERT", "MERGE")):
            self._check_parent_keys(sql, params)
        try:
            return self._raw(statement, [params[index] for index in indices])
        except Exception:
            raise SqlServerStorageError("SQL Server storage operation failed") from None

    def _check_parent_keys(self, sql: str, params: Sequence[Any]) -> None:
        """元Storeの親子制約を、同じtransactionの親行ロックで維持する。"""
        tree = sqlglot.parse_one(_number_parameters(sql), read="sqlite")
        if not isinstance(tree, exp.Insert) or not isinstance(tree.this, exp.Schema):
            return
        table = TABLES.get(tree.this.this.name, {})
        if not table.get("foreign_keys"):
            return
        names = [column.name for column in tree.this.expressions]
        values = tree.expression.expressions[0].expressions
        for relation in table["foreign_keys"]:
            bound = []
            for column in relation["columns"]:
                value = values[names.index(column)]
                if not isinstance(value, exp.Placeholder):
                    raise ValueError("parent key must use a bound parameter")
                bound.append(params[int(value.this.removeprefix("__jra_p"))])
            if any(value is None for value in bound):
                continue
            identity = (relation["parent_table"], tuple(bound))
            if identity in self._verified_parents:
                continue
            predicates, arguments = [], []
            for column, value in zip(relation["parent_columns"], bound, strict=True):
                predicates.append(f"[{column}]=? AND [__hash_{column}]=CONVERT(binary(32),HASHBYTES('SHA2_256',CONVERT(nvarchar(max),?)))")
                arguments += [value, value]
            query = f"SELECT 1 FROM [{SCHEMA}].[{relation['parent_table']}] WITH (UPDLOCK,HOLDLOCK) WHERE " + " AND ".join(predicates)
            if self._raw(query, arguments).fetchone() is None:
                raise SqlServerStorageError("referenced parent row does not exist")
            self._verified_parents.add(identity)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        """同じtransaction内で複数行を保存し、途中失敗を全体へ伝える。"""
        for row in rows:
            self.execute(sql, row)

    def __enter__(self):
        """この操作だけが所有するtransactionを返す。"""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """成功時commit、失敗時rollbackを行い、例外を抑制せず接続を閉じる。"""
        try:
            if exc_type is None and not self.read_only:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self.close()

    def close(self) -> None:
        """未完了transactionを残さず接続を閉じる。複数回呼び出せる。"""
        if not self._closed and self._connection is not None:
            self._closed = True
            self._connection.close()
