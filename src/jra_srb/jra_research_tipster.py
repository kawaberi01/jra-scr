"""概要: 移送済みSQLの固定版から予想家由来研究の内容履歴とワイド払戻を読む。
作成日: 2026-10-17
入力: configs/research/tipster_history_sql_v1.json、研究専用reader接続。
出力: メモリ内の履歴行・払戻対応、元データを含まない実行証跡。
実行例: uv run --extra ml python scripts/run_jra_tipster_history.py
注意事項: SELECTのみ。SQLite・HTTP・旧JSONLへのfallbackなし。特徴計算・学習は呼出し側で行う。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from .jra_research_artifacts import ROOT, RunArtifacts
from .jra_research_contracts import ResearchError, canonical_json, digest
from .jra_research_reader import ResearchReader
from .jra_research_resources import check_memory


DEFAULT_CONFIG = ROOT / "configs/research/tipster_history_sql_v1.json"
TABLES = {
    "live.netkeiba_race_results": ("netkeiba_race_id", "race_date", "course", "race_no", "surface", "distance", "race_laps_json"),
    "live.netkeiba_result_entries": ("netkeiba_race_id", "horse_no", "horse_name", "sex_age", "rank", "corner_order", "final_3f"),
    "live.netkeiba_payouts": ("netkeiba_race_id", "bet_type", "combination", "payout"),
}
COURSES = dict(zip(("中山", "京都", "小倉", "東京", "阪神", "中京", "福島", "新潟", "函館", "札幌"),
                   ("nakayama", "kyoto", "kokura", "tokyo", "hanshin", "chukyo", "fukushima", "niigata", "hakodate", "sapporo"), strict=True))


@dataclass(frozen=True)
class TipsterHistoryConfig:
    """履歴SQL入力の固定版・期間・物理上限を保持する。"""

    raw: dict

    @property
    def snapshot(self) -> int:
        """設定で明示したanalysis固定版を返す。"""
        return self.raw["source_policy"]["snapshot_id"]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG):
        """未知設定・日付の逆転・不正な読取上限を拒否する。"""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if set(raw) != {"schema_version", "source_policy", "date_from", "date_through", "limits"}:
                raise ValueError("keys")
            if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
                raise ValueError("version")
            policy = raw["source_policy"]
            if (set(policy) != {"source_key", "snapshot_id"} or policy["source_key"] != "analysis-current"
                    or type(policy["snapshot_id"]) is not int or policy["snapshot_id"] <= 0):
                raise ValueError("source")
            for key in ("date_from", "date_through"):
                if date.fromisoformat(raw[key]).isoformat() != raw[key]:
                    raise ValueError("date")
            if raw["date_from"] > raw["date_through"]:
                raise ValueError("date_order")
            limits = raw["limits"]
            maximums = {"fetch_rows": 10000, "query_timeout_seconds": 90,
                        "memory_bytes": 2147483648, "max_candidate_rows": 1500000}
            if set(limits) != set(maximums):
                raise ValueError("limits")
            if any(type(limits[k]) is not int or not 0 < limits[k] <= maximums[k] for k in maximums):
                raise ValueError("limit")
            return cls(raw)
        except (OSError, ValueError, TypeError, KeyError):
            raise ResearchError("invalid_tipster_history_config", 2) from None


class TipsterHistoryReader(ResearchReader):
    """既存研究専用接続でnetkeiba移送3表だけを分割読取する。"""

    def preflight(self) -> dict:
        """接続権限・固定版・必要列・一意keyset索引を確認する。"""
        identity = self._small("tipster:identity", "SELECT DB_NAME() database_name,IS_SRVROLEMEMBER('sysadmin') sysadmin,IS_ROLEMEMBER('db_owner') db_owner,IS_ROLEMEMBER('db_datawriter') db_datawriter,IS_ROLEMEMBER('db_ddladmin') db_ddladmin")[0]
        if identity["database_name"] != "jra_unified" or any(identity[k] != 0 for k in ("sysadmin", "db_owner", "db_datawriter", "db_ddladmin")):
            raise ResearchError("unexpected_database_or_privilege", 3)
        for table in (*TABLES, "ops.source_database", "ops.source_snapshot"):
            for permission in ("SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL"):
                rows = self._small("tipster:permission", "SELECT HAS_PERMS_BY_NAME(?,'OBJECT',?) permitted", (table, permission))
                if rows[0]["permitted"] != int(permission == "SELECT"):
                    raise ResearchError("permission_contract_failed", 3, table=table, permission=permission)
        source = self._small("tipster:source", "SELECT d.source_key,s.status,s.source_snapshot_id,s.schema_catalog_sha256 FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (self.config.snapshot,))
        if len(source) != 1 or source[0]["source_key"] != "analysis-current" or source[0]["status"] != "verified":
            raise ResearchError("unverified_source", 3)
        schema = []
        for table, fields in TABLES.items():
            columns = self._small("tipster:columns", "SELECT name FROM sys.columns WHERE object_id=OBJECT_ID(?)", (table,))
            if not set((*fields, "__migration_source_rowid", "__migration_source_snapshot_id")) <= {c["name"] for c in columns}:
                raise ResearchError("missing_schema_columns", 3, table=table)
            indexes = self._small("tipster:indexes", "SELECT i.name,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND i.is_unique=1 AND i.is_disabled=0 AND i.is_hypothetical=0 AND i.has_filter=0 AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
            grouped = defaultdict(list)
            for row in indexes:
                grouped[row["name"]].append(row["column_name"])
            if ["__migration_source_snapshot_id", "__migration_source_rowid"] not in grouped.values():
                raise ResearchError("keyset_requires_unique_index", 3, table=table)
            schema.append({"table": table, "columns": columns, "indexes": indexes})
        self.report = {"source": source[0], "schema_digest": digest(schema), "read_consistency": "chunked_unproven",
                       "availability": "retrospective_research_only", "identity_method": "legacy_name_birthyear_sex"}
        return self.report

    def rows(self, table: str):
        """許可3表を固定snapshotと一意rowidで有界に読む。"""
        if table not in TABLES:
            raise ResearchError("invalid_tipster_table", 3)
        fields = ("__migration_source_rowid", *TABLES[table])
        previous, seen = None, 0
        stream = hashlib.sha256((table + "\n").encode())
        limits = self.config.raw["limits"]
        while True:
            size = min(limits["fetch_rows"], limits["max_candidate_rows"] - seen + 1)
            sql = "SELECT TOP (?) " + ",".join(f"[{k}]" for k in fields) + f" FROM {table} WHERE __migration_source_snapshot_id=?"
            params = [size, self.config.snapshot]
            if previous is not None:
                sql += " AND __migration_source_rowid>?"
                params.append(previous)
            sql += " ORDER BY __migration_source_rowid"
            with self._cursor("tipster:keyset:" + table, sql, params) as cursor:
                batch = cursor.fetchmany(size)
            if not batch:
                self.report.setdefault("table_digests", {})[table] = stream.hexdigest()
                return
            check_memory(limits["memory_bytes"])
            for values in batch:
                row = dict(zip(fields, values, strict=True))
                stream.update((canonical_json(row) + "\n").encode())
                identifier = row.pop("__migration_source_rowid")
                if identifier is None or previous is not None and identifier <= previous:
                    raise ResearchError("invalid_keyset_rowid", 3, table=table)
                seen += 1
                self.scan_rows[table] = seen
                if seen > limits["max_candidate_rows"]:
                    raise ResearchError("scan_row_limit", 4, table=table)
                previous = identifier
                yield row


def read_tipster_history(config_path: str | Path = DEFAULT_CONFIG, *, provenance: dict | None = None):
    """SQL履歴とワイド精算をメモリ結合し、非秘密runを保存する。

    Args:
        config_path: 固定版・期間・上限の設定。
        provenance: 指定時は版・利用列digest・run IDを格納する。元データは格納しない。
    Returns:
        旧内容変換へ渡す履歴行、レース別払戻辞書、件数監査。
    Raises:
        ResearchError: SQL失敗、重複、対象範囲内の孤児、不正精算。
    Notes:
        生データをファイル保存しない。固定版の行digestを記録するが、原子的snapshotや当時取得を保証しない。
    """
    config = TipsterHistoryConfig.load(config_path)
    artifacts = RunArtifacts(config.raw, "tipster-history-input")
    reader = TipsterHistoryReader(config)
    try:
        with reader:
            artifacts.write_json("preflight.json", reader.preflight())
            races, selected = {}, {}
            excluded_missing_date = 0
            for row in reader.rows("live.netkeiba_race_results"):
                key = row["netkeiba_race_id"]
                if key in races:
                    raise ResearchError("duplicate_key", 4, table="live.netkeiba_race_results")
                races[key] = row
                day = row["race_date"]
                if day is None:
                    excluded_missing_date += 1
                    continue
                if config.raw["date_from"] <= day <= config.raw["date_through"] and row["course"] in COURSES:
                    selected[key] = row
            raw, wide, seen = [], defaultdict(dict), set()
            for entry in reader.rows("live.netkeiba_result_entries"):
                rid = entry["netkeiba_race_id"]
                if rid not in races:
                    raise ResearchError("orphan_tipster_entry", 4)
                if rid not in selected:
                    continue
                key = rid, entry["horse_no"]
                if key in seen:
                    raise ResearchError("duplicate_key", 4, table="live.netkeiba_result_entries")
                seen.add(key)
                raw.append({**selected[rid], **entry})
            for payout in reader.rows("live.netkeiba_payouts"):
                rid = payout["netkeiba_race_id"]
                if rid not in races:
                    raise ResearchError("orphan_tipster_payout", 4)
                if rid not in selected or payout["bet_type"] != "wide":
                    continue
                pair = tuple(sorted(re.findall(r"\d+", str(payout["combination"])), key=int))
                if len(pair) != 2 or not payout["payout"]:
                    continue
                race = selected[rid]
                key = race["race_date"], COURSES[race["course"]], int(race["race_no"] or 0)
                value = int(payout["payout"])
                if pair in wide[key] and wide[key][pair] != value:
                    raise ResearchError("conflicting_wide_settlement", 4)
                wide[key][pair] = value
            audit = {"sql_history_races": len(selected), "sql_history_entry_rows": len(raw),
                     "sql_wide_races": len(wide), "sql_history_missing_date_excluded": excluded_missing_date}
            artifacts.write_json("coverage.json", {**audit, "scanned_rows": reader.scan_rows,
                                                   "source": reader.report, "query_count": len(reader.query_metrics)})
            artifacts.finish(input_digest=digest(reader.report["table_digests"]), overall_complete=False,
                             stage="history_input_only", sqlite_used=False, run_id_reference=artifacts.run_id)
            if provenance is not None:
                provenance.update(run_id=artifacts.run_id, input_digest=digest(reader.report["table_digests"]),
                                  source=reader.report["source"], date_from=config.raw["date_from"],
                                  date_through=config.raw["date_through"])
            return raw, wide, audit
    except ResearchError as error:
        artifacts.write_json("coverage.json", {"scanned_rows": reader.scan_rows, "queries": reader.query_metrics})
        artifacts.fail(error)
        raise
    except Exception as error:
        artifacts.write_json("coverage.json", {"scanned_rows": reader.scan_rows, "queries": reader.query_metrics})
        failure = ResearchError("tipster_history_failed", 4, error_type=type(error).__name__)
        artifacts.fail(failure)
        raise failure from None
