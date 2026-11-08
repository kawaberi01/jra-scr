"""概要: 固定SQL版の単勝/ワイドを時点・精算検査後に旧R11の純計算へ渡す。
作成日: 2026-10-16
入力: R11非秘密JSON設定、研究専用reader接続、replay元runまたはscore対象ID。
出力: 新規共通runの契約・coverage・集計・入力digest。元行/市場全量は保存しない。
実行例: uv run python scripts/run_jra_research.py cross-market --config configs/research/cross_market_disagreement_sql_v1.json
注意事項: SELECT専用、各表各巡100万行/2巡上限。同時点未証明・精算不明を推測しない。
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from .jra_research_artifacts import RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, canonical_json, digest
from .jra_research_cross_market import (
    build_race_candidates, evaluate_candidates, select_candidates,
    VALUE_THRESHOLDS, INFORMATION_THRESHOLDS,
)
from .jra_research_reader import ResearchReader
from .jra_research_resources import check_memory
from .jra_research_runtime import _utc, _time_key
from .jra_history_dataset import COURSE_CODES
from .normalization import COURSE_ALIASES


FIELDS = {
    "live.races": ("race_id", "race_date", "race_no"),
    "live.netkeiba_race_results": ("netkeiba_race_id", "jra_race_id", "race_date", "course", "race_no", "source", "fetched_at"),
    "live.netkeiba_result_entries": ("netkeiba_race_id", "jra_race_id", "horse_no", "win_odds", "rank"),
    "live.netkeiba_odds_entries": ("netkeiba_race_id", "jra_race_id", "bet_type", "combination", "odds", "odds_min", "odds_max", "source", "fetched_at"),
    "live.netkeiba_payouts": ("netkeiba_race_id", "jra_race_id", "bet_type", "combination", "payout"),
}
CONTRACT = {"profile_id": "cross_market_disagreement_sql_v1", "year": 2025,
            "timing": "matching_parent_and_all_wide_captures", "identity": "stored_jra_id_and_parent_netkeiba_id_exact",
            "settlement": "normal_complete_rank_and_three_wide_winning_pairs_100yen",
            "population": "validated_subset_of_legacy_2025; full_legacy_equivalence_unproven",
            "value_thresholds": VALUE_THRESHOLDS, "information_thresholds": INFORMATION_THRESHOLDS}
MAP_TYPES = {
    "map_id": ("bigint", 8, False), "source_snapshot_id": ("bigint", 8, False),
    "source_relation": ("varchar", 128, False), "source_original_id": ("nvarchar", 256, False),
    "api_race_id": ("nvarchar", 128, True), "race_date": ("date", 3, True),
    "jv_race_key_full_16": ("varchar", 16, True),
    "venue_code": ("nvarchar", 32, True), "race_no": ("int", 4, True),
    "unified_race_id": ("nvarchar", 256, False), "mapping_status": ("varchar", 24, False),
    "evidence_json": ("nvarchar", -1, False),
}
CONTRACT["venue_dictionary_sha256"] = digest({"codes": COURSE_CODES, "aliases": {k: v.value for k, v in COURSE_ALIASES.items()}})
CONTRACT["identity"] = "verified_registered_live_races_map_and_parent_native_ids"
CONTRACT["mapping_evidence_schema"] = "stored_full16_and_coordinates_v1_no_12_to_16_synthesis"
CONTRACT["mapping_reference_evidence_schema"] = "registered_full16_reference_v1_no_id_synthesis"


def validate_registered_identity(row):
    """既存map証拠の方式と全座標・IDを照合し、非空JSONだけでは採用しない。

    Notes:
        stored_full_idそのものを検証に使い、API IDからJV IDを組み立てない。
        未知の証拠方式は別契約での確認が必要であり、暗黙に許可しない。
    """
    try:
        if row["mapping_status"] != "verified" or row["source_relation"] != "live.races" or not isinstance(row["source_original_id"], str) or not row["source_original_id"]:
            raise ValueError("registration")
        evidence = json.loads(row["evidence_json"])
        if isinstance(evidence, dict) and evidence.get("rule") == CONTRACT["mapping_reference_evidence_schema"]:
            from .jra_research_identity_repair import validate_reference_evidence
            validate_reference_evidence(row)
            return
        required = {"source_relation", "original_id", "stored_full_id", "stored_date", "stored_venue", "stored_race_no", "rule"}
        if not isinstance(evidence, dict) or set(evidence) != required:
            raise ValueError("schema")
        if evidence["rule"] != "stored_full16_and_coordinates; no 12-to-16 synthesis" or evidence["source_relation"] != "live.races":
            raise ValueError("method")
        full = row["jv_race_key_full_16"]
        if not isinstance(full, str) or len(full) != 16 or not full.isascii() or not full.isdigit():
            raise ValueError("full key")
        if evidence["stored_full_id"] != full or row["unified_race_id"] != "JRA:" + full:
            raise ValueError("unified identity")
        original = row["source_original_id"]
        if not all(isinstance(value, str) and value.encode("utf-16le") == original.encode("utf-16le")
                   for value in (evidence["original_id"], row["api_race_id"])):
            raise ValueError("native identity")
        venue = COURSE_ALIASES.get(evidence["stored_venue"])
        if venue is None or venue.value != COURSE_CODES.get(row["venue_code"]):
            raise ValueError("venue")
        day = date.fromisoformat(row["race_date"])
        if evidence["stored_date"] != day.isoformat() or day.strftime("%Y%m%d") != full[:8] or full[8:10] != row["venue_code"]:
            raise ValueError("date/venue coordinates")
        if type(evidence["stored_race_no"]) is not int or evidence["stored_race_no"] != row["race_no"] or int(full[-2:]) != row["race_no"]:
            raise ValueError("race number")
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ResearchError("unverified_mapping_evidence", 4) from None


@dataclass(frozen=True)
class CrossMarketConfig:
    """R11専用の固定版と実行上限を保持する。"""

    raw: dict

    @property
    def snapshot(self):
        """利用者が明示した固定snapshotを返す。"""
        return self.raw["source_policy"]["snapshot_id"]

    @classmethod
    def load(cls, path):
        """設定の未知キー・型・版・物理上限を接続前に検査する。"""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict) or set(raw) != {"schema_version", "profile_id", "source_policy", "year", "timing_policy", "limits"}:
                raise ValueError("keys")
            if type(raw["schema_version"]) is not int or raw["schema_version"] != 1 or raw["profile_id"] != CONTRACT["profile_id"]:
                raise ValueError("profile")
            policy = raw["source_policy"]
            if not isinstance(policy, dict) or set(policy) != {"source_key", "snapshot_id"} or policy["source_key"] != "analysis-current" or type(policy["snapshot_id"]) is not int or policy["snapshot_id"] < 1:
                raise ValueError("policy")
            if type(raw["year"]) is not int or raw["year"] != 2025 or raw["timing_policy"] != "matching_captured_at":
                raise ValueError("semantics")
            limits = raw["limits"]
            maxima = {"fetch_rows": 10000, "max_candidate_rows": 1000000, "query_timeout_seconds": 90, "memory_bytes": 2 * 1024 ** 3}
            if not isinstance(limits, dict) or set(limits) != set(maxima):
                raise ValueError("limits")
            if any(type(limits[k]) is not int or not 0 < limits[k] <= maximum for k, maximum in maxima.items()):
                raise ValueError("limits")
            return cls(raw)
        except (OSError, ValueError, TypeError, KeyError):
            raise ResearchError("invalid_cross_market_config", 2) from None


class CrossMarketReader(ResearchReader):
    """市場5表と登録ID対応だけを、検証済みの既存索引で有界読取する。"""

    def preflight(self, *, score=False):
        """読取専用権限・利用全列の型・非filtered unique route・採用版を検査する。"""
        ident = self._small("cross:identity", "SELECT DB_NAME() database_name,IS_SRVROLEMEMBER('sysadmin') sysadmin,IS_ROLEMEMBER('db_owner') db_owner,IS_ROLEMEMBER('db_ddladmin') db_ddladmin,IS_ROLEMEMBER('db_datawriter') db_datawriter")
        if len(ident) != 1 or ident[0]["database_name"] != "jra_unified" or any(ident[0][k] != 0 for k in ("sysadmin", "db_owner", "db_ddladmin", "db_datawriter")):
            raise ResearchError("unexpected_database_or_privilege", 3)
        tables = [table for table in FIELDS if not score or table != "live.netkeiba_payouts"]
        for scope, name, permissions in (("DATABASE", "jra_unified", ("CONTROL", "ALTER ANY SCHEMA", "CREATE TABLE")),
                                         ("SCHEMA", "live", ("ALTER", "CONTROL")), ("SCHEMA", "ops", ("ALTER", "CONTROL")),
                                         ("SCHEMA", "history", ("ALTER", "CONTROL")),
                                         *(("OBJECT", t, ("SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL")) for t in (*tables, "history.race_identity_map", "ops.source_snapshot", "ops.source_database"))):
            for permission in permissions:
                row = self._small("cross:permission", "SELECT HAS_PERMS_BY_NAME(?,?,?) permitted", (name, scope, permission))
                if len(row) != 1 or row[0]["permitted"] != int(permission == "SELECT"):
                    raise ResearchError("permission_contract_failed", 3, object=name, permission=permission)
        source = self._small("cross:source", "SELECT d.source_key,s.source_snapshot_id,s.status,s.schema_catalog_sha256 FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (self.config.snapshot,))
        if len(source) != 1 or source[0]["source_key"] != self.config.raw["source_policy"]["source_key"] or source[0]["status"] != "verified":
            raise ResearchError("unverified_source", 3)
        self.report = {"identity": ident[0], "source": source[0]}
        mapping_digest, mapping_counts = self.identity_map()
        schema, indexes = {}, {}
        for table in tables:
            cols = self._small("cross:columns", "SELECT c.name,t.name type_name,c.max_length,c.is_nullable,c.is_computed FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id", (table,))
            actual = {row["name"]: row for row in cols}
            fields = [name for name in FIELDS[table] if not score or name != "rank"]
            fields += ["__migration_source_snapshot_id", "__migration_source_rowid"]
            for name in fields:
                sql_type, size = ("bigint", 8) if name in {"rank", "payout", "race_no", "__migration_source_snapshot_id", "__migration_source_rowid"} else (("float", 8) if name in {"win_odds", "odds", "odds_min", "odds_max"} else ("nvarchar", -1))
                expected = (sql_type, size, name != "__migration_source_snapshot_id", False)
                observed = actual.get(name)
                if observed is None or tuple(observed[k] for k in ("type_name", "max_length", "is_nullable", "is_computed")) != expected:
                    raise ResearchError("cross_market_schema_failed", 3, table=table, column=name)
            schema[table] = {name: actual[name] for name in fields}
            found = self._small("cross:indexes", "SELECT i.name,i.is_unique,i.is_disabled,i.is_hypothetical,i.has_filter,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
            groups = {}
            for row in found:
                if row["is_unique"] == 1 and all(row[k] == 0 for k in ("is_disabled", "is_hypothetical", "has_filter")):
                    groups.setdefault(row["name"], []).append(row["column_name"])
            if ["__migration_source_snapshot_id", "__migration_source_rowid"] not in groups.values():
                raise ResearchError("keyset_requires_unique_index", 3, table=table)
            indexes[table] = found
        self.report = {"identity": ident[0], "source": source[0], "schema_sha256": digest(schema), "indexes_sha256": digest(indexes),
                       "identity_map_sha256": mapping_digest, "identity_map_counts": mapping_counts,
                       "venue_dictionary_sha256": CONTRACT["venue_dictionary_sha256"],
                       "availability": "research_only", "feature_availability": "retrospective_final_odds",
                       "read_consistency": "chunked_unproven", "replayability": "content_match_only",
                       "timing_guarantee": "matching_capture_only_not_announced_at_or_strict_live"}
        return self.report

    def identity_map(self):
        """登録mapの限定prefix全体を読み、hash lookupなしで元IDと版を照合する。

        Notes:
            computed hash値/式を述語・結合・一致証拠へ使わない。snapshot/relation索引の
            prefixだけで対象を限定し、元IDのbinary順/map_id順で最大9000件を読む。
            上限到達は全体性未証明として停止。未解決をverifiedへ変更しない。
        """
        table = "history.race_identity_map"
        cols = self._small("cross:map-columns", "SELECT c.name,t.name type_name,c.max_length,c.is_nullable,c.is_computed FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id", (table,))
        actual = {row["name"]: row for row in cols}
        for name, (kind, length, nullable) in MAP_TYPES.items():
            row = actual.get(name)
            if row is None or tuple(row[k] for k in ("type_name", "max_length", "is_nullable", "is_computed")) != (kind, length, nullable, False):
                raise ResearchError("cross_market_map_schema_failed", 3, column=name)
        indexes = self._small("cross:map-indexes", "SELECT i.name,i.is_unique,i.is_disabled,i.is_hypothetical,i.has_filter,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
        groups = {}
        for row in indexes:
            if row["is_unique"] == 1 and all(row[k] == 0 for k in ("is_disabled", "is_hypothetical", "has_filter")):
                groups.setdefault(row["name"], []).append(row["column_name"])
        if not any(keys[:2] == ["source_snapshot_id", "source_relation"] for keys in groups.values()):
            raise ResearchError("cross_market_map_route_missing", 3)
        rows = self._small("cross:map-prefix", "SELECT TOP (?) map_id,source_snapshot_id,source_relation,source_original_id,api_race_id,jv_race_key_full_16,CONVERT(varchar(10),race_date,23) race_date,venue_code,race_no,unified_race_id,mapping_status,evidence_json FROM history.race_identity_map WHERE source_snapshot_id=? AND source_relation=? ORDER BY CONVERT(varbinary(max),source_original_id),map_id", (9000, self.config.snapshot, "live.races"))
        if len(rows) >= 9000:
            raise ResearchError("cross_market_map_row_limit", 4, completeness="unproven_at_cap")
        self.identity_rows, api_seen, reverse = {}, set(), set()
        counts = Counter()
        for row in rows:
            if row["source_snapshot_id"] != self.config.snapshot or row["source_relation"] != "live.races":
                raise ResearchError("cross_market_map_source_mismatch", 3)
            original = row["source_original_id"]
            if not isinstance(original, str) or not original:
                raise ResearchError("cross_market_map_identity_invalid", 4)
            key = original.encode("utf-16le")
            if key in self.identity_rows:
                raise ResearchError("cross_market_map_duplicate", 4)
            self.identity_rows[key] = row
            if isinstance(row["race_date"], str) and row["race_date"].startswith("2025-"):
                counts[row["mapping_status"]] += 1
            if row["mapping_status"] == "verified":
                if isinstance(row["race_date"], str) and row["race_date"].startswith("2025-"):
                    validate_registered_identity(row)
                if not isinstance(row["api_race_id"], str) or not row["unified_race_id"]:
                    raise ResearchError("cross_market_map_identity_invalid", 4)
                api_key = row["api_race_id"].encode("utf-16le")
                if api_key in api_seen or row["unified_race_id"] in reverse:
                    raise ResearchError("cross_market_map_duplicate", 4)
                api_seen.add(api_key)
                reverse.add(row["unified_race_id"])
        self.report["identity_map_counts"] = dict(counts)
        if not counts["verified"]:
            raise ResearchError("cross_market_identity_coverage_empty", 4, year=2025, mapping_counts=dict(counts))
        return digest({"rows": rows, "schema": {k: actual[k] for k in MAP_TYPES}, "indexes": indexes}), dict(counts)

    def table_rows(self, table, *, score=False):
        """許可表の全使用列を固定版・一意rowidで走査し、件数/メモリ上限を守る。"""
        if table not in FIELDS or score and table == "live.netkeiba_payouts":
            raise ResearchError("invalid_cross_market_table", 3)
        fields = ("__migration_source_rowid", *(name for name in FIELDS[table] if not score or name != "rank"))
        previous, seen = None, 0
        limits = self.config.raw["limits"]
        while True:
            size = min(limits["fetch_rows"], limits["max_candidate_rows"] - seen)
            if size <= 0:
                raise ResearchError("scan_row_limit", 4, table=table, completeness="unproven_at_cap")
            sql = "SELECT TOP (?) " + ",".join("[" + field + "]" for field in fields)
            sql += " FROM " + table + " WHERE __migration_source_snapshot_id=?"
            params = [size, self.config.snapshot]
            if previous is not None:
                sql += " AND __migration_source_rowid>?"
                params.append(previous)
            sql += " ORDER BY __migration_source_rowid"
            with self._cursor("cross:keyset:" + table, sql, params) as cursor:
                rows = cursor.fetchmany(size)
            if not rows:
                return
            check_memory(limits["memory_bytes"])
            for values in rows:
                row = dict(zip(fields, values, strict=True))
                identifier = row["__migration_source_rowid"]
                if type(identifier) is not int or previous is not None and identifier <= previous:
                    raise ResearchError("invalid_keyset_rowid", 3, table=table)
                seen += 1
                self.scan_rows[table] = self.scan_rows.get(table, 0) + 1
                if seen > limits["max_candidate_rows"]:
                    raise ResearchError("scan_row_limit", 4, table=table)
                previous = identifier
                yield row
            if len(rows) < size:
                return


def collect_cross_market(reader, *, race_id=None):
    """全使用列とmetadataを二巡照合し、一巡目の対象年/対象レース行だけ保持する。"""
    score = race_id is not None
    retained, first_digests, first_report = {}, None, None
    for pass_no in range(2):
        report = reader.preflight(score=score)
        streams = {}
        for table in FIELDS:
            if score and table == "live.netkeiba_payouts":
                continue
            stream = hashlib.sha256((table + "\n").encode())
            for row in reader.table_rows(table, score=score):
                stream.update((canonical_json(row) + "\n").encode("utf-8"))
                if pass_no:
                    continue
                key = row.get("race_id") if table == "live.races" else row.get("jra_race_id")
                if table == "live.races":
                    day = row["race_date"]
                    if not isinstance(day, str) or not day.startswith("2025-") or score and key != race_id:
                        continue
                    if date.fromisoformat(day).isoformat() != day or not isinstance(key, str) or not key:
                        raise ResearchError("invalid_cross_market_race", 4)
                    if key in retained:
                        retained[key]["bad"] = "ambiguous_race"
                    else:
                        retained[key] = {"race": row, "identity": reader.identity_rows.get(key.encode("utf-16le")),
                                         "parents": [], "results": [], "odds": [], "payouts": []}
                elif key in retained:
                    bucket = {"live.netkeiba_race_results": "parents", "live.netkeiba_result_entries": "results",
                              "live.netkeiba_odds_entries": "odds", "live.netkeiba_payouts": "payouts"}[table]
                    if bucket not in {"odds", "payouts"} or row["bet_type"] == "wide":
                        retained[key][bucket].append(row)
            streams[table] = stream.hexdigest()
        check_memory(reader.config.raw["limits"]["memory_bytes"])
        if pass_no and (streams != first_digests or report != first_report):
            raise ResearchError("source_changed", 5)
        first_digests, first_report = streams, report
    return retained, digest({"streams": first_digests, "preflight": first_report}), first_report


def _pair(text):
    """保存済みpairの馬番表記を維持し、二頭の数値順と正当性だけを検査する。"""
    parts = text.split("-") if isinstance(text, str) else []
    if len(parts) != 2 or any(not p.isascii() or not p.isdigit() or not 1 <= int(p) <= 18 for p in parts) or int(parts[0]) == int(parts[1]):
        raise ResearchError("invalid_market_pair", 4)
    return tuple(sorted(parts, key=int))


def _positive(value):
    """単勝/ワイド価格の非有限・NULL・非正値を拒否する。"""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ResearchError("invalid_market_price", 4)
    return float(value)


def validate_race_bundle(bundle, *, score=False):
    """同じvendor ID/captureの完全市場と、評価時だけ正常wide精算を構成する。

    Returns:
        結果を含まない候補列と、評価時だけ全候補pairの確定払戻対応。
    Raises:
        ResearchError: ID/時点/市場の不一致、重複、未対応順位、精算不明。
    """
    if "bad" in bundle:
        raise ResearchError(bundle["bad"], 4)
    race, parents = bundle["race"], bundle["parents"]
    if len(parents) != 1:
        raise ResearchError("missing_or_ambiguous_result_parent", 4)
    parent = parents[0]
    mapping = bundle.get("identity")
    if not mapping or mapping["mapping_status"] != "verified":
        raise ResearchError("unresolved_registered_identity", 4)
    validate_registered_identity(mapping)
    try:
        parent_course = COURSE_ALIASES.get(parent["course"]) or COURSE_ALIASES.get(str(parent["course"]).lower())
        if parent_course is None or parent_course.value != COURSE_CODES.get(mapping["venue_code"]):
            raise ValueError("venue or evidence")
        if any(mapping[k] != race[k] or race[k] is None for k in ("race_date", "race_no")):
            raise ValueError("date/number")
        native_id = race["race_id"].encode("utf-16le")
        if mapping["source_original_id"].encode("utf-16le") != native_id or mapping["api_race_id"].encode("utf-16le") != native_id:
            raise ValueError("original ID")
    except (TypeError, ValueError, AttributeError):
        raise ResearchError("identity_map_attribute_mismatch", 4) from None
    if any(parent[k] != race[k] or race[k] is None for k in ("race_date", "race_no")) or not parent["netkeiba_race_id"]:
        raise ResearchError("identity_attribute_mismatch", 4)
    try:
        capture = _time_key(_utc(parent["fetched_at"]))
        host = urlsplit(parent["source"]).hostname or ""
        if host != "netkeiba.com" and not host.endswith(".netkeiba.com"):
            raise ValueError("source")
    except (TypeError, ValueError, ResearchError):
        raise ResearchError("unknown_result_capture", 4) from None
    for row in (*bundle["results"], *bundle["odds"], *bundle["payouts"]):
        if row["netkeiba_race_id"] != parent["netkeiba_race_id"] or row["jra_race_id"] != parent["jra_race_id"]:
            raise ResearchError("identity_attribute_mismatch", 4)
    wins, ranks, numbers = {}, {}, set()
    for row in bundle["results"]:
        horse = row["horse_no"]
        if not isinstance(horse, str) or not horse.isascii() or not horse.isdigit() or not 1 <= int(horse) <= 18:
            raise ResearchError("invalid_market_horse", 4)
        if horse in wins or int(horse) in numbers:
            raise ResearchError("ambiguous_win_price", 4)
        numbers.add(int(horse))
        wins[horse] = _positive(row["win_odds"])
        if not score:
            ranks[horse] = row["rank"]
    if len(wins) < 3:
        raise ResearchError("incomplete_win_book", 4)
    wides = {}
    for row in bundle["odds"]:
        try:
            observed = _time_key(_utc(row["fetched_at"]))
            host = urlsplit(row["source"]).hostname or ""
        except (TypeError, ValueError, ResearchError):
            raise ResearchError("unknown_wide_capture", 4) from None
        if observed != capture:
            raise ResearchError("capture_time_mismatch", 4)
        if host != "netkeiba.com" and not host.endswith(".netkeiba.com"):
            raise ResearchError("source_mismatch", 4)
        pair = _pair(row["combination"])
        if pair in wides:
            raise ResearchError("ambiguous_wide_price", 4)
        if row["odds"] is not None:
            price = _positive(row["odds"])
        else:
            lo = _positive(row["odds_min"]) if row["odds_min"] is not None else None
            hi = _positive(row["odds_max"]) if row["odds_max"] is not None else None
            if lo is None and hi is None or lo is not None and hi is not None and lo > hi:
                raise ResearchError("invalid_market_price", 4)
            price = (lo + hi) / 2 if lo is not None and hi is not None else lo or hi
        wides[pair] = price
    expected_book = set(combinations(sorted(wins, key=int), 2))
    if set(wides) != expected_book:
        raise ResearchError("incomplete_wide_book", 4)
    candidates = build_race_candidates(parent["jra_race_id"], race["race_date"], wins, wides)
    if score:
        return candidates, {}
    if any(type(rank) is not int for rank in ranks.values()) or sorted(ranks.values()) != list(range(1, len(wins) + 1)):
        raise ResearchError("settlement_unknown_rank", 4)
    winners = sorted((h for h, rank in ranks.items() if rank <= 3), key=int)
    expected_hits = set(combinations(winners, 2))
    actual = {}
    for row in bundle["payouts"]:
        pair = _pair(row["combination"])
        if pair in actual or type(row["payout"]) is not int or row["payout"] <= 0:
            raise ResearchError("ambiguous_or_unknown_payout", 4)
        actual[pair] = row["payout"]
    if set(actual) != expected_hits:
        raise ResearchError("settlement_incomplete_wide", 4)
    return candidates, {(parent["jra_race_id"], pair): actual.get(pair, 0) for pair in wides}


def build_cross_market(bundles, *, score=False):
    """採用/除外を全raceで数え、精算不明を外れへ変換せず結果を分離する。"""
    candidates, payouts, reasons, samples = [], {}, Counter(), []
    accepted, periods = 0, Counter()
    for key, bundle in bundles.items():
        try:
            rows, outcome = validate_race_bundle(bundle, score=score)
        except ResearchError as error:
            reasons[error.reason] += 1
            if len(samples) < 10:
                samples.append({"race_key": key, "reason": error.reason})
            continue
        candidates.extend(rows)
        payouts.update(outcome)
        accepted += 1
        day = bundle["race"]["race_date"]
        periods["development_2025h1" if day <= "2025-06-30" else "external_2025q3" if day <= "2025-09-30" else "external_2025q4"] += 1
    coverage = {"candidate_races": len(bundles), "accepted_races": accepted, "excluded_races": sum(reasons.values()),
                "excluded_by_reason": dict(reasons), "exclusion_samples": samples, "period_races": dict(periods),
                "legacy_population_equivalence": False, "contract_sha256": digest(CONTRACT)}
    return candidates, payouts, coverage


def execute_cross_market(path=None, *, replay_run_id=None, race_id=None):
    """評価/replay/対象結果非参照scoreを実行し、失敗も新規共通runへ記録する。"""
    original = None
    if replay_run_id is not None:
        prior = existing_run(replay_run_id)
        original = json.loads((prior / "manifest.json").read_text(encoding="utf-8"))
        if original.get("status") != "complete" or original.get("command") not in {"cross-market", "cross-market-replay"}:
            raise ResearchError("run_not_replayable", 2)
        path = prior / "config.json"
    if race_id is not None and (not isinstance(race_id, str) or not race_id or len(race_id) > 128):
        raise ResearchError("invalid_cross_market_race", 2)
    config = CrossMarketConfig.load(path)
    artifact = RunArtifacts(config.raw, "cross-market-score" if race_id else "cross-market-replay" if original else "cross-market")
    reader = None
    try:
        with CrossMarketReader(config) as reader:
            bundles, content, report = collect_cross_market(reader, race_id=race_id)
            artifact.write_json("preflight.json", report)
            artifact.manifest.update(input_content_sha256=content, feature_contract_sha256=digest(CONTRACT),
                                     query_metrics=reader.query_metrics, scan_rows=reader.scan_rows,
                                     outcome_read=race_id is None)
        if original is not None and (original.get("input_content_sha256") != content or original.get("feature_contract_sha256") != digest(CONTRACT)):
            raise ResearchError("replay_input_changed", 5)
        candidates, payouts, coverage = build_cross_market(bundles, score=race_id is not None)
        del bundles
        artifact.write_json("coverage.json", coverage)
        check_memory(config.raw["limits"]["memory_bytes"])
        if not candidates:
            raise ResearchError("cross_market_coverage_empty", 4, excluded_by_reason=coverage["excluded_by_reason"])
        if race_id is None:
            metrics = evaluate_candidates(candidates, payouts)
        else:
            tickets = [{"direction": direction, "threshold": threshold, "tickets": select_candidates(candidates, direction, threshold)}
                       for direction, values in (("value", VALUE_THRESHOLDS), ("information", INFORMATION_THRESHOLDS)) for threshold in values]
            metrics = {"race_id": race_id, "outcome_read": False, "kind": "retrospective_stored_final_odds_score", "policies": tickets}
        if original is not None and digest(metrics) != original.get("metrics_sha256"):
            raise ResearchError("replay_output_changed", 5)
        artifact.write_json("metrics.json", metrics)
        artifact.finish(metrics_sha256=digest(metrics), overall_complete=False, legacy_population_equivalence=False,
                        replay_of=replay_run_id, verification_scope="validated_subset_only")
        return {"status": "passed", "run_id": artifact.run_id, "accepted_races": coverage["accepted_races"],
                "excluded_races": coverage["excluded_races"], "outcome_read": race_id is None,
                "legacy_population_equivalence": False, "overall_complete": False}
    except Exception as exc:
        error = exc if isinstance(exc, ResearchError) else ResearchError("cross_market_execution_failed", 4, error_type=type(exc).__name__)
        error.details.setdefault("run_id", artifact.run_id)
        error.details.setdefault("resume_condition", "固定版/ID/同時点capture/完全wide精算とcoverageを確認後、新規runで再開。自動再試行しない。")
        if reader is not None:
            artifact.manifest["query_metrics"] = reader.query_metrics
            artifact.manifest["scan_rows"] = reader.scan_rows
            if not (artifact.path / "preflight.json").exists():
                artifact.write_json("preflight.json", {"status": "failed", "partial_diagnostics": reader.report,
                    "last_query_id": reader.query_metrics[-1]["query_id"] if reader.query_metrics else None})
        artifact.fail(error)
        raise error from None
