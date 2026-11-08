"""概要: 保存済みnative API出馬表と固定SQL履歴から、R01モデルのresearch-only予測を行う。
作成日: 2026-10-17
入力: R01設定・モデルartifact、native API race ID、日付/場/番号、UTC knowledge cutoff、期待source。
出力: 確率・選択来歴・入力digestだけの新規RunArtifacts。
実行例: uv run python scripts/run_jra_research.py native-card-score --config configs/research/history_sql_v1.json --model artifacts/jra_research/runs/<model-run>/model_history.json --race-id 202610170404 --race-date 2026-10-17 --course niigata --race-no 4 --knowledge-cutoff 2026-10-17T02:13:01+00:00
注意事項: SQLはSELECTのみ。HTTP/SQLite/ID変換なし。native API card＋horse-name legacy historyであり新受入族ではない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .jra_history_dataset import COURSE_CODES
from .jra_research_contracts import ResearchError, canonical_json, digest
from .jra_research_history import (
    HistoryConfig,
    HistoryReader,
    collect_history_score,
    history_score_records,
    load_history_score_artifact,
)
from .jra_research_resources import check_memory
from .jra_research_runtime import _payload, _sha, _time_key, _utc, _validate_roster
from .jra_research_runtime_sql import _preflight
from .models import RaceCard

MAX_RECEIPT_ROWS = 9999
MAX_RECEIPT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NativeCardIdentity:
    """登録済みJV IDを持たない、receipt照合用native API属性だけを保持する。"""

    api_race_id: str
    race_date: str
    course: str
    race_no: int


@dataclass(frozen=True, repr=False)
class _SelectedCard:
    """選択カードと公開可能な受領証跡digestだけを保持する。"""

    history_card: dict[str, Any]
    receipt_digest: str
    received_at_utc: str
    fetched_at_utc: str
    payload_sha256: str


def _canonical_day(value: date | str) -> str:
    """日付をISOへ正規化し、曖昧な文字列を拒否する。"""
    if isinstance(value, datetime):
        raise ResearchError("invalid_native_card_date", 2)
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ResearchError("invalid_native_card_date", 2) from None
    return parsed.isoformat()


def _identity(race_id: str, day: str, course: str, race_no: int) -> NativeCardIdentity:
    """要求属性の正規形を検査し、ID文字列を変更せず照合identityにする。"""
    if (not isinstance(race_id, str) or len(race_id) != 12 or not race_id.isascii()
            or not race_id.isdigit() or race_id[:8] != day.replace("-", "")
            or not isinstance(course, str) or not course
            or type(race_no) is not int or not 1 <= race_no <= 12
            or race_id[-2:] != f"{race_no:02d}"
            or not "01" <= race_id[8:10] <= "10" or race_id[8:10] not in COURSE_CODES
            or course != COURSE_CODES[race_id[8:10]]):
        raise ResearchError("invalid_native_card_identity", 2)
    return NativeCardIdentity(race_id, day, course, race_no)


def _official_source_url(value: Any) -> bool:
    """JRA公式source URLだけを受け入れ、host偽装や不正authorityを拒否する。"""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.hostname == "www.jra.go.jp"
            and parsed.username is None and parsed.password is None
            and port in (None, 443) and not parsed.fragment)


def _validate_source_policy(source: str) -> None:
    """公式host aliasまたは完全一致用公式URLにsource policyを限定する。"""
    if source == "official" or _official_source_url(source):
        return
    raise ResearchError("invalid_native_card_source", 2)


def _source_matches(observed_source: Any, expected_source: str) -> bool:
    """official aliasは公式hostを照合し、URL指定時は受領値との完全一致を要求する。"""
    if expected_source == "official":
        return _official_source_url(observed_source)
    return _official_source_url(expected_source) and observed_source == expected_source


def _prepare_card(row: Mapping[str, Any], identity: NativeCardIdentity, source: str,
                  cutoff: str) -> _SelectedCard | None:
    """receipt payloadを検証し、completeなpre-race cardのactive馬だけをscore用に整える。"""
    _validate_source_policy(source)
    payload, observed = _payload(dict(row), identity, "race_card")
    if not _source_matches(observed.get("source"), source):
        return None
    received = _utc(row["received_at_utc"], sql_utc=True)
    fetched = _utc(observed["fetched_at"])
    if _time_key(received) > _time_key(cutoff) or _time_key(fetched) > _time_key(cutoff):
        return None
    data_status = observed.get("data_status")
    if (not isinstance(data_status, dict) or data_status.get("runner_set") != "complete"
            or data_status.get("source_kind") != "pre_race_card"):
        raise ResearchError("native_card_status_incomplete", 4)
    _validate_roster(observed, "race_card", None)
    card_model = RaceCard.model_validate(observed)
    card = card_model.model_dump(mode="json")
    active = [runner for runner in card["runners"] if runner["status"] == "active"]
    if len(active) < 2:
        raise ResearchError("native_card_active_roster_incomplete", 4)
    if not all(runner["status"] in {"active", "withdrawn"} for runner in card["runners"]):
        raise ResearchError("native_card_roster_status_invalid", 4)
    if any(not isinstance(card.get(key), str) or not card[key]
           for key in ("race_name", "surface", "distance")):
        raise ResearchError("native_card_features_missing", 4)
    history_card = {**card, "race_date": identity.race_date, "runners": active}
    payload_sha = digest(payload)
    request_sha = _sha(row.get("request_sha256"))
    receipt_digest = digest({"request_sha256": request_sha, "operation": row["operation"],
                             "race_id": row["race_id"], "received_at_utc": received,
                             "payload_sha256": payload_sha})
    return _SelectedCard(history_card, receipt_digest, received, fetched, payload_sha)


def _select_native_card(rows: list[dict[str, Any]], identity: NativeCardIdentity,
                        source: str, cutoff: str) -> _SelectedCard:
    """最新cutoff内receiptを100ns精度で選び、同時刻の異なる本文を拒否する。"""
    _validate_source_policy(source)
    eligible = []
    seen = set()
    for row in rows:
        if row.get("operation") != "race_card":
            raise ResearchError("native_card_operation_mismatch", 4)
        if not isinstance(row.get("race_id"), str) or row["race_id"].encode("utf-16le") != identity.api_race_id.encode("utf-16le"):
            raise ResearchError("native_card_id_mismatch", 4)
        key = _sha(row.get("request_sha256"))
        if key in seen:
            raise ResearchError("duplicate_native_card_receipt", 4)
        seen.add(key)
        selected = _prepare_card(row, identity, source, cutoff)
        if selected is not None:
            eligible.append((selected, key))
    if not eligible:
        raise ResearchError("native_card_receipt_unavailable", 4)
    latest = max(_time_key(item[0].received_at_utc) for item in eligible)
    at_latest = [item for item in eligible if _time_key(item[0].received_at_utc) == latest]
    if len({item[0].payload_sha256 for item in at_latest}) > 1:
        raise ResearchError("ambiguous_native_card_revision", 4)
    return min(at_latest, key=lambda item: item[1])[0]


class _NativeCardHistoryReader(HistoryReader):
    """R01 history readerへnative card receiptを二巡で接続する専用read-only reader。"""

    def __init__(self, config: HistoryConfig, identity: NativeCardIdentity, source: str, cutoff: str):
        """履歴設定と明示native card属性を保持し、接続は親readerへ委ねる。"""
        super().__init__(config)
        self.native_identity, self.native_source, self.native_cutoff = identity, source, cutoff
        self.native_preflight: dict[str, Any] = {}

    def preflight(self) -> dict[str, Any]:
        """receipt/index/hash routeとR01の固定34 history routeを検査する。"""
        runtime_config = {"source_policy": {"source_key": self.config.raw["source_policy"]["source_key"],
                                             "snapshot_id": self.config.snapshot}}
        receipt = _preflight(self, runtime_config)
        history = super().preflight()
        self.native_preflight = {"receipt": receipt, "history": history,
                                 "score_scope": "native_api_card_plus_horse_name_legacy_history",
                                 "model_family_verified": False, "baseline_verified": False}
        return self.native_preflight

    def _receipt_rows(self) -> list[dict[str, Any]]:
        """race_card operationだけをnative ID・hash keyset・UTC cutoffで有界取得する。"""
        identity = self.native_identity
        memory_budget = self.config.raw["limits"]["memory_bytes"]
        payload_budget = min(MAX_RECEIPT_BYTES, max(1, memory_budget // 16))
        cutoff_sql = self.native_cutoff.removesuffix("+00:00")
        inner = ("SELECT TOP (?) request_sha256,operation,race_id,payload_json,"
                 "CONVERT(varchar(33),received_at_utc,126) received_at_utc "
                 "FROM api_runtime.write_receipts WHERE race_sha256=CONVERT(binary(32),?) "
                 "AND CONVERT(varbinary(max),race_id)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?)) "
                 "AND received_at_utc<=CONVERT(datetime2(7),?) AND operation=N'race_card' "
                 "ORDER BY received_at_utc,request_sha256")
        sql = ("SELECT request_sha256,operation,race_id,received_at_utc,"
               "CASE WHEN SUM(CONVERT(bigint,DATALENGTH(payload_json))) OVER ()<=? "
               "THEN payload_json ELSE NULL END payload_json,"
               "CONVERT(bigint,DATALENGTH(payload_json)) payload_byte_count FROM (" + inner +
               ") bounded_receipts ORDER BY received_at_utc,request_sha256")
        params = (payload_budget, MAX_RECEIPT_ROWS + 1,
                  hashlib.sha256(identity.api_race_id.encode("utf-16le")).digest(),
                  identity.api_race_id, cutoff_sql)
        with self._cursor("native_card:receipt_race_card", sql, params) as cursor:
            columns = [column[0] for column in cursor.description]
            raw_rows = cursor.fetchmany(MAX_RECEIPT_ROWS + 1)
        if len(raw_rows) > MAX_RECEIPT_ROWS:
            raise ResearchError("native_card_receipt_row_cap", 4)
        rows = []
        for raw in raw_rows:
            row = dict(zip(columns, raw, strict=True))
            size, payload = row.pop("payload_byte_count"), row["payload_json"]
            if payload is None or type(size) is not int or size < 0 or size > payload_budget:
                raise ResearchError("native_card_receipt_payload_cap", 4)
            rows.append(row)
        return rows

    def history_rows(self, score_race_id: str | None = None):
        """固定履歴snapshotを対象日前だけから走査し、receipt cardをscore targetに差す。"""
        if score_race_id != self.native_identity.api_race_id:
            raise ResearchError("native_card_history_target_mismatch", 4)
        selected = _select_native_card(self._receipt_rows(), self.native_identity,
                                       self.native_source, self.native_cutoff)
        self.score_target = None
        for row in super().history_rows():
            if row["race_date"] >= self.native_identity.race_date:
                raise ResearchError("native_card_history_not_before_target", 4)
            yield row
        self.score_target = selected.history_card
        self.pass_streams["api_runtime.write_receipts"] = selected.receipt_digest
        self.pass_streams["selected_card_payload_sha256"] = selected.payload_sha256

    def _table_rows(self, table: str, fields: tuple[str, ...]):
        """旧HistoryReader keyset SQLを使い、対象raceの結果/払戻だけ明示除外する。"""
        if table in {"live.result_entries", "live.payouts"}:
            self.excluded_outcome_race_id = self.native_identity.api_race_id
        yield from super()._table_rows(table, fields)


def _new_reader(config: HistoryConfig, identity: NativeCardIdentity, source: str,
                cutoff: str) -> _NativeCardHistoryReader:
    """実行用のreceipt/history固定SELECT readerを生成する。"""
    return _NativeCardHistoryReader(config, identity, source, cutoff)


def execute_native_card_score(config: str | Path, model: str | Path, race_id: str,
                              day: date | str, course: str, race_no: int,
                              knowledge_cutoff: str, source: str = "official") -> dict[str, Any]:
    """native API cardと既存horse-name R01履歴を用い、対象結果を読まずにscoreする。

    Args:
        config: history_sql_v1またはrecent_form_sql_v2の設定JSON。
        model: 同じ固定snapshot/profileのcomplete model_history.json。
        race_id: native API race ID。ID変換・unified ID生成はしない。
        day: 対象開催日。
        course: API receipt wrapperと完全一致させる場名。
        race_no: 対象レース番号。
        knowledge_cutoff: timezone付きの100ns精度UTC上限。
        source: officialなら公式JRA host policy、URLなら公式URLとの完全一致条件。
    Returns:
        保存カード＋horse-name legacy historyの確率・来歴・digestを返す。
    Raises:
        ResearchError: 設定/モデル/receipt/preflight/履歴/選択またはscore境界が不成立。
    Notes:
        固定snapshot 34だけを使う。出力はresearch-onlyでbaseline/M4全体受入へ昇格しない。
    """
    target_day = _canonical_day(day)
    identity = _identity(race_id, target_day, course, race_no)
    cutoff = _utc(knowledge_cutoff)
    history_config = HistoryConfig.load(config)
    if (history_config.snapshot != 34 or history_config.raw["source_policy"]["source_key"] != "analysis-current"
            or history_config.raw["date_through"] >= target_day):
        raise ResearchError("native_card_history_config_scope", 2)
    model_values, model_contract_sha = load_history_score_artifact(model, history_config)
    trained_through = model_values.get("trained_through")
    if not isinstance(trained_through, str) or date.fromisoformat(trained_through) >= date.fromisoformat(target_day):
        raise ResearchError("native_card_model_not_before_target", 2)
    from .jra_research_artifacts import RunArtifacts
    from .jra_history_model import score_live_records

    artifacts = RunArtifacts(history_config.raw, "native-card-score")
    reader = None
    try:
        reader = _new_reader(history_config, identity, source, cutoff)
        with reader:
            preflight = reader.preflight()
            artifacts.write_json("preflight.json", preflight)
            rows, card, field_sizes, content = collect_history_score(reader, race_id)
            artifacts.manifest.update(query_metrics=reader.query_metrics,
                                      input_content_sha256=content,
                                      provenance={"scope": "native_api_card_plus_horse_name_legacy_history",
                                          "availability": "retrospective_compatibility",
                                          "source_snapshot_id": history_config.snapshot,
                                          "read_consistency": "chunked_unproven",
                                          "scan_rows": reader.scan_rows,
                                          "source_table_streams_sha256": reader.pass_streams})
        records = history_score_records(rows, card, field_sizes,
                                        recent=history_config.raw["profile_id"] == "recent_form_sql_v2")
        check_memory(history_config.raw["limits"]["memory_bytes"])
        scored = score_live_records(model_values, records)
        output = {"profile_id": history_config.raw["profile_id"], "race_id": race_id,
                  "outcome_read": False, "history_before": card["race_date"],
                  "availability": "native_api_card_plus_horse_name_legacy_history",
                  "evaluation_kind": "released_artifact_score_not_holdout",
                  "model_trained_through": trained_through,
                  "knowledge_cutoff": cutoff, "card_source": source,
                  "native_card_identity_preserved": True, "model_family_verified": False,
                  "baseline_verified": False,
                  "predictions": [{"horse_no": row["horse_no"], **{key: row[key] for key in
                      ("win_probability", "top3_probability", "win_probability_race_normalized")}}
                      for row in scored]}
        artifacts.write_json("metrics.json", output)
        artifacts.finish(metrics_sha256=digest(output), feature_contract_sha256=model_contract_sha,
                         model_sha256=digest(model_values), input_content_sha256=content,
                         outcome_read=False, baseline_verified=False, overall_complete=False,
                         verification_scope="native_card_plus_legacy_history_only")
        return {"status": "passed", "run_id": artifacts.run_id, **output, "overall_complete": False}
    except Exception as error:
        if reader is not None:
            artifacts.manifest["query_metrics"] = reader.query_metrics
        safe = error if isinstance(error, ResearchError) else ResearchError(
            "native_card_score_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None
