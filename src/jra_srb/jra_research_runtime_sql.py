"""概要: SQL専用readerからruntime receiptの完全束を再現し、二巡の一致を検査する。
作成日: 2026-10-15
入力: source/map版、source_relation、race ID、operation、cutoffを含む非秘密JSON設定。
出力: 本文を含まない診断・選択digestとRunArtifactsの失敗記録。
実行例: uv run python -c "from jra_srb.jra_research_runtime_sql import execute_runtime_verification; print(execute_runtime_verification('configs/research/runtime_receipt_v1.json'))"
注意事項: SELECT専用。baselineは未実装で受入対象外。大表scan、API/旧DB接続、本文成果物保存は行わない。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace
from datetime import date
import hashlib

from .jra_research_artifacts import RunArtifacts
from .jra_research_contracts import ResearchError, digest, timestamp
from .jra_research_reader import ResearchReader
from .jra_research_resources import check_memory
from .jra_research_raw_sql import _expression_identity, _hash_expression
from .jra_research_runtime import (
    OPERATIONS,
    RuntimeIdentity,
    read_receipt_rows,
    select_runtime_bundle,
    select_whole_bundle,
    validate_identity_map,
)


_RECEIPT = "api_runtime.write_receipts"
_IDENTITY = "history.race_identity_map"


def _config(path: str | Path) -> dict:
    """JSON設定のキー・型・要求条件を厳格に検証する。

    Args:
        path: UTF-8のJSON設定パス。
    Returns:
        検証済み設定辞書。
    Raises:
        ResearchError: 設定が不正、未知キーあり、または要求が不完全。
    """
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ResearchError("invalid_config_file", 2) from None
    if not isinstance(value, dict) or set(value) != {"schema_version", "profile_id", "source_policy", "id_map", "request", "limits", "configuration_status"}:
        raise ResearchError("invalid_config_keys", 2)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["profile_id"] != "runtime_receipt_v1" or not isinstance(value["configuration_status"], str) or value["configuration_status"] not in {"example_only", "ready_for_verification"}:
        raise ResearchError("invalid_config_version", 2)
    policy = value["source_policy"]
    if not isinstance(policy, dict) or set(policy) != {"policy_id", "source_key", "snapshot_id"} or policy["policy_id"] != "runtime_receipt_v1" or not isinstance(policy["source_key"], str) or not policy["source_key"] or type(policy["snapshot_id"]) is not int or policy["snapshot_id"] < 1:
        raise ResearchError("invalid_source_config", 2)
    if not isinstance(value["id_map"], dict) or set(value["id_map"]) != {"source_snapshot_id", "source_relation", "source_original_id"}:
        raise ResearchError("invalid_id_map_config", 2)
    if type(value["id_map"]["source_snapshot_id"]) is not int or value["id_map"]["source_snapshot_id"] < 1 or not isinstance(value["id_map"]["source_relation"], str) or not value["id_map"]["source_relation"] or not isinstance(value["id_map"]["source_original_id"], str) or not value["id_map"]["source_original_id"]:
        raise ResearchError("invalid_id_map_config", 2)
    if policy["snapshot_id"] != value["id_map"]["source_snapshot_id"]:
        raise ResearchError("source_snapshot_mismatch", 2)
    request = value["request"]
    required = {"api_race_id", "source", "operation", "knowledge_cutoff", "decision_cutoff", "bet_type", "odds_timing", "race_date", "course", "race_no"}
    if not isinstance(request, dict) or set(request) != required:
        raise ResearchError("invalid_request_config", 2)
    if any(not isinstance(request[key], str) or not request[key] for key in ("api_race_id", "source", "operation", "knowledge_cutoff", "race_date", "course")):
        raise ResearchError("invalid_request_config", 2)
    if request["operation"] not in OPERATIONS or type(request["race_no"]) is not int or not 1 <= request["race_no"] <= 12:
        raise ResearchError("invalid_request_config", 2)
    if request["operation"] == "odds":
        if not isinstance(request["bet_type"], str) or not request["bet_type"] or not isinstance(request["odds_timing"], str) or not request["odds_timing"]:
            raise ResearchError("explicit_market_required", 2)
    elif request["bet_type"] is not None or request["odds_timing"] is not None:
        raise ResearchError("invalid_request_config", 2)
    if request["decision_cutoff"] is not None and not isinstance(request["decision_cutoff"], str):
        raise ResearchError("invalid_request_config", 2)
    try:
        if str(date.fromisoformat(request["race_date"])) != request["race_date"]:
            raise ValueError("noncanonical date")
        timestamp(request["knowledge_cutoff"])
        if request["decision_cutoff"] is not None:
            timestamp(request["decision_cutoff"])
    except (ValueError, ResearchError):
        raise ResearchError("invalid_request_config", 2) from None
    limits = value["limits"]
    if not isinstance(limits, dict) or set(limits) != {"max_receipt_rows", "memory_bytes"} or type(limits["max_receipt_rows"]) is not int or not 1 <= limits["max_receipt_rows"] <= 9999 or type(limits["memory_bytes"]) is not int or not 1 <= limits["memory_bytes"] <= 2 * 1024 ** 3:
        raise ResearchError("invalid_resource_limit", 2)
    return value


def _small(reader: ResearchReader, query_id: str, sql: str, params: tuple = ()) -> list[dict]:
    """ResearchReader既存の_smallだけを用いて小規模SELECTを実行する。"""
    reader.report["last_query_id"] = query_id
    rows = reader._small(query_id, sql, params)
    reader.report["query_count"] = len(reader.query_metrics)
    return rows


def _preflight(reader: ResearchReader, config: dict) -> dict:
    """reader権限・source・receipt/mapの列型、hash式、有効索引routeを検査する。

    Notes:
        sys catalogで定義を確認できない場合やrouteの根拠が足りない場合は停止する。
        sysadmin/owner/writer権限、DML/DDL権限、NULL権限判定を許容しない。
    """
    ident = _small(reader, "runtime:identity", "SELECT DB_NAME() database_name,CURRENT_USER database_user,IS_SRVROLEMEMBER('sysadmin') sysadmin,IS_ROLEMEMBER('db_owner') db_owner,IS_ROLEMEMBER('db_ddladmin') db_ddladmin,IS_ROLEMEMBER('db_datawriter') db_datawriter")
    if len(ident) != 1 or ident[0]["database_name"] != "jra_unified" or any(ident[0][k] != 0 for k in ("sysadmin", "db_owner", "db_ddladmin", "db_datawriter")):
        raise ResearchError("unexpected_database_or_privilege", 3)
    permissions = []
    for permission in ("CONTROL", "ALTER ANY SCHEMA", "CREATE TABLE"):
        rows = _small(reader, "runtime:permission", "SELECT HAS_PERMS_BY_NAME(?,?,?) permitted", ("jra_unified", "DATABASE", permission))
        if len(rows) != 1 or rows[0]["permitted"] is None or rows[0]["permitted"] != 0:
            raise ResearchError("permission_contract_failed", 3, object="jra_unified", permission=permission)
    for table in (_RECEIPT, _IDENTITY, "ops.source_snapshot", "ops.source_database"):
        for permission, expected in (("SELECT", 1), ("INSERT", 0), ("UPDATE", 0), ("DELETE", 0), ("ALTER", 0), ("CONTROL", 0)):
            rows = _small(reader, "runtime:permission", "SELECT HAS_PERMS_BY_NAME(?,?,?) permitted", (table, "OBJECT", permission))
            if len(rows) != 1 or rows[0]["permitted"] is None or rows[0]["permitted"] != expected:
                raise ResearchError("permission_contract_failed", 3, object=table, permission=permission)
            permissions.append((table, permission, expected))
    for schema in ("api_runtime", "history", "ops"):
        for permission in ("ALTER", "CONTROL"):
            rows = _small(reader, "runtime:permission", "SELECT HAS_PERMS_BY_NAME(?,?,?) permitted", (schema, "SCHEMA", permission))
            if len(rows) != 1 or rows[0]["permitted"] is None or rows[0]["permitted"] != 0:
                raise ResearchError("permission_contract_failed", 3, object=schema, permission=permission)
    snapshot_id = config["source_policy"]["snapshot_id"]
    source = _small(reader, "runtime:source", "SELECT d.source_key,s.source_snapshot_id,s.source_database_id,s.status FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (snapshot_id,))
    if len(source) != 1 or source[0]["source_key"] != config["source_policy"]["source_key"] or source[0]["status"] != "verified":
        raise ResearchError("unverified_source", 3)

    expected_columns = {
        _RECEIPT: {"request_sha256": ("binary", 32, False), "operation": ("nvarchar", 128, False), "race_id": ("nvarchar", -1, False), "payload_json": ("nvarchar", -1, False), "received_at_utc": ("datetime2", 8, False), "race_sha256": ("binary", 32, True)},
        _IDENTITY: {"source_snapshot_id": ("bigint", 8, False), "source_relation": ("varchar", 128, False), "source_original_id": ("nvarchar", 256, False), "api_race_id": ("nvarchar", 128, True), "race_date": ("date", 3, True), "venue_code": ("nvarchar", 32, True), "race_no": ("int", 4, True), "unified_race_id": ("nvarchar", 256, False), "mapping_status": ("varchar", 24, False), "evidence_json": ("nvarchar", -1, False), "source_row_sha256": ("binary", 32, False), "__unified_original_sha256": ("binary", 32, True)},
    }
    definitions = {}
    for table, expected in expected_columns.items():
        rows = _small(reader, "runtime:columns", "SELECT c.name,t.name type_name,c.max_length,c.is_nullable,c.is_computed,c.scale FROM sys.columns c JOIN sys.types t ON c.user_type_id=t.user_type_id WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id", (table,))
        actual = {row["name"]: row for row in rows}
        if not expected.keys() <= actual.keys():
            raise ResearchError("missing_schema_columns", 3, table=table)
        for name, (type_name, length, nullable) in expected.items():
            row = actual[name]
            if (row["type_name"], row["max_length"], bool(row["is_nullable"]), bool(row["is_computed"])) != (type_name, length, nullable, name in {"race_sha256", "__unified_original_sha256"}):
                raise ResearchError("unexpected_column_definition", 3, table=table, column=name)
            if name == "received_at_utc" and row["scale"] != 7:
                raise ResearchError("unexpected_column_definition", 3, table=table, column=name)
        definitions[table] = rows
    computed = {}
    for table, name in ((_RECEIPT, "race_sha256"), (_IDENTITY, "__unified_original_sha256")):
        rows = _small(reader, "runtime:computed", "SELECT name,definition,is_persisted FROM sys.computed_columns WHERE object_id=OBJECT_ID(?) AND name=?", (table, name))
        if len(rows) != 1 or not rows[0]["definition"] or rows[0]["is_persisted"] != 1:
            raise ResearchError("missing_hash_definition", 3, table=table)
        # receiptのmigrationはnvarcharを直接HASHBYTESへ渡す。raw finalizeの式と区別する。
        expected_expression = ("CONVERT(binary(32),HASHBYTES('SHA2_256',race_id))" if table == _RECEIPT
                               else _hash_expression(("source_original_id",)))
        try:
            observed_formula = _expression_identity(rows[0]["definition"])
            expected_formula = _expression_identity(expected_expression)
        except ResearchError:
            raise ResearchError("unexpected_hash_definition", 3, table=table) from None
        if observed_formula != expected_formula:
            raise ResearchError("unexpected_hash_definition", 3, table=table)
        computed[table] = rows[0]
    indexes = {}
    for table in expected_columns:
        rows = _small(reader, "runtime:indexes", "SELECT i.name,i.is_unique,i.is_disabled,i.is_hypothetical,i.filter_definition,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
        groups = {}
        for row in rows:
            if not row["is_disabled"] and not row["is_hypothetical"] and row["filter_definition"] is None:
                groups.setdefault(row["name"], []).append(row["column_name"])
        required = (["race_sha256", "received_at_utc"] if table == _RECEIPT else ["source_snapshot_id", "source_relation", "__unified_original_sha256"])
        route_indexes = [row["name"] for row in rows if not row["is_disabled"] and not row["is_hypothetical"] and row["filter_definition"] is None and row["is_unique"] and groups.get(row["name"], []) == required]
        if table == _RECEIPT:
            unique_groups = [groups.get(row["name"], []) for row in rows if row["is_unique"] and not row["is_disabled"] and not row["is_hypothetical"] and row["filter_definition"] is None]
            if ["request_sha256"] not in unique_groups or not any(cols[:2] == required for cols in groups.values()):
                raise ResearchError("missing_index_route", 3, table=table)
        elif not route_indexes:
            raise ResearchError("missing_index_route", 3, table=table)
        indexes[table] = rows
    return {"database": ident[0], "source": source[0], "permission_checks": len(permissions),
            "schema_digest": digest(definitions), "computed_digest": digest(computed),
            "index_digest": digest(indexes), "receipt_route": "race_sha256+race_id_exact+cutoff",
            "id_map_route": "bounded_source_snapshot+source_relation_index_range+api_id_and_unified_id_reverse_uniqueness"}


def _identity_rows(reader: ResearchReader, config: dict) -> tuple[list[dict], str]:
    """mapをpoint lookupし、snapshot/relation範囲内の正逆一意とevidenceを確認する。"""
    request = config["request"]
    api_id = request["api_race_id"]
    original_id = config["id_map"]["source_original_id"]
    point_sql = ("SELECT TOP (2) source_snapshot_id,source_relation,source_original_id,api_race_id,"
                 "CONVERT(varchar(10),race_date,23) race_date,venue_code,race_no,unified_race_id,mapping_status,evidence_json,source_row_sha256 "
                 "FROM history.race_identity_map WHERE source_snapshot_id=? AND source_relation=? "
                 "AND __unified_original_sha256=CONVERT(binary(32),?) "
                 "AND CONVERT(varbinary(max),source_original_id)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?))")
    point_rows = _small(reader, "runtime:id_map_point_lookup", point_sql,
                        (config["id_map"]["source_snapshot_id"], config["id_map"]["source_relation"],
                         hashlib.sha256(original_id.encode("utf-16le")).digest(), original_id))
    if len(point_rows) != 1 or point_rows[0]["api_race_id"] != api_id:
        raise ResearchError("unresolved_id", 3)
    try:
        evidence = json.loads(point_rows[0]["evidence_json"])
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("evidence")
    except (TypeError, ValueError):
        raise ResearchError("unresolved_id_evidence", 3) from None
    # unique indexのsnapshot/relation prefixで範囲を限定し、全候補上限を超えれば停止する。
    sql = ("SELECT TOP (?) source_snapshot_id,source_relation,source_original_id,api_race_id,"
           "CONVERT(varchar(10),race_date,23) race_date,venue_code,race_no,unified_race_id,mapping_status "
           "FROM history.race_identity_map WHERE source_snapshot_id=? AND source_relation=? "
           "ORDER BY __unified_original_sha256")
    rows = _small(reader, "runtime:id_map_lookup", sql, (10001, config["id_map"]["source_snapshot_id"], config["id_map"]["source_relation"]))
    if len(rows) > 10000:
        raise ResearchError("id_map_row_limit", 4, maximum=10000)
    forward, reverse, matched = {}, {}, []
    for candidate in rows:
        key, unified = candidate["api_race_id"], candidate["unified_race_id"]
        if not key or not unified or key in forward or unified in reverse:
            raise ResearchError("ambiguous_id", 3)
        forward[key], reverse[unified] = unified, key
        if key == api_id:
            if candidate["source_original_id"] != original_id:
                raise ResearchError("unresolved_id", 3)
            matched.append(candidate)
    if len(matched) != 1:
        raise ResearchError("unresolved_id", 3)
    row = matched[0]
    if (row["race_date"] != request["race_date"] or row["venue_code"] != request["course"] or row["race_no"] != request["race_no"]):
        raise ResearchError("identity_attribute_mismatch", 3)
    if point_rows[0]["unified_race_id"] != row["unified_race_id"] or point_rows[0]["race_date"] != row["race_date"] or point_rows[0]["venue_code"] != row["venue_code"] or point_rows[0]["race_no"] != row["race_no"]:
        raise ResearchError("identity_attribute_mismatch", 3)
    mapped = [{"api_race_id": row["api_race_id"], "unified_race_id": row["unified_race_id"],
             "race_date": row["race_date"], "course": row["venue_code"], "race_no": row["race_no"],
             "source_snapshot_id": row["source_snapshot_id"], "mapping_status": row["mapping_status"]}]
    return mapped, digest({"range_rows": rows, "target_row": mapped[0], "evidence_sha256": hashlib.sha256(point_rows[0]["evidence_json"].encode("utf-8")).hexdigest(),
                          "source_row_sha256": point_rows[0]["source_row_sha256"]})


def execute_runtime_verification(config_path: str | Path) -> dict:
    """runtime完全束をSQLから二巡取得し、入力と選択digestの再現一致を返す。

    Args:
        config_path: runtime_receipt_v1形式の非秘密JSON設定。
    Returns:
        成功時の診断・選択digest。本文や全特徴量は含めない。
    Raises:
        ResearchError: preflight、ID解決、receipt選択、二巡digestのいずれかが不成立。
    Notes:
        RunArtifactsにはpreflight診断または固定エラーだけを保存する。receipt-only実行は
        baseline_verified/overall_completeをfalseとし、M4完了扱いにしない。
    """
    config = _config(config_path)
    artifact = RunArtifacts(config, "runtime-sql-verification")
    reader = None
    try:
        # ResearchReaderはSQL接続・timeout・cursor/smallのみ利用するための最小構成。
        internal = SimpleNamespace(raw={"limits": {"query_timeout_seconds": 30}})
        reader = ResearchReader(internal)
        reader.__enter__()
        pass_digests, pass_results = [], []
        for _ in range(2):
            check_memory(config["limits"]["memory_bytes"])
            preflight = _preflight(reader, config)
            map_rows, map_digest = _identity_rows(reader, config)
            identities = validate_identity_map(map_rows, [config["request"]["api_race_id"]],
                                               expected_snapshot_id=config["id_map"]["source_snapshot_id"])
            identity: RuntimeIdentity = identities[config["request"]["api_race_id"]]
            selection = config["request"]
            # UTF16本文の展開・JSON解析分の余裕を残し、SQL側で本文送信前に総量を制限する。
            payload_budget = min(64 * 1024 ** 2, config["limits"]["memory_bytes"] // 16)
            rows = read_receipt_rows(reader, [identity], knowledge_cutoff=selection["knowledge_cutoff"],
                                     max_rows=config["limits"]["max_receipt_rows"],
                                     max_payload_bytes=max(1, payload_budget))
            check_memory(config["limits"]["memory_bytes"])
            input_digest = digest(sorted(rows, key=lambda x: (x["received_at_utc"], x["request_sha256"])))
            bundle = select_runtime_bundle(rows, identity, operation=selection["operation"], source=selection["source"],
                                           knowledge_cutoff=selection["knowledge_cutoff"], decision_cutoff=selection["decision_cutoff"],
                                           bet_type=selection["bet_type"], odds_timing=selection["odds_timing"])
            chosen = select_whole_bundle([bundle], priority=("receipt",))
            pass_result = {"preflight_digest": digest(preflight), "map_digest": map_digest,
                           "input_digest": input_digest, "selection_digest": chosen.content_digest(),
                           "selection": chosen.evidence()}
            pass_results.append(pass_result)
            pass_digests.append(digest(pass_result))
            artifact.write_json("preflight.json", {"phase": "runtime_receipt_verification", "pass": len(pass_results),
                                                     "query_count": len(reader.query_metrics), "status": "in_progress"})
            check_memory(config["limits"]["memory_bytes"])
        if pass_digests[0] != pass_digests[1]:
            raise ResearchError("source_changed", 5)
        reader.close()
        selected = pass_results[1]
        report = {"status": "passed", "run_id": artifact.run_id, "verification_scope": "receipt_only",
                  "configuration_status": config["configuration_status"],
                  "preflight": preflight, "preflight_digest": selected["preflight_digest"],
                  "map_digest": selected["map_digest"], "input_digest": selected["input_digest"],
                  "selection_digest": selected["selection_digest"],
                  "selection": {key: value for key, value in selected["selection"].items() if key != "payload_sha256"},
                  "baseline_verified": False, "overall_complete": False,
                  "quality": {"availability": "research_only", "read_consistency": "chunked_unproven", "replayability": "content_match_only"},
                  "two_pass_all_inputs_match": True, "query_metrics": reader.query_metrics}
        artifact.write_json("preflight.json", report)
        artifact.finish(overall_complete=False, baseline_verified=False, selection_digest=selected["selection_digest"],
                        verification_scope="receipt_only", configuration_status=config["configuration_status"],
                        query_metrics=reader.query_metrics)
        return report
    except ResearchError as error:
        if reader is not None:
            reader.close()
            error.details.setdefault("query_metrics", reader.query_metrics)
            error.details.setdefault("partial_diagnostics", reader.report)
        error.details.setdefault("resume_condition", "preflight/権限/版/索引か再読取差分を解消後、新しいrunで再実行する。自動再試行しない。")
        error.details.setdefault("run_id", artifact.run_id)
        artifact.manifest.update(query_metrics=reader.query_metrics if reader else [], partial_diagnostics=reader.report if reader else {})
        artifact.write_json("preflight.json", {"phase": reader.report.get("last_query_id", "before_preflight") if reader else "before_connection",
                                                 "query_count": len(reader.query_metrics) if reader else 0,
                                                 "diagnostics": reader.report if reader else {}})
        artifact.fail(error)
        raise
    except Exception as exc:
        error = ResearchError("runtime_sql_failed", 3, error_type=type(exc).__name__, run_id=artifact.run_id,
                              resume_condition="SQL境界と診断を確認後、新しいrunで再実行する。自動再試行しない。")
        if reader is not None:
            reader.close()
            error.details["query_metrics"] = reader.query_metrics
            error.details["partial_diagnostics"] = reader.report
            artifact.manifest.update(query_metrics=reader.query_metrics, partial_diagnostics=reader.report)
            artifact.write_json("preflight.json", {"phase": reader.report.get("last_query_id", "before_preflight"),
                                                     "query_count": len(reader.query_metrics), "diagnostics": reader.report})
        artifact.fail(error)
        raise error from None
