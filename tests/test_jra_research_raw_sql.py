"""概要: SQL本文検証のsource・索引・時点選択・二巡・保存境界を確認する。
作成日: 2026-10-15
入力: 合成本文とSQL cursor/metadataの代替fixture。
出力: pytest結果。実SQL・HTTP・旧DBは使用しない。
実行例: uv run pytest -q tests/test_jra_research_raw_sql.py
注意事項: run出力はpytest一時領域に限定する。
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import zlib

import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_jv_parser import PARSER_VERSION, parse_record
from jra_srb import jra_research_raw_sql as raw_sql


@pytest.fixture
def config():
    """非秘密の実設定を独立コピーで返す。"""
    return raw_sql.RawSQLConfig.load(Path(__file__).parents[1] / "configs/research/sql_content_verified_compat_v1.json")


def body(spec):
    """O1/O2の少数明細を持つ本文を作る。"""
    value = bytearray(b" " * (962 if spec == "0B41" else 2042))
    value[:2] = b"O1" if spec == "0B41" else b"O2"
    value[2:3], value[3:11], value[11:27] = b"1", b"20250105", b"2025010506010101"
    value[27:35], value[35:39] = b"01050930", b"1818"
    if spec == "0B41":
        value[39:43], value[43:51] = b"1111", b"01002501"
    else:
        value[39:40], value[40:53] = b"1", b"0102000450001"
    value[-2:] = b"\r\n"
    return bytes(value)


class MemoryReader:
    """本文と明細をメモリで返し、取得の副作用を記録する。"""

    def __init__(self, config):
        """二券種の正しい合成観測を構築する。"""
        self.config, self.scan_rows, self.query_metrics = config, {}, []
        self.report = {"phase": "complete", "sources": {"parsed": 30, "raw": 29}}
        self.observations, self.contents, self.entries = {}, {}, {}
        self.preflight_calls, self.content_calls = 0, 0
        for spec in ("0B41", "0B42"):
            data = body(spec)
            parsed = parse_record(data, spec, "202501050601")
            sha = hashlib.sha256(data).hexdigest()
            raw_id = "raw-" + spec
            observation = {"raw_record_id": raw_id, "parser_version": PARSER_VERSION, "source_sha256": sha,
                "source_bytes": len(data), "jv_race_key": "202501050601", "source_data_spec": spec,
                "record_type": parsed.record_type, "data_division": "1", "announced_at": parsed.announced_at,
                "announced_at_status": "resolved", "retrieved_at": "2025-01-06T00:00:00+09:00"}
            compressed = zlib.compress(data)
            self.observations[spec] = [observation]
            self.contents[sha] = {"sha256": sha, "codec": "zlib", "raw_length": len(data), "record_type": parsed.record_type,
                                  "compressed_bytes": len(compressed), "compressed_payload": compressed}
            self.entries[raw_id] = [{"raw_record_id": raw_id, "parser_version": PARSER_VERSION, **asdict(entry)} for entry in parsed.entries]

    def preflight(self):
        """検査済みmetadataを同じ内容で返す。"""
        self.preflight_calls += 1
        return self.report

    @contextmanager
    def read_transaction(self):
        """テスト内の二巡境界を提供する。"""
        yield

    def observation_rows(self, race_key, spec):
        """指定券種の観測行を返す。"""
        return deepcopy(self.observations[spec])

    def content_row(self, sha):
        """本文読取回数を数えてコピーを返す。"""
        self.content_calls += 1
        return deepcopy(self.contents[sha])

    def entry_rows(self, observation):
        """採用観測の明細を返す。"""
        return deepcopy(self.entries[observation["raw_record_id"]])


def test_content_verification_two_passes_and_no_payload(config):
    """二巡の本文/明細一致と未証明保証の明示を確認する。"""
    reader = MemoryReader(config)
    output = raw_sql.collect_raw_verification(reader, config, "202501050601", "2025-01-05T10:00:00+09:00")
    assert output["read_passes"] == 2 and reader.content_calls == 4
    assert output["materializer_eligible"] is False and output["checkpoint_equivalence"] == "unverified"
    assert output["strict_live_replay_eligible"] is False and output["overall_complete"] is False
    serialized = json.dumps(output)
    assert "compressed_payload" not in serialized and "odds_low_x10" not in serialized
    assert {row["market"] for row in output["selected"]} == {"win", "quinella"}


def test_cutoff_is_timezone_aware_and_not_retrieval_time(config):
    """同一UTCのcutoffを受け入れ、事後受領をstrict保証へ昇格しない。"""
    reader = MemoryReader(config)
    result = raw_sql.read_verified_market(reader, config, "202501050601", "2025-01-05T00:30:00+00:00", "0B41")
    assert result.parsed.starter_count == 18
    with pytest.raises(ResearchError, match="missing_raw_before_cutoff"):
        raw_sql.read_verified_market(reader, config, "202501050601", "2025-01-05T00:29:59+00:00", "0B41")


def test_latest_timestamp_conflict_stops_before_body(config):
    """同時刻の異本文をID順で黙って選ばない。"""
    reader = MemoryReader(config)
    alternate = deepcopy(reader.observations["0B41"][0])
    alternate.update(raw_record_id="other", source_sha256="f" * 64)
    reader.observations["0B41"].append(alternate)
    with pytest.raises(ResearchError, match="ambiguous_revision"):
        raw_sql.read_verified_market(reader, config, "202501050601", "2025-01-05T10:00:00+09:00", "0B41")
    assert reader.content_calls == 0


def test_after_cutoff_revision_does_not_replace_selected(config):
    """cutoff後の訂正を予測時点へ遡及採用しない。"""
    reader = MemoryReader(config)
    alternate = deepcopy(reader.observations["0B41"][0])
    alternate.update(raw_record_id="later", source_sha256="f" * 64, announced_at="2025-01-05T10:01:00+09:00")
    reader.observations["0B41"].append(alternate)
    result = raw_sql.read_verified_market(reader, config, "202501050601", "2025-01-05T10:00:00+09:00", "0B41")
    assert result.diagnostic["raw_record_id"] == "raw-0B41"


@pytest.mark.parametrize("damage", ["duplicate", "marker", "codec", "sha", "entry_identity", "unresolved"])
def test_invalid_sources_stop(config, damage):
    """不正本文・明細・観測を内容出力なしで拒否する。"""
    reader = MemoryReader(config)
    observed = reader.observations["0B41"][0]
    if damage == "duplicate":
        reader.observations["0B41"].append(deepcopy(observed))
    elif damage == "marker":
        reader.entries[observed["raw_record_id"]][0]["odds_status_low"] = "blank"
    elif damage == "codec":
        reader.contents[observed["source_sha256"]]["codec"] = "brotli"
    elif damage == "sha":
        reader.contents[observed["source_sha256"]]["compressed_payload"] = zlib.compress(b"x" * 962)
    elif damage == "entry_identity":
        reader.entries[observed["raw_record_id"]][0]["raw_record_id"] = "wrong"
    else:
        observed["announced_at_status"] = "unresolved"
    with pytest.raises(ResearchError):
        raw_sql.read_verified_market(reader, config, "202501050601", "2025-01-05T10:00:00+09:00", "0B41")


def test_source_change_in_unused_market_is_detected(config):
    """二巡間の全取得列変更は採用単勝値が同じでも停止する。"""
    reader = MemoryReader(config)
    original = reader.preflight
    def changing_preflight():
        """一巡後に返却済み観測metadataを変える。"""
        result = original()
        reader.observations["0B41"][0]["retrieved_at"] = "2025-01-07T00:00:00+09:00"
        return result
    reader.preflight = changing_preflight
    with pytest.raises(ResearchError, match="source_changed"):
        raw_sql.collect_raw_verification(reader, config, "202501050601", "2025-01-05T10:00:00+09:00")


@pytest.mark.parametrize("field,value", [("snapshot_id", True), ("snapshot_id", 0), ("source_key", "secret;server=x")])
def test_invalid_config_source(config, field, value):
    """曖昧型・秘密文字列をsourceとして受け入れない。"""
    raw = deepcopy(config.raw)
    raw["source_policy"]["raw"][field] = value
    with pytest.raises(ResearchError, match="invalid_raw_config"):
        raw_sql.RawSQLConfig.parse(raw)


def test_hash_matches_existing_binary_concatenation():
    """区切り文字付き連結やUTF8へ誤置換しない。"""
    expected = hashlib.sha256(hashlib.sha256("a".encode("utf-16le")).digest() + hashlib.sha256("b".encode("utf-16le")).digest()).digest()
    assert raw_sql.observation_hash("a", "b") == expected
    expression = raw_sql._hash_expression(("raw_record_id", "parser_version"))
    assert raw_sql._expression_identity("(" + expression + ")") == raw_sql._expression_identity(expression)
    assert raw_sql._expression_identity(expression.replace("varbinary(max)", "varbinary(8)")) != raw_sql._expression_identity(expression)


def test_receipt_hash_definition_ignores_identifier_brackets_only():
    """実DDLの角括弧を同一視し、入力型・列名・hash変更は拒否する。"""
    actual = "(CONVERT([binary](32),hashbytes('SHA2_256',[race_id])))"
    expected = "CONVERT(binary(32),HASHBYTES('SHA2_256',race_id))"
    assert raw_sql._expression_identity(actual) == raw_sql._expression_identity(expected)
    for changed in (expected.replace("race_id", "source_original_id"),
                    expected.replace("SHA2_256", "SHA1"),
                    expected.replace("race_id", "CONVERT(varchar(max),race_id)")):
        assert raw_sql._expression_identity(actual) != raw_sql._expression_identity(changed)


class MetadataReader(raw_sql.RawSQLReader):
    """SQLを使わずpreflightの厳密ゲートを検証する。"""

    def __init__(self, config, damage=None):
        """metadata不正箇所だけを指定できるようにする。"""
        super().__init__(config)
        self.damage = damage

    def _small(self, query_id, sql, params=()):
        """query_idに対応した最小の既存metadataを返す。"""
        if query_id == "raw_identity":
            return [{"database_name": "jra_unified", "sysadmin": 0, "db_owner": 0, "db_ddladmin": 0, "db_datawriter": 0}]
        if query_id == "raw_permission":
            return [{"permitted": None if self.damage == "permission" else int(params[2] == "SELECT")}]
        if query_id == "raw_source":
            name = "parsed" if params[0] == self.config.raw["source_policy"]["parsed"]["snapshot_id"] else "raw"
            source = self.config.raw["source_policy"][name]
            return [{"source_key": source["source_key"], "source_snapshot_id": source["snapshot_id"], "source_database_id": 1,
                     "status": "loading" if self.damage == "source" else "verified", "schema_catalog_sha256": "a" * 64}]
        if query_id == "raw_isolation":
            return [{"snapshot_isolation_state": 0, "is_read_committed_snapshot_on": 0}]
        table = params[0]
        if query_id == "raw_schema":
            return [{"name": key, "type_name": "int" if self.damage == "type" else value[0], "max_length": value[1]} for key, value in raw_sql._required_types(table).items()]
        if query_id == "raw_indexes":
            rows = []
            for (relation, field), (_, unique) in raw_sql.ROUTES.items():
                if relation == table:
                    for ordinal, column in enumerate(("__migration_source_snapshot_id", field), 1):
                        rows.append({"name": field, "is_unique": int(unique), "is_disabled": int(self.damage == "disabled"),
                            "is_hypothetical": 0, "filter_definition": "x=1" if self.damage == "filter" else None,
                            "column_name": column, "key_ordinal": ordinal})
            return rows
        if query_id == "raw_computed":
            field = params[1]
            expression = raw_sql._hash_expression(raw_sql.ROUTES[table, field][0])
            return [{"name": field, "definition": None if self.damage == "hidden" else expression.replace("SHA2_256", "SHA1") if self.damage == "definition" else expression}]
        raise AssertionError(query_id)


def test_independent_preflight_validates_all_routes(config):
    """M1の版/build manifestを使わずraw/parsed全routeを検査する。"""
    report = MetadataReader(config).preflight()
    assert report["phase"] == "complete" and report["permission_checks"] > 30
    assert set(report["sources"]) == {"raw", "parsed"}


@pytest.mark.parametrize("damage", ["permission", "source", "type", "disabled", "filter", "hidden", "definition"])
def test_independent_preflight_fails_closed(config, damage):
    """権限/型/版/索引/定義不明を成功扱いにしない。"""
    with pytest.raises(ResearchError):
        MetadataReader(config, damage).preflight()


def test_sql_routes_are_parameterized_and_bounded(config):
    """巨大表全走査へ落とさずhash・元値・版とTOPを固定する。"""
    reader = raw_sql.RawSQLReader(config)
    captured = []
    def capture(query_id, sql, params, maximum):
        """実行の代わりにSQL契約だけを収集する。"""
        captured.append((query_id, sql, params, maximum))
        return []
    reader._bounded = capture
    reader.observation_rows("202501050601", "0B41")
    reader.entry_rows({"raw_record_id": "raw-id"})
    with pytest.raises(ResearchError, match="raw_content_cardinality"):
        reader.content_row("a" * 64)
    for _, sql, params, _ in captured:
        assert "SELECT TOP" in sql and "__migration_source_snapshot_id=?" in sql
        assert "CONVERT(binary(32),?)" in sql and "CONVERT(varbinary(max),CONVERT(nvarchar(max),?))" in sql
        assert "202501050601" not in sql and "raw-id" not in sql
    assert "DATALENGTH" in captured[-1][1] and "CASE WHEN" in captured[-1][1]


def test_run_failure_closes_and_records_without_secret(config, tmp_path, monkeypatch):
    """preflight失敗でも接続close・秘密除去・失敗manifestを残す。"""
    from jra_srb import jra_research_artifacts
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config.raw), encoding="utf-8")
    monkeypatch.setattr(jra_research_artifacts, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(jra_research_artifacts, "code_identity", lambda: {})
    state = {"closed": False}
    class FailingReader:
        """接続後のmetadata不足を模擬する。"""
        def __init__(self, config):
            """最小の非秘密診断を用意する。"""
            self.report, self.query_metrics, self.scan_rows = {"phase": "schema"}, [], {}
        def __enter__(self):
            """接続所有者を返す。"""
            return self
        def __exit__(self, *args):
            """例外でもcloseを記録する。"""
            state["closed"] = True
        def preflight(self):
            """readerで定義を確認できない状態を返す。"""
            raise ResearchError("missing_raw_hash_definition", 3)
    monkeypatch.setattr(raw_sql, "RawSQLReader", FailingReader)
    with pytest.raises(ResearchError, match="missing_raw_hash_definition") as caught:
        raw_sql.execute_raw_verification(path, "202501050601", "2025-01-05T10:00:00+09:00")
    assert state["closed"]
    run = tmp_path / "runs" / caught.value.details["run_id"]
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and "resume_condition" in manifest["failure"]["details"]
    assert {p.name for p in run.iterdir()} == {"config.json", "manifest.json", "failure.json", "preflight.json"}


@pytest.mark.parametrize("race,cutoff", [("202513050601", "2025-01-05T10:00:00+09:00"), ("202501051101", "2025-01-05T10:00:00+09:00"), ("202501050601", "2025-01-05T10:00:00")])
def test_invalid_request_is_rejected(race, cutoff):
    """不正開催日・場コード・timezone欠落を拒否する。"""
    with pytest.raises(ResearchError):
        raw_sql._validate_request(race, cutoff)
