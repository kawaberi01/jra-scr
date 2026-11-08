"""概要: native receipt card scoreのID保持・cutoff・active roster・対象結果非参照境界を検証する。
作成日: 2026-10-17
入力: 合成RaceCard receipt、fake history reader/model/artifact。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_research_native_card.py
注意事項: SQL/HTTP/SQLiteを使わず、実モデルartifactを読み書きしない。
"""

from copy import deepcopy
from datetime import date
import hashlib
import json
from types import SimpleNamespace

import pytest

from jra_srb.jra_research_contracts import ResearchError, canonical_json
from jra_srb.jra_research_native_card import (
    NativeCardIdentity,
    _NativeCardHistoryReader,
    _identity,
    _select_native_card,
    execute_native_card_score,
)


RACE_ID = "202610180811"
DAY = "2026-10-18"
CUTOFF = "2026-10-17T04:10:00.0000000+00:00"
OFFICIAL_URL = "https://www.jra.go.jp/JRADB/accessD.html?CNAME=test"


def _receipt(*, received="2026-10-17T04:04:00.1234567", fetched="2026-10-17T04:03:00+00:00",
             source=OFFICIAL_URL, runner_set="complete", source_kind="pre_race_card",
             statuses=("active", "active", "withdrawn"), race_id=RACE_ID):
    """完全/不完全状態やrunner状態を指定できる合成native receiptを作る。"""
    runners = [{"horse_no": str(index), "horse_name": f"馬{index}", "jockey": "騎手", "trainer": "調教師",
                "status": status} for index, status in enumerate(statuses, 1)]
    observed = {"race_id": race_id, "race_name": "合成記念", "course": "kyoto", "distance": "1800",
                "surface": "芝", "runners": runners, "fetched_at": fetched, "source": source,
                "data_status": {"runner_set": runner_set, "source_kind": source_kind}}
    payload = {"date": DAY, "course": "kyoto", "race_no": 11, "card": observed}
    business = deepcopy(payload)
    business["card"].pop("cache_hit", None)
    business["card"].pop("meta", None)
    request_sha = hashlib.sha256(("race_card\n" + race_id + "\n" + canonical_json(business)).encode("utf-8")).hexdigest()
    return {"operation": "race_card", "race_id": race_id, "request_sha256": request_sha,
            "received_at_utc": received, "payload_json": canonical_json(payload)}


def _install_score_harness(monkeypatch, reader_factory):
    """execute入口のmodel・artifact・score依存をfakeへ置き換える。"""
    import jra_srb.jra_research_native_card as module

    fake_config = SimpleNamespace(raw={"profile_id": "history_sql_v1",
        "source_policy": {"source_key": "analysis-current", "snapshot_id": 34},
        "date_through": "2026-10-16", "limits": {"memory_bytes": 2 * 1024 ** 3}}, snapshot=34)
    model = {"trained_through": "2026-10-16", "models": {}}
    monkeypatch.setattr(module.HistoryConfig, "load", classmethod(lambda cls, path: fake_config))
    monkeypatch.setattr(module, "load_history_score_artifact", lambda path, config: (model, "c" * 64))
    monkeypatch.setattr(module, "check_memory", lambda budget: None)
    monkeypatch.setattr(module, "_new_reader", reader_factory)

    artifacts = []

    class FakeArtifacts:
        """artifact writerの失敗状態をメモリで記録する。"""
        def __init__(self, config, command):
            """実行識別子と保存状態を初期化する。"""
            self.manifest, self.writes, self.command = {}, [], command
            self.run_id = "synthetic-run"
            artifacts.append(self)

        def write_json(self, name, value):
            """JSON成果物の名前と値を保存せず記録する。"""
            self.writes.append((name, value))

        def finish(self, **kwargs):
            """成功metadataを記録する。"""
            self.finished = kwargs

        def fail(self, error):
            """失敗理由を記録する。"""
            self.error = error

    monkeypatch.setattr("jra_srb.jra_research_artifacts.RunArtifacts", FakeArtifacts)
    monkeypatch.setattr(module, "history_score_records", lambda rows, card, sizes, recent: [])
    monkeypatch.setattr("jra_srb.jra_history_model.score_live_records", lambda model, records: [])
    return artifacts


def test_native_id_is_preserved_and_active_complete_card_selected():
    """最新official cardのnative API IDを保持し、withdrawn runnerはscore対象から外す。"""
    identity = NativeCardIdentity(RACE_ID, DAY, "kyoto", 11)
    selected = _select_native_card([_receipt()], identity, "official", CUTOFF)
    assert selected.history_card["race_id"] == RACE_ID
    assert selected.history_card["race_date"] == DAY
    assert [runner["horse_no"] for runner in selected.history_card["runners"]] == ["1", "2"]
    assert "unified_race_id" not in selected.history_card
    assert len(selected.receipt_digest) == 64 and len(selected.payload_sha256) == 64


def test_official_source_alias_accepts_only_jra_host_and_explicit_url_is_exact():
    """official aliasはJRA公式URLに限り、明示URLは完全一致だけを採用する。"""
    identity = NativeCardIdentity(RACE_ID, DAY, "kyoto", 11)
    row = _receipt()
    assert _select_native_card([row], identity, "official", CUTOFF).history_card["race_id"] == RACE_ID
    assert _select_native_card([row], identity, OFFICIAL_URL, CUTOFF).history_card["race_id"] == RACE_ID
    with pytest.raises(ResearchError, match="invalid_native_card_source"):
        _select_native_card([row], identity, "https://www.jra.go.jp.evil.example/card", CUTOFF)
    with pytest.raises(ResearchError, match="invalid_native_card_source"):
        _select_native_card([], identity, "http://www.jra.go.jp/card", CUTOFF)
    with pytest.raises(ResearchError, match="invalid_native_card_source"):
        _select_native_card([], identity, "https://user@www.jra.go.jp/card", CUTOFF)
    with pytest.raises(ResearchError, match="native_card_receipt_unavailable"):
        _select_native_card([row], identity, "https://www.jra.go.jp/other", CUTOFF)


def test_native_course_must_match_race_id_venue_code():
    """競馬場名はnative IDの場コードから既存COURSE_CODESと一致させる。"""
    assert _identity(RACE_ID, DAY, "kyoto", 11).course == "kyoto"
    with pytest.raises(ResearchError, match="invalid_native_card_identity"):
        _identity(RACE_ID, DAY, "tokyo", 11)


@pytest.mark.parametrize("kwargs", [
    {"runner_set": "incomplete"},
    {"source_kind": "result_page"},
    {"statuses": ("withdrawn", "withdrawn")},
    {"source": "mirror"},
    {"race_id": "202610180812"},
])
def test_receipt_status_source_id_and_roster_fail_closed(kwargs):
    """status・期待source・native ID・active roster不一致を採用しない。"""
    identity = NativeCardIdentity(RACE_ID, DAY, "kyoto", 11)
    with pytest.raises(ResearchError):
        _select_native_card([_receipt(**kwargs)], identity, "official", CUTOFF)


def test_cutoff_and_latest_ambiguity_use_100ns_receipt_time():
    """cutoff後のreceipt/provider時刻と、最新時刻で異なる本文を拒否する。"""
    identity = NativeCardIdentity(RACE_ID, DAY, "kyoto", 11)
    too_late = _receipt(received="2026-10-17T04:10:00.0000001")
    with pytest.raises(ResearchError, match="native_card_receipt_unavailable"):
        _select_native_card([too_late], identity, "official", CUTOFF)
    provider_too_late = _receipt(fetched="2026-10-17T04:10:00.0000001+00:00")
    with pytest.raises(ResearchError, match="native_card_receipt_unavailable"):
        _select_native_card([provider_too_late], identity, "official", CUTOFF)
    first = _receipt(received="2026-10-17T04:04:00.1234567")
    second = _receipt(received="2026-10-17T04:04:00.1234567", fetched="2026-10-17T04:03:01+00:00")
    with pytest.raises(ResearchError, match="ambiguous_native_card_revision"):
        _select_native_card([first, second], identity, "official", CUTOFF)


def test_receipt_sha_mismatch_and_duplicate_key_are_rejected():
    """receipt本文hashの不一致と同一request SHAの重複を拒否する。"""
    identity = NativeCardIdentity(RACE_ID, DAY, "kyoto", 11)
    bad = _receipt()
    bad["request_sha256"] = "0" * 64
    with pytest.raises(ResearchError, match="receipt_digest_mismatch"):
        _select_native_card([bad], identity, "official", CUTOFF)
    row = _receipt()
    with pytest.raises(ResearchError, match="duplicate_native_card_receipt"):
        _select_native_card([row, dict(row)], identity, "official", CUTOFF)


def test_receipt_query_is_race_card_only_and_payload_bounded(monkeypatch):
    """receipt SELECTはoperationをrace_cardに固定し、TOP/本文容量を有限化する。"""
    import jra_srb.jra_research_native_card as module

    row = _receipt()
    columns = ["request_sha256", "operation", "race_id", "received_at_utc", "payload_json", "payload_byte_count"]
    values = [(bytes.fromhex(row["request_sha256"]), row["operation"], row["race_id"],
               row["received_at_utc"], row["payload_json"], len(row["payload_json"].encode("utf-16le")))]
    observed = {}

    class CursorContext:
        """固定結果を返すfake cursor context。"""
        def __init__(self, query_id, sql, params):
            """呼出しSQLとparamsを監査用に記録する。"""
            observed.update(query_id=query_id, sql=sql, params=params)
            self.description = [(name,) for name in columns]

        def __enter__(self):
            """cursor contextとして自身を返す。"""
            return self

        def __exit__(self, exc_type, exc, tb):
            """fake cursorを閉じる操作を何もしない。"""
            return None

        def fetchmany(self, size):
            """指定上限を記録し、合成receiptを返す。"""
            observed["fetch_size"] = size
            return values

    monkeypatch.setattr(_NativeCardHistoryReader, "_cursor", lambda self, *args: CursorContext(*args))
    config = SimpleNamespace(raw={"limits": {"memory_bytes": 2 * 1024 ** 3}})
    reader = object.__new__(_NativeCardHistoryReader)
    reader.config = config
    reader.native_identity = NativeCardIdentity(RACE_ID, DAY, "kyoto", 11)
    reader.native_cutoff = CUTOFF
    result = reader._receipt_rows()
    assert len(result) == 1 and result[0]["request_sha256"] == bytes.fromhex(row["request_sha256"])
    assert "operation=N'race_card'" in observed["sql"]
    assert "race_sha256=CONVERT(binary(32),?)" in observed["sql"]
    assert "SUM(CONVERT(bigint,DATALENGTH(payload_json))) OVER ()" in observed["sql"]
    assert observed["params"][1] == 10000 and observed["fetch_size"] == 10000


def test_history_keyset_sql_excludes_target_outcomes(monkeypatch):
    """既存history keyset SQLに対象raceのresult/payout除外が付く。"""
    import jra_srb.jra_research_native_card as module

    seen = []

    class CursorContext:
        """keyset queryを記録して空結果を返すfake cursor context。"""
        def __init__(self, query_id, sql, params):
            """対象race排除述語を確認できるようSQLを記録する。"""
            seen.append((query_id, sql, tuple(params)))

        def __enter__(self):
            """cursor contextとして自身を返す。"""
            return self

        def __exit__(self, exc_type, exc, tb):
            """fake cursorを閉じる操作を何もしない。"""
            return None

        def fetchmany(self, size):
            """テーブル行がない状態を表す空batchを返す。"""
            return []

    monkeypatch.setattr(_NativeCardHistoryReader, "_cursor", lambda self, *args: CursorContext(*args))
    reader = object.__new__(_NativeCardHistoryReader)
    reader.config = SimpleNamespace(snapshot=34, raw={"limits": {
        "fetch_rows": 10, "max_candidate_rows": 10, "memory_bytes": 2 * 1024 ** 3}})
    reader.native_identity = NativeCardIdentity(RACE_ID, DAY, "kyoto", 11)
    reader.excluded_outcome_race_id = None
    reader.pass_streams = {}
    reader.scan_rows = {}
    assert list(reader._table_rows("live.payouts", ("race_id",))) == []
    assert list(reader._table_rows("live.result_entries", ("race_id", "horse_no", "rank"))) == []
    assert all("AND race_id<>?" in sql and params[-1] == RACE_ID for _, sql, params in seen)


def test_execute_scores_from_native_card_without_target_outcome_or_card_persistence(monkeypatch):
    """fake SQL境界で二巡し、前日履歴のみをR01 scoreへ渡し本文をartifactへ保存しない。"""
    import jra_srb.jra_research_native_card as module

    raw_config = {"profile_id": "history_sql_v1", "source_policy": {"source_key": "analysis-current", "snapshot_id": 34},
                  "date_through": "2026-10-16", "limits": {"memory_bytes": 2 * 1024 ** 3}}
    fake_config = SimpleNamespace(raw=raw_config, snapshot=34)
    monkeypatch.setattr(module.HistoryConfig, "load", classmethod(lambda cls, path: fake_config))
    model = {"trained_through": "2026-10-16", "models": {}}
    monkeypatch.setattr(module, "load_history_score_artifact", lambda path, config: (model, "c" * 64))
    monkeypatch.setattr(module, "check_memory", lambda budget: None)
    receipt = _receipt()

    artifacts_created = []

    class FakeArtifacts:
        """artifact writerをメモリ上で模擬し、書込payloadを監査する。"""
        def __init__(self, config, command):
            """書込と完了状態をメモリに保持する。"""
            self.manifest, self.writes, self.command = {}, [], command
            self.run_id = "synthetic-run"
            artifacts_created.append(self)

        def write_json(self, name, value):
            """保存要求をメモリへ記録する。"""
            self.writes.append((name, value))

        def finish(self, **kwargs):
            """完了時metadataを記録する。"""
            self.finished = kwargs

        def fail(self, error):
            """失敗errorを記録し、失敗artifactの存在を表す。"""
            self.error = error

    class FakeReader:
        """history passごとに同じnative receiptを読み、対象日前の合成履歴だけを返す。"""
        def __init__(self):
            """二巡比較に必要なreader状態を初期化する。"""
            self.query_metrics, self.scan_rows = [], {}
            self.report = {}
            self.pass_streams = {}
            self.result_field_sizes = {"202610120811": 10}
            self.score_target = None
            self.passes = 0

        def __enter__(self):
            """fake SQL reader contextを開始する。"""
            return self

        def __exit__(self, exc_type, exc, tb):
            """fake SQL reader contextを終了する。"""
            return None

        def preflight(self):
            """最小read-only preflight結果を返す。"""
            return {"read_only": True}

        def history_rows(self, score_race_id=None):
            """対象日前の履歴と保存済みnative cardを一巡分返す。"""
            assert score_race_id == RACE_ID
            self.passes += 1
            self.pass_streams = {"live.races": "history-digest"}
            selected = _select_native_card([receipt], NativeCardIdentity(RACE_ID, DAY, "kyoto", 11), "official", CUTOFF)
            self.score_target = None
            yield {"race_id": "202610120811", "race_date": "2026-10-12", "horse_no": "1",
                   "horse_name": "過去馬", "rank": 1}
            self.score_target = selected.history_card
            self.pass_streams["api_runtime.write_receipts"] = selected.receipt_digest

    fake_reader = FakeReader()
    monkeypatch.setattr(module, "_new_reader", lambda *args: fake_reader)
    monkeypatch.setattr("jra_srb.jra_research_artifacts.RunArtifacts", FakeArtifacts)
    monkeypatch.setattr(module, "history_score_records", lambda rows, card, sizes, recent:
        (assert_history(rows, card), [{"horse_no": "1", "features": [0.0]}])[1])
    monkeypatch.setattr("jra_srb.jra_history_model.score_live_records", lambda model, records:
        [{"horse_no": "1", "win_probability": 0.4, "top3_probability": 0.8,
          "win_probability_race_normalized": 0.4}])

    result = execute_native_card_score("config.json", "model_history.json", RACE_ID, DAY,
                                       "kyoto", 11, CUTOFF)
    assert result["status"] == "passed" and result["overall_complete"] is False
    assert result["outcome_read"] is False and result["native_card_identity_preserved"] is True
    assert fake_reader.passes == 2
    saved_text = json.dumps([value for _, value in artifacts_created[0].writes], ensure_ascii=False)
    assert '"runners"' not in saved_text and "馬1" not in saved_text


def test_receipt_change_between_history_passes_fails_and_keeps_failure_artifact(monkeypatch):
    """二巡間にreceipt streamが変われば停止し、失敗artifactへ理由を保持する。"""
    row = _receipt()

    class ChangingReader:
        """history passごとに異なるreceipt digestを返すfake reader。"""
        def __init__(self):
            """pass数とscore対象カードの状態を初期化する。"""
            self.query_metrics, self.scan_rows, self.result_field_sizes = [], {}, {}
            self.pass_streams, self.report = {}, {}
            self.score_target, self.passes = None, 0

        def __enter__(self):
            """fake reader contextを開始する。"""
            return self

        def __exit__(self, exc_type, exc, tb):
            """fake reader contextを終了する。"""
            return None

        def preflight(self):
            """read-onlyなfake preflight結果を返す。"""
            return {"read_only": True}

        def history_rows(self, score_race_id=None):
            """履歴・カードは固定し、receipt digestだけを巡回ごとに変える。"""
            self.passes += 1
            self.pass_streams = {"api_runtime.write_receipts": f"receipt-{self.passes}"}
            self.score_target = None
            yield {"race_id": "202610120811", "race_date": "2026-10-12", "horse_no": "1",
                   "horse_name": "過去馬", "rank": 1}
            self.score_target = _select_native_card(
                [row], NativeCardIdentity(RACE_ID, DAY, "kyoto", 11), "official", CUTOFF).history_card

    reader = ChangingReader()
    artifacts = _install_score_harness(monkeypatch, lambda *args: reader)
    with pytest.raises(ResearchError, match="source_changed") as captured:
        execute_native_card_score("config.json", "model_history.json", RACE_ID, DAY,
                                  "kyoto", 11, CUTOFF)
    assert reader.passes == 2
    assert artifacts[0].error.reason == "source_changed"
    assert captured.value.details["run_id"] == artifacts[0].run_id


def test_connection_exception_closes_reader_and_preserves_failure_artifact(monkeypatch):
    """接続例外はreader close後にResearchError化され、run失敗証跡を残す。"""
    import sys
    import jra_srb.jra_research_native_card as module

    reader = _NativeCardHistoryReader(
        SimpleNamespace(raw={"source_policy": {"source_key": "analysis-current"},
                          "limits": {"query_timeout_seconds": 10}}),
        NativeCardIdentity(RACE_ID, DAY, "kyoto", 11), "official", CUTOFF)
    closed = []
    built = []

    def fail_connect(*args, **kwargs):
        """SQL driver接続失敗を再現する。"""
        raise OSError("fake connection failure")

    monkeypatch.setitem(sys.modules, "mssql_python", SimpleNamespace(connect=fail_connect))
    original_close = module.HistoryReader.close

    def tracked_close(self):
        """reader close呼出しを記録して本来のclose処理も実行する。"""
        closed.append(self)
        return original_close(self)

    monkeypatch.setattr(module.HistoryReader, "close", tracked_close)
    artifacts = _install_score_harness(monkeypatch, lambda *args: (built.append(reader) or reader))
    with pytest.raises(ResearchError, match="sql_connection_failed") as captured:
        execute_native_card_score("config.json", "model_history.json", RACE_ID, DAY,
                                  "kyoto", 11, CUTOFF)
    assert built == [reader] and closed == [reader]
    assert artifacts[0].error.reason == "sql_connection_failed"
    assert captured.value.details["run_id"] == artifacts[0].run_id


def test_saved_model_contract_rejection_stops_before_reader(monkeypatch):
    """不適合artifactが拒否された場合はreader/receipt照会へ進まない。"""
    import jra_srb.jra_research_native_card as module

    fake_config = SimpleNamespace(raw={"profile_id": "history_sql_v1",
        "source_policy": {"source_key": "analysis-current", "snapshot_id": 34},
        "date_through": "2026-10-16", "limits": {"memory_bytes": 2 * 1024 ** 3}}, snapshot=34)
    monkeypatch.setattr(module.HistoryConfig, "load", classmethod(lambda cls, path: fake_config))
    monkeypatch.setattr(module, "load_history_score_artifact",
                        lambda *args: (_ for _ in ()).throw(ResearchError("history_model_contract_mismatch", 2)))
    monkeypatch.setattr(module, "_new_reader", lambda *args: pytest.fail("reader must not open"))
    with pytest.raises(ResearchError, match="history_model_contract_mismatch"):
        execute_native_card_score("config.json", "model_history.json", RACE_ID, DAY,
                                  "kyoto", 11, CUTOFF)


def test_same_day_history_cutoff_is_rejected_before_model_or_reader(monkeypatch):
    """R01履歴date_throughが対象日当日なら結果混入可能性を避けて停止する。"""
    import jra_srb.jra_research_native_card as module

    fake_config = SimpleNamespace(raw={"profile_id": "history_sql_v1",
        "source_policy": {"source_key": "analysis-current", "snapshot_id": 34},
        "date_through": DAY, "limits": {"memory_bytes": 2 * 1024 ** 3}}, snapshot=34)
    monkeypatch.setattr(module.HistoryConfig, "load", classmethod(lambda cls, path: fake_config))
    monkeypatch.setattr(module, "load_history_score_artifact",
                        lambda *args: pytest.fail("model must not load"))
    monkeypatch.setattr(module, "_new_reader", lambda *args: pytest.fail("reader must not open"))
    with pytest.raises(ResearchError, match="native_card_history_config_scope"):
        execute_native_card_score("config.json", "model_history.json", RACE_ID, DAY,
                                  "kyoto", 11, CUTOFF)


def assert_history(rows, card):
    """score入力が対象日前の行とnative cardのactive runnerだけで構成されることを検査する。"""
    assert all(row["race_date"] < card["race_date"] for row in rows)
    assert card["race_id"] == RACE_ID and len(card["runners"]) == 2
