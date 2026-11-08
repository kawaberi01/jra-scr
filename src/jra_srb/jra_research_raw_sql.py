"""概要: 固定SQL版のO1/O2観測・本文を既存索引で読み、内容検証を行う。
作成日: 2026-10-15
入力: 研究専用reader、非秘密JSON設定、12桁JVレースキー、timezone付きcutoff。
出力: メモリ内の検証済み解析値と、共通run内の来歴・digest・診断。
実行例: uv run python scripts/run_jra_research.py verify-raw --config configs/research/sql_content_verified_compat_v1.json --race-key 202501050601 --cutoff 2025-01-05T10:00:00+09:00
注意事項: SELECT専用。本文・市場明細は保存しない。旧path系譜・checkpoint・strictライブは証明しない。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from .jra_research_contracts import ResearchError, canonical_json, digest, timestamp
from .jra_research_jv_parser import PARSER_VERSION, ParsedObservation
from .jra_research_raw import verify_jv_content, verify_jv_entries
from .jra_research_reader import ResearchReader
from .jra_research_resources import check_memory


POLICY = "sql_content_verified_compat_v1"
OBSERVATIONS = "market.parsed_observations"
ENTRIES = "market.parsed_entries"
CONTENTS = "raw.master_contents"
OBS_FIELDS = ("raw_record_id", "parser_version", "source_sha256", "source_bytes", "jv_race_key",
              "source_data_spec", "record_type", "data_division", "announced_at", "announced_at_status", "retrieved_at")
ENTRY_FIELDS = ("raw_record_id", "parser_version", "market", "selection_key", "odds_raw_low", "odds_raw_high",
                "odds_status_low", "odds_status_high", "odds_low_x10", "odds_high_x10", "popularity")
CONTENT_FIELDS = ("sha256", "codec", "compressed_payload", "raw_length", "record_type")
ROUTES = {
    (OBSERVATIONS, "__unified_race_sha256"): (("jv_race_key",), False),
    (OBSERVATIONS, "__unified_observation_sha256"): (("raw_record_id", "parser_version"), True),
    (ENTRIES, "__unified_observation_sha256"): (("raw_record_id", "parser_version"), False),
    (CONTENTS, "__unified_fk_5d5b09f6_sha256"): (("sha256",), False),
}


def _hash_text(value: str) -> bytes:
    """SQLのnvarchar→varbinaryと同じUTF16LE本文をSHA256へ変換する。"""
    return hashlib.sha256(value.encode("utf-16le")).digest()


def observation_hash(raw_record_id: str, parser_version: str) -> bytes:
    """既存観測索引の二重hashをbinary連結から計算する。"""
    return hashlib.sha256(_hash_text(raw_record_id) + _hash_text(parser_version)).digest()


def _hash_expression(columns: tuple[str, ...]) -> str:
    """既存finalizeのcomputed式を意味を変えず構成する。"""
    def hashed(expression):
        """UTF16/binary入力をbinary32 SHAへ変換するSQL式を返す。"""
        return "CONVERT(binary(32),HASHBYTES('SHA2_256',CONVERT(varbinary(max)," + expression + ")))"
    return hashed("[" + columns[0] + "]") if len(columns) == 1 else hashed("+".join(hashed("[" + name + "]") for name in columns))


def _expression_identity(expression: str) -> str:
    """SQL式の括弧・引用表記だけを正規化し、演算・型・列の変更は保持する。"""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(expression, read="tsql")
        tree = tree.transform(lambda node: node.this if isinstance(node, exp.Paren) else node)
        for identifier in tree.find_all(exp.Identifier):
            identifier.set("quoted", False)
        return tree.sql(dialect="tsql", normalize=True)
    except Exception:
        raise ResearchError("raw_hash_definition_unparseable", 3) from None


@dataclass(frozen=True)
class RawSQLConfig:
    """本文検証専用のsourceと物理上限を保持する。"""

    raw: dict

    @classmethod
    def load(cls, path: str | Path):
        """非秘密設定を読み、未知キー・秘密設定・不正な型を拒否する。"""
        try:
            return cls.parse(json.loads(Path(path).read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, TypeError):
            raise ResearchError("invalid_raw_config", 2) from None

    @classmethod
    def parse(cls, value: dict):
        """設定辞書のpolicy・parser・source・上限を厳密に検証する。"""
        try:
            if set(value) != {"schema_version", "profile_id", "source_policy", "parser_version", "limits"}:
                raise ValueError("keys")
            if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["profile_id"] != POLICY or value["parser_version"] != PARSER_VERSION:
                raise ValueError("version")
            policy = value["source_policy"]
            if set(policy) != {"policy_id", "parsed", "raw"} or policy["policy_id"] != POLICY:
                raise ValueError("policy")
            for name in ("parsed", "raw"):
                source = policy[name]
                if set(source) != {"source_key", "snapshot_id"} or not isinstance(source["source_key"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", source["source_key"]):
                    raise ValueError("source")
                if type(source["snapshot_id"]) is not int or source["snapshot_id"] < 1:
                    raise ValueError("snapshot")
            maxima = {"fetch_rows": 10000, "query_timeout_seconds": 90, "memory_bytes": 2147483648,
                      "max_observations_per_spec": 10000, "max_entries_per_observation": 1000,
                      "max_compressed_bytes": 262144, "max_rows_all_passes": 100000}
            if set(value["limits"]) != set(maxima) or any(type(value["limits"][k]) is not int or not 0 < value["limits"][k] <= v for k, v in maxima.items()):
                raise ValueError("limits")
            return cls(json.loads(canonical_json(value)))
        except (KeyError, TypeError, ValueError):
            raise ResearchError("invalid_raw_config", 2) from None


def _required_types(table: str) -> dict[str, tuple[str, int]]:
    """使用する列と索引列のSQL型・byte長を返す。"""
    fields = {OBSERVATIONS: OBS_FIELDS, ENTRIES: ENTRY_FIELDS, CONTENTS: CONTENT_FIELDS}[table]
    integers = {"source_bytes", "raw_length", "odds_low_x10", "odds_high_x10", "popularity"}
    result = {name: (("bigint", 8) if name in integers else ("varbinary", -1) if name == "compressed_payload" else ("nvarchar", -1)) for name in fields}
    result["__migration_source_snapshot_id"] = ("bigint", 8)
    for relation, field in ROUTES:
        if relation == table:
            result[field] = ("binary", 32)
    return result


class RawSQLReader(ResearchReader):
    """共通接続を使い、本文検証専用の固定SELECTとpreflightを提供する。"""

    def preflight(self) -> dict:
        """M1へ依存せずDB・最小権限・全source・型・computed式・索引を検査する。"""
        self.report = {"phase": "identity"}
        identity = self._small("raw_identity", "SELECT DB_NAME() database_name,IS_SRVROLEMEMBER('sysadmin') sysadmin,IS_ROLEMEMBER('db_owner') db_owner,IS_ROLEMEMBER('db_ddladmin') db_ddladmin,IS_ROLEMEMBER('db_datawriter') db_datawriter")[0]
        if identity["database_name"] != "jra_unified" or any(identity[k] != 0 for k in ("sysadmin", "db_owner", "db_ddladmin", "db_datawriter")):
            raise ResearchError("unexpected_database_or_privilege", 3)
        self.report.update(identity=identity, phase="permissions")
        scopes = [("DATABASE", "jra_unified", ("CONTROL", "ALTER ANY SCHEMA", "CREATE TABLE"))]
        scopes += [("SCHEMA", name, ("ALTER", "CONTROL")) for name in ("raw", "market", "ops")]
        scopes += [("OBJECT", name, ("SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL")) for name in (OBSERVATIONS, ENTRIES, CONTENTS, "ops.source_database", "ops.source_snapshot")]
        checks = 0
        for scope, name, permissions in scopes:
            for permission in permissions:
                rows = self._small("raw_permission", "SELECT HAS_PERMS_BY_NAME(?,?,?) permitted", (name, scope, permission))
                if len(rows) != 1 or rows[0]["permitted"] != int(permission == "SELECT"):
                    raise ResearchError("permission_contract_failed", 3, object=name, permission=permission)
                checks += 1
        self.report.update(permission_checks=checks, phase="sources")
        sources = {}
        for name in ("parsed", "raw"):
            expected = self.config.raw["source_policy"][name]
            rows = self._small("raw_source", "SELECT d.source_key,s.source_snapshot_id,s.source_database_id,s.status,s.schema_catalog_sha256 FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (expected["snapshot_id"],))
            if len(rows) != 1 or rows[0]["source_key"] != expected["source_key"] or rows[0]["status"] != "verified":
                raise ResearchError("unverified_source", 3, source=name)
            sources[name] = rows[0]
        self.report.update(sources=sources, phase="schema")
        schemas, indexes, expressions = [], [], []
        for table in (OBSERVATIONS, ENTRIES, CONTENTS):
            columns = self._small("raw_schema", "SELECT c.name,t.name type_name,c.max_length FROM sys.columns c JOIN sys.types t ON c.user_type_id=t.user_type_id WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id", (table,))
            found = {row["name"]: (row["type_name"], row["max_length"]) for row in columns}
            if any(found.get(name) != expected for name, expected in _required_types(table).items()):
                raise ResearchError("raw_schema_type_mismatch", 3, table=table)
            schemas.append({"table": table, "columns": columns})
            rows = self._small("raw_indexes", "SELECT i.name,i.is_unique,i.is_disabled,i.is_hypothetical,i.filter_definition,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
            indexes.append({"table": table, "indexes": rows})
            for (relation, field), (keys, unique) in ROUTES.items():
                if relation != table:
                    continue
                groups = {}
                for row in rows:
                    if row["is_disabled"] == 0 and row["is_hypothetical"] == 0 and row["filter_definition"] is None:
                        groups.setdefault(row["name"], []).append(row)
                if not any([r["column_name"] for r in group] == ["__migration_source_snapshot_id", field] and (not unique or all(r["is_unique"] == 1 for r in group)) for group in groups.values()):
                    raise ResearchError("missing_raw_index_route", 3, table=table, column=field)
                definitions = self._small("raw_computed", "SELECT name,definition FROM sys.computed_columns WHERE object_id=OBJECT_ID(?) AND name=?", (table, field))
                if len(definitions) != 1 or not isinstance(definitions[0]["definition"], str) or not definitions[0]["definition"]:
                    raise ResearchError("missing_raw_hash_definition", 3, table=table, column=field)
                if _expression_identity(definitions[0]["definition"]) != _expression_identity(_hash_expression(keys)):
                    raise ResearchError("unexpected_raw_hash_definition", 3, table=table, column=field)
                expressions.append({"table": table, **definitions[0]})
        isolation = self._small("raw_isolation", "SELECT snapshot_isolation_state,is_read_committed_snapshot_on FROM sys.databases WHERE name=DB_NAME()")
        if len(isolation) != 1 or isolation[0]["snapshot_isolation_state"] not in (0, 1, 2, 3):
            raise ResearchError("raw_isolation_unverified", 3)
        self.report.update(phase="complete", schema_digest=digest(schemas), index_digest=digest(indexes), computed_digest=digest(expressions),
                           isolation=isolation[0], read_consistency="snapshot_transaction" if isolation[0]["snapshot_isolation_state"] == 1 else "chunked_unproven",
                           availability="research_only", provenance_equivalence="content_verified/path_unverified")
        return self.report

    def _bounded(self, query_id: str, sql: str, params: tuple, maximum: int) -> list[dict]:
        """SELECT TOP(max+1)の全行をfetchmanyし、超過と全体上限を拒否する。"""
        if self.report.get("phase") != "complete":
            raise ResearchError("raw_preflight_required", 3)
        rows = []
        with self._cursor(query_id, sql, params) as cursor:
            names = [column[0] for column in cursor.description]
            while batch := cursor.fetchmany(self.config.raw["limits"]["fetch_rows"]):
                self.scan_rows[query_id] = self.scan_rows.get(query_id, 0) + len(batch)
                if sum(self.scan_rows.values()) > self.config.raw["limits"]["max_rows_all_passes"] or len(rows) + len(batch) > maximum:
                    raise ResearchError("raw_row_limit", 4, query_id=query_id)
                rows.extend(dict(zip(names, row, strict=True)) for row in batch)
                check_memory(self.config.raw["limits"]["memory_bytes"])
        return rows

    def observation_rows(self, race_key: str, spec: str) -> list[dict]:
        """版・race hash・元値・DataSpec・parserで全候補を有界取得する。"""
        maximum = self.config.raw["limits"]["max_observations_per_spec"]
        sql = "SELECT TOP (?) " + ",".join("[" + name + "]" for name in OBS_FIELDS)
        sql += f" FROM {OBSERVATIONS} WHERE __migration_source_snapshot_id=? AND __unified_race_sha256=CONVERT(binary(32),?) AND CONVERT(varbinary(max),jv_race_key)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?)) AND CONVERT(varbinary(max),source_data_spec)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?)) AND CONVERT(varbinary(max),parser_version)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?)) AND data_division=N'1' AND announced_at_status=N'resolved'"
        return self._bounded("raw_observations:" + spec, sql, (maximum + 1, self.config.raw["source_policy"]["parsed"]["snapshot_id"], _hash_text(race_key), race_key, spec, PARSER_VERSION), maximum)

    def entry_rows(self, observation: dict) -> list[dict]:
        """版・観測hash・元raw ID/parserで明細を有界取得する。"""
        maximum = self.config.raw["limits"]["max_entries_per_observation"]
        raw_id = observation["raw_record_id"]
        sql = "SELECT TOP (?) " + ",".join("[" + name + "]" for name in ENTRY_FIELDS)
        sql += f" FROM {ENTRIES} WHERE __migration_source_snapshot_id=? AND __unified_observation_sha256=CONVERT(binary(32),?) AND CONVERT(varbinary(max),raw_record_id)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?)) AND CONVERT(varbinary(max),parser_version)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?))"
        return self._bounded("raw_entries", sql, (maximum + 1, self.config.raw["source_policy"]["parsed"]["snapshot_id"], observation_hash(raw_id, PARSER_VERSION), raw_id, PARSER_VERSION), maximum)

    def content_row(self, sha: str) -> dict:
        """版・SHA hash・元SHAで本文を取得し、巨大payloadを転送前に拒否する。"""
        maximum = self.config.raw["limits"]["max_compressed_bytes"]
        sql = f"SELECT TOP (2) sha256,codec,raw_length,record_type,DATALENGTH(compressed_payload) compressed_bytes,CASE WHEN DATALENGTH(compressed_payload)<=? THEN compressed_payload ELSE NULL END compressed_payload FROM {CONTENTS} WHERE __migration_source_snapshot_id=? AND __unified_fk_5d5b09f6_sha256=CONVERT(binary(32),?) AND CONVERT(varbinary(max),sha256)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?))"
        rows = self._bounded("raw_content", sql, (maximum, self.config.raw["source_policy"]["raw"]["snapshot_id"], _hash_text(sha), sha), 2)
        if len(rows) != 1:
            raise ResearchError("raw_content_cardinality", 4, count=len(rows))
        row = rows[0]
        if type(row["compressed_bytes"]) is not int or not 0 < row["compressed_bytes"] <= maximum or row["compressed_payload"] is None:
            raise ResearchError("raw_compressed_byte_limit", 4)
        return row


@dataclass(frozen=True)
class VerifiedMarket:
    """本文で検証した観測をメモリ内に限定し、診断と分離して保持する。"""

    parsed: ParsedObservation
    diagnostic: dict
    source_stream_sha256: str


def _validate_request(race_key: str, cutoff: str):
    """12桁JVキーの開催日/場/番号とtimezone付きcutoffを検証する。"""
    if not isinstance(race_key, str) or not re.fullmatch(r"[0-9]{12}", race_key) or not "01" <= race_key[8:10] <= "10" or not 1 <= int(race_key[10:]) <= 12:
        raise ResearchError("invalid_raw_race_key", 2)
    try:
        date.fromisoformat(race_key[:4] + "-" + race_key[4:6] + "-" + race_key[6:8])
    except ValueError:
        raise ResearchError("invalid_raw_race_key", 2) from None
    return timestamp(cutoff)


def read_verified_market(reader: RawSQLReader, config: RawSQLConfig, race_key: str, cutoff: str, spec: str) -> VerifiedMarket:
    """cutoff以内の最新観測を選び、同時刻競合・全利用明細・本文を検証する。

    Returns:
        本文由来の解析値と、本文/明細を含まない診断。flags等はSQL値を採用しない。
    Raises:
        ResearchError: 欠落、重複、曖昧訂正、上限超過、本文・明細の不一致。
    Notes:
        旧path/metadata checkpoint、受領済み時点、旧カードcutoffの同値は検証しない。
    """
    cutoff_at = _validate_request(race_key, cutoff)
    if spec not in {"0B41", "0B42"}:
        raise ResearchError("unsupported_raw_spec", 2)
    rows = reader.observation_rows(race_key, spec)
    seen, eligible = set(), []
    for row in rows:
        raw_id = row["raw_record_id"]
        if not isinstance(raw_id, str) or not raw_id or not raw_id.isascii() or raw_id in seen:
            raise ResearchError("duplicate_or_invalid_observation_id", 4)
        seen.add(raw_id)
        if row["jv_race_key"] != race_key or row["source_data_spec"] != spec or row["parser_version"] != PARSER_VERSION or row["data_division"] != "1":
            raise ResearchError("raw_observation_key_mismatch", 4)
        if row["announced_at_status"] != "resolved":
            raise ResearchError("raw_announcement_unresolved", 4)
        announced = timestamp(row["announced_at"])
        if announced <= cutoff_at:
            eligible.append((announced, row))
    if not eligible:
        raise ResearchError("missing_raw_before_cutoff", 4, data_spec=spec)
    latest = max(at for at, _ in eligible)
    latest_rows = [row for at, row in eligible if at == latest]
    if len({row["source_sha256"] for row in latest_rows}) != 1:
        raise ResearchError("ambiguous_revision", 4, data_spec=spec)
    chosen = max(latest_rows, key=lambda row: row["raw_record_id"])
    sha = chosen["source_sha256"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ResearchError("raw_content_sha_invalid", 4)
    content, entries = reader.content_row(sha), reader.entry_rows(chosen)
    parsed = verify_jv_content(content, chosen)
    market = "win" if spec == "0B41" else "quinella"
    verify_jv_entries(parsed, entries, market)
    for row in entries:
        if row["raw_record_id"] != chosen["raw_record_id"] or row["parser_version"] != PARSER_VERSION:
            raise ResearchError("raw_entry_identity_mismatch", 4)
    source_stream = digest({"observations": sorted(rows, key=canonical_json), "entries": sorted(entries, key=canonical_json),
                            "content": {k: v for k, v in content.items() if k != "compressed_payload"},
                            "compressed_sha256": hashlib.sha256(bytes(content["compressed_payload"])).hexdigest()})
    diagnostic = {"data_spec": spec, "market": market, "source_sha256": sha, "raw_record_id": chosen["raw_record_id"],
                  "announced_at_utc": latest.isoformat(), "candidate_count": len(rows), "eligible_count": len(eligible),
                  "latest_count": len(latest_rows), "verified_entry_count": sum(e.market == market for e in parsed.entries),
                  "codec": content["codec"], "raw_length": content["raw_length"], "parsed_sha256": digest(asdict(parsed)),
                  "metadata_value_source": "reparsed_body_only"}
    return VerifiedMarket(parsed, diagnostic, source_stream)


def collect_raw_verification(reader: RawSQLReader, config: RawSQLConfig, race_key: str, cutoff: str) -> dict:
    """全利用列と圧縮本文digestを二巡照合し、検証限定の非秘密診断を返す。"""
    prior, prior_metadata = None, digest(reader.report)
    with reader.read_transaction():
        for _ in range(2):
            values = [read_verified_market(reader, config, race_key, cutoff, spec) for spec in ("0B41", "0B42")]
            stream = digest({"source_streams": [value.source_stream_sha256 for value in values], "selected": [value.diagnostic for value in values]})
            after = reader.preflight()
            if digest(after) != prior_metadata or prior is not None and prior != stream:
                raise ResearchError("source_changed", 5)
            prior = stream
    return {"profile_id": POLICY, "race_key": race_key, "cutoff_utc": timestamp(cutoff).isoformat(),
            "verification_scope": "selected_O1_win_O2_quinella_content_and_parsed_entries", "selected": [value.diagnostic for value in values],
            "input_content_sha256": prior, "read_passes": 2, "scan_rows_all_passes": dict(reader.scan_rows),
            "availability": "research_only", "provenance_equivalence": "content_verified/path_unverified",
            "checkpoint_equivalence": "unverified", "materializer_eligible": False, "strict_live_replay_eligible": False,
            "overall_complete": False}


def execute_raw_verification(config_path: str | Path, race_key: str, cutoff: str) -> dict:
    """新規runへ診断だけを保存し、SQL例外時も失敗証跡と再開条件を残す。"""
    from .jra_research_artifacts import RunArtifacts
    config = RawSQLConfig.load(config_path)
    artifacts = RunArtifacts({**config.raw, "request": {"race_key": race_key, "cutoff": cutoff}}, "verify-raw")
    reader = None
    try:
        _validate_request(race_key, cutoff)
        with RawSQLReader(config) as reader:
            report = reader.preflight()
            artifacts.write_json("preflight.json", report)
            output = collect_raw_verification(reader, config, race_key, cutoff)
            artifacts.manifest.update(query_metrics=reader.query_metrics, provenance=reader.report,
                                      input_content_sha256=output["input_content_sha256"])
        artifacts.write_json("metrics.json", output)
        artifacts.finish(metrics_sha256=digest(output), overall_complete=False, materializer_eligible=False)
        return {"status": "passed", "run_id": artifacts.run_id, **output}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("raw_verification_failed", 4, error_type=type(error).__name__)
        if reader is not None:
            artifacts.manifest.update(query_metrics=reader.query_metrics, scan_rows_all_passes=reader.scan_rows)
            artifacts.write_json("preflight.json", reader.report)
        safe.details.setdefault("resume_condition", "原因・権限・schema・source・本文/明細契約を確認後、明示的に新runを開始する。自動再試行しない。")
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None
