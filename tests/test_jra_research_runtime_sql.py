"""概要: runtime SQLのpreflight、設定、二巡処理の境界を合成入力で検証する。
作成日: 2026-10-16
入力: 合成設定、sys catalog結果、SQL reader stub。
出力: pytest結果。DB接続・HTTP・本文成果物なし。
実行例: uv run pytest -q tests/test_jra_research_runtime_sql.py
注意事項: 実DBの権限・定義・索引は別途preflightで検証する。
"""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb import jra_research_artifacts as artifacts
from jra_srb import jra_research_runtime_sql as runtime_sql
from jra_srb.jra_research_contracts import canonical_json
from jra_srb.models import RaceResult
from jra_srb.jra_research_runtime_sql import _config, _identity_rows, _preflight


def config_value():
    """runtime設定契約を満たす合成辞書を返す。"""
    return {"schema_version": 1, "profile_id": "runtime_receipt_v1", "configuration_status": "ready_for_verification",
            "source_policy": {"policy_id": "runtime_receipt_v1", "source_key": "analysis-current", "snapshot_id": 34},
            "id_map": {"source_snapshot_id": 34, "source_relation": "live.races", "source_original_id": "opaque-id"},
            "request": {"api_race_id": "opaque-id", "source": "official", "operation": "race_result",
                        "knowledge_cutoff": "2026-10-15T12:00:00+00:00", "decision_cutoff": None,
                        "bet_type": None, "odds_timing": None, "race_date": "2026-10-14",
                        "course": "tokyo", "race_no": 1},
            "limits": {"max_receipt_rows": 1000, "memory_bytes": 1024 ** 3}}


def _validated_config(value):
    """一時ファイルを作らず設定検証関数へ合成辞書を渡す。"""
    with patch("jra_srb.jra_research_runtime_sql.json.loads", return_value=value), patch(
        "jra_srb.jra_research_runtime_sql.Path.read_text", return_value="{}"
    ):
        return _config("unused.json")


def test_config_checks_profile_policy_date_timezone_and_fetch_limit():
    """source policy、暦日、timezone、最大fetch行数を接続前に検査する。"""
    value = config_value()
    value["request"]["knowledge_cutoff"] = "2026-10-15T12:00:00"
    with pytest.raises(ResearchError, match="invalid_request_config"):
        _validated_config(value)
    value = config_value()
    value["source_policy"]["policy_id"] = "other"
    with pytest.raises(ResearchError, match="invalid_source_config"):
        _validated_config(value)
    value = config_value()
    value["limits"]["max_receipt_rows"] = 10000
    with pytest.raises(ResearchError, match="invalid_resource_limit"):
        _validated_config(value)


def test_config_rejects_unknown_keys_and_incomplete_market():
    """未知設定とodds市場条件の省略を拒否する。"""
    value = config_value()
    value["unexpected"] = True
    with pytest.raises(ResearchError, match="invalid_config_keys"):
        _validated_config(value)
    value = config_value()
    value["request"]["operation"] = "odds"
    with pytest.raises(ResearchError, match="explicit_market_required"):
        _validated_config(value)


@pytest.mark.parametrize("status", [[], {}, None, True, 1])
def test_configuration_status_type_errors_are_safe_config_failures(status):
    """配列/辞書などの不正状態値もTypeErrorではなく固定設定エラーで拒否する。"""
    value = config_value()
    value["configuration_status"] = status
    with pytest.raises(ResearchError, match="invalid_config_version"):
        _validated_config(value)


def _column(name, type_name, size, nullable, computed=False, scale=0):
    """catalog column fixtureを作る。"""
    return {"name": name, "type_name": type_name, "max_length": size, "is_nullable": nullable,
            "is_computed": computed, "scale": scale}


class PreflightReader:
    """SQL catalogを再現し、preflightの固定queryを合成検査するreader。"""

    def __init__(self, *, bad_expression=False, bad_unique=False, scale=7):
        """catalog異常を指定したpreflight fixtureを初期化する。"""
        self.bad_expression, self.bad_unique, self.scale = bad_expression, bad_unique, scale
        self.query_metrics = []
        self.report = {}

    def _small(self, query_id, sql, params=()):
        """query_idごとのcatalog・権限・source行を返す。"""
        if query_id == "runtime:identity":
            return [{"database_name": "jra_unified", "database_user": "jra_reader", "sysadmin": 0,
                     "db_owner": 0, "db_ddladmin": 0, "db_datawriter": 0}]
        if query_id == "runtime:permission":
            table, scope, permission = params
            return [{"permitted": int(permission == "SELECT" and scope == "OBJECT")}]
        if query_id == "runtime:source":
            return [{"source_key": "analysis-current", "source_snapshot_id": 34,
                     "source_database_id": 1, "status": "verified"}]
        if query_id == "runtime:columns":
            if params[0] == "api_runtime.write_receipts":
                fields = [_column("request_sha256", "binary", 32, False), _column("operation", "nvarchar", 128, False),
                          _column("race_id", "nvarchar", -1, False), _column("payload_json", "nvarchar", -1, False),
                          _column("received_at_utc", "datetime2", 8, False, scale=self.scale),
                          _column("race_sha256", "binary", 32, True, True)]
            else:
                fields = [_column("source_snapshot_id", "bigint", 8, False), _column("source_relation", "varchar", 128, False),
                          _column("source_original_id", "nvarchar", 256, False), _column("api_race_id", "nvarchar", 128, True),
                          _column("race_date", "date", 3, True), _column("venue_code", "nvarchar", 32, True),
                          _column("race_no", "int", 4, True), _column("unified_race_id", "nvarchar", 256, False),
                          _column("mapping_status", "varchar", 24, False), _column("evidence_json", "nvarchar", -1, False),
                          _column("source_row_sha256", "binary", 32, False),
                          _column("__unified_original_sha256", "binary", 32, True, True)]
            return fields
        if query_id == "runtime:computed":
            table, name = params
            # 実migration/finalizeの独立したliteralで検証し、本体helperとの循環を避ける。
            expression = ("CONVERT(binary(32),HASHBYTES('SHA2_256',race_id))" if name == "race_sha256"
                          else "CONVERT(binary(32),HASHBYTES('SHA2_256',CONVERT(varbinary(max),[source_original_id])))")
            if self.bad_expression:
                expression = "CONVERT(binary(32), HASHBYTES('SHA2_256', CONVERT(varbinary(max), 'race_id source_original_id')))"
            return [{"name": name, "definition": expression, "is_persisted": 1}]
        if query_id == "runtime:indexes":
            table = params[0]
            if table == "api_runtime.write_receipts":
                rows = [{"name": "PK_receipt", "is_unique": 1 if not self.bad_unique else 0,
                         "is_disabled": 0, "is_hypothetical": 0, "filter_definition": None,
                         "column_name": "request_sha256", "key_ordinal": 1}]
                rows.extend([{"name": "IX_receipt_race", "is_unique": 0, "is_disabled": 0,
                              "is_hypothetical": 0, "filter_definition": None, "column_name": col,
                              "key_ordinal": ordinal} for ordinal, col in enumerate(("race_sha256", "received_at_utc"), 1)])
                return rows
            return [{"name": "UX_map_origin", "is_unique": 1, "is_disabled": 0, "is_hypothetical": 0,
                     "filter_definition": None, "column_name": col, "key_ordinal": ordinal}
                    for ordinal, col in enumerate(("source_snapshot_id", "source_relation", "__unified_original_sha256"), 1)]
        raise AssertionError(f"Unexpected query id: {query_id}")


def test_preflight_accepts_exact_hash_ddl_and_required_unique_routes():
    """DDL完全一致、request hash一意索引とmap point lookup索引を受け入れる。"""
    result = _preflight(PreflightReader(), config_value())
    assert result["receipt_route"] == "race_sha256+race_id_exact+cutoff"
    assert result["source"]["status"] == "verified"


@pytest.mark.parametrize("reader,reason", [
    (PreflightReader(bad_expression=True), "unexpected_hash_definition"),
    (PreflightReader(bad_unique=True), "missing_index_route"),
    (PreflightReader(scale=6), "unexpected_column_definition"),
])
def test_preflight_rejects_near_miss_hash_indexes_and_datetime_scale(reader, reason):
    """類似SHA式、非unique request key、datetime2(6)をpreflight拒否する。"""
    with pytest.raises(ResearchError, match=reason):
        _preflight(reader, config_value())


class IdentityReader:
    """有界map範囲とpoint lookup結果を返す合成reader。"""

    def __init__(self, *, wrong_original=False, duplicate_reverse=False):
        """対象IDと逆引き重複を調整して初期化する。"""
        self.wrong_original, self.duplicate_reverse = wrong_original, duplicate_reverse
        self.calls = []
        self.report = {}
        self.query_metrics = []

    def _small(self, query_id, sql, params=()):
        """point lookupと逆一意用範囲queryの条件を検証し合成行を返す。"""
        self.calls.append(query_id)
        if query_id == "runtime:id_map_point_lookup":
            assert "__unified_original_sha256=CONVERT(binary(32),?)" in sql
            assert "CONVERT(varbinary(max),source_original_id)" in sql
            assert params[:2] == (34, "live.races")
            assert params[2] == hashlib.sha256("opaque-id".encode("utf-16le")).digest()
            assert params[3] == "opaque-id"
            return [{"source_snapshot_id": 34, "source_relation": "live.races", "source_original_id": "opaque-id",
                     "api_race_id": "opaque-id", "race_date": "2026-10-14", "venue_code": "tokyo", "race_no": 1,
                     "unified_race_id": "unified:race", "mapping_status": "verified", "evidence_json": '{"method":"verified"}',
                     "source_row_sha256": "ab" * 32}]
        assert query_id == "runtime:id_map_lookup"
        assert "source_snapshot_id=? AND source_relation=?" in sql
        assert params == (10001, 34, "live.races")
        rows = [{"source_snapshot_id": 34, "source_relation": "live.races", "source_original_id": "opaque-id",
                 "api_race_id": "opaque-id", "race_date": "2026-10-14", "venue_code": "tokyo", "race_no": 1,
                 "unified_race_id": "unified:race", "mapping_status": "verified"}]
        if self.wrong_original:
            rows[0]["source_original_id"] = "different-id"
        if self.duplicate_reverse:
            rows.append({**rows[0], "source_original_id": "second", "api_race_id": "another-api"})
        return rows


def test_map_point_lookup_checks_hash_original_and_evidence_then_reverse_uniqueness():
    """hash付きpoint lookupと元ID/evidence、版範囲の逆一意を照合する。"""
    reader = IdentityReader()
    mapped, map_digest = _identity_rows(reader, config_value())
    assert mapped[0]["unified_race_id"] == "unified:race"
    assert len(map_digest) == 64
    assert reader.calls == ["runtime:id_map_point_lookup", "runtime:id_map_lookup"]


def test_map_refuses_wrong_source_original_id_and_reverse_collision():
    """別元IDや同じunified IDへの別API登録を拒否する。"""
    with pytest.raises(ResearchError, match="unresolved_id"):
        _identity_rows(IdentityReader(wrong_original=True), config_value())
    with pytest.raises(ResearchError, match="ambiguous_id"):
        _identity_rows(IdentityReader(duplicate_reverse=True), config_value())


@pytest.mark.parametrize("column,damage", [
    ("evidence_json", {"max_length": 256}),
    ("source_row_sha256", {"type_name": "varbinary"}),
    ("source_row_sha256", {"is_nullable": True}),
])
def test_preflight_validates_all_used_identity_evidence_columns(column, damage):
    """実際に読む証跡本文と元行SHAの型・長さ・NULL条件を検査する。"""
    reader = PreflightReader()
    original = reader._small

    def damaged(query_id, sql, params=()):
        """対象証跡列だけを壊したcatalogを返す。"""
        rows = original(query_id, sql, params)
        if query_id == "runtime:columns" and params[0] == "history.race_identity_map":
            rows = [{**row, **damage} if row["name"] == column else row for row in rows]
        return rows

    reader._small = damaged
    with pytest.raises(ResearchError, match="unexpected_column_definition"):
        _preflight(reader, config_value())


def result_receipt():
    """実writerと同じhashを持つ、SQL入口用の合成完全結果束を返す。"""
    body = RaceResult(race_id="opaque-id", source="official", fetched_at="2026-10-14T10:00:00+00:00",
                      results=[{"rank": "1", "horse_no": "1", "horse_name": "A"}],
                      payouts=[{"bet_type": "win", "combination": "1", "payout": "230"}]).model_dump(mode="json")
    business = deepcopy(body)
    business.pop("cache_hit", None)
    business.pop("meta", None)
    key = hashlib.sha256(("race_result\nopaque-id\n" + canonical_json(business)).encode()).digest()
    return {"request_sha256": key, "operation": "race_result", "race_id": "opaque-id",
            "received_at_utc": "2026-10-15T10:00:00.1234567", "payload_json": canonical_json(body)}


class ExecutionReader(PreflightReader):
    """実preflight/map/receipt adapterを通す二巡SQL境界の合成reader。"""

    def __init__(self, *, change=None, missing_definition=False, unexpected=False):
        """第二巡の改変または第一巡の境界障害を指定する。"""
        super().__init__()
        self.change, self.missing_definition, self.unexpected = change, missing_definition, unexpected
        self.pass_no = self.closed = self.receipt_queries = 0

    def __enter__(self):
        """接続開始の代わりに自身を返す。"""
        return self

    def close(self):
        """接続close回数を記録する。"""
        self.closed += 1

    def _small(self, query_id, sql, params=()):
        """実検査用catalogとmapを返し、指定時は第二巡だけ変更する。"""
        self.query_metrics.append({"query_id": query_id, "status": "passed"})
        if query_id == "runtime:identity":
            self.pass_no += 1
        if self.unexpected:
            raise RuntimeError("SECRET-CONNECTION-STRING")
        if query_id.startswith("runtime:id_map"):
            rows = IdentityReader()._small(query_id, sql, params)
            if self.change == "map" and self.pass_no == 2 and query_id.endswith("point_lookup"):
                rows[0]["evidence_json"] = '{"method":"changed"}'
            return rows
        rows = super()._small(query_id, sql, params)
        if query_id == "runtime:computed" and self.missing_definition:
            rows[0]["definition"] = None
        if query_id == "runtime:source" and self.change == "source" and self.pass_no == 2:
            rows[0]["source_database_id"] = 2
        return rows

    @contextmanager
    def _cursor(self, query_id, sql, params):
        """有界SQLを検査し、本文上限のSQL側NULL置換を再現する。"""
        self.receipt_queries += 1
        assert query_id == "runtime:receipt_by_race_cutoff"
        assert "FROM (SELECT TOP (?)" in sql and "SUM(CONVERT(bigint,DATALENGTH(payload_json))) OVER ()<=?" in sql
        assert params[1] == 1001
        assert params[2] == hashlib.sha256("opaque-id".encode("utf-16le")).digest()
        row = result_receipt()
        rows = [row]
        if self.change == "unselected_receipt":
            rows.append({**row, "request_sha256": bytes.fromhex("cd" * 32), "operation": "race_card",
                         "payload_json": "unused-first" if self.pass_no == 1 else "unused-changed"})
        if self.change == "oversize":
            row["payload_json"] = None
        names = list(row) + ["payload_byte_count"]
        values = [tuple(item[name] for name in row) + (len((item["payload_json"] or "").encode("utf-16le")),) for item in rows]

        class Cursor:
            """合成DB cursorの列定義と有界fetchを提供する。"""

            description = [(name,) for name in names]

            def fetchmany(self, count):
                """1万件以下の要求だけを返す。"""
                assert count <= 10000
                return values[:count]

        yield Cursor()


def execution_setup(tmp_path, monkeypatch, reader, *, example=False):
    """新規一時runだけを許可し、実SQL/実成果物を使わない実行環境を準備する。"""
    value = config_value()
    if example:
        value["configuration_status"] = "example_only"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(artifacts, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(artifacts, "code_identity", lambda: {})
    monkeypatch.setattr(runtime_sql, "ResearchReader", lambda config: reader)
    return path


@pytest.mark.parametrize("example", [False, True])
def test_execute_two_passes_preserve_receipt_only_scope_and_no_payload(tmp_path, monkeypatch, example):
    """実adapterの二巡一致を記録し、例示設定を明示してbaselineと全体を未受入にする。"""
    reader = ExecutionReader()
    path = execution_setup(tmp_path, monkeypatch, reader, example=example)
    report = runtime_sql.execute_runtime_verification(path)
    assert reader.pass_no == reader.receipt_queries == 2 and reader.closed == 1
    assert report["verification_scope"] == "receipt_only" and report["two_pass_all_inputs_match"]
    assert report["baseline_verified"] is False and report["overall_complete"] is False
    assert report["configuration_status"] == ("example_only" if example else "ready_for_verification")
    assert report["quality"]["replayability"] == "content_match_only"
    output = tmp_path / "runs" / report["run_id"]
    assert {p.name for p in output.iterdir()} == {"config.json", "manifest.json", "preflight.json"}
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["status"] == "complete"
    assert "payouts" not in "".join(p.read_text(encoding="utf-8") for p in output.iterdir())


@pytest.mark.parametrize("change", ["source", "map", "unselected_receipt"])
def test_execute_detects_second_pass_source_map_and_unused_receipt_change(tmp_path, monkeypatch, change):
    """選択しないreceiptを含む利用入力の差分も拒否し、二巡以上再試行しない。"""
    reader = ExecutionReader(change=change)
    path = execution_setup(tmp_path, monkeypatch, reader)
    with pytest.raises(ResearchError, match="source_changed") as raised:
        runtime_sql.execute_runtime_verification(path)
    assert reader.pass_no == reader.receipt_queries == 2 and reader.closed == 1
    output = tmp_path / "runs" / raised.value.details["run_id"]
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["status"] == "failed"
    assert raised.value.details["resume_condition"]


@pytest.mark.parametrize("missing,unexpected,change,reason", [
    (True, False, None, "missing_hash_definition"),
    (False, True, None, "runtime_sql_failed"),
    (False, False, "oversize", "receipt_payload_limit"),
])
def test_execute_stops_and_preserves_failure_diagnostics_without_secret(tmp_path, monkeypatch, missing, unexpected, change, reason):
    """定義非可視/境界例外/過大本文で停止し、固定理由とquery診断を秘密なしで残す。"""
    reader = ExecutionReader(change=change, missing_definition=missing, unexpected=unexpected)
    path = execution_setup(tmp_path, monkeypatch, reader)
    with pytest.raises(ResearchError, match=reason) as raised:
        runtime_sql.execute_runtime_verification(path)
    assert reader.closed == 1 and reader.pass_no == 1
    assert reader.receipt_queries == (1 if change == "oversize" else 0)
    output = tmp_path / "runs" / raised.value.details["run_id"]
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert failure["reason"] == reason and failure["details"]["query_metrics"]
    assert failure["details"]["partial_diagnostics"]["last_query_id"]
    assert "SECRET-CONNECTION-STRING" not in "".join(p.read_text(encoding="utf-8") for p in output.iterdir())
