"""概要: SQL受領履歴から明示時点のoperation完全束を選択して再現性を検査する。
作成日: 2026-10-15
入力: 研究reader、登録済みID対応、固定cutoff、受領履歴または明示baseline。
出力: メモリ内完全束、本文を含まない選択証跡とdigest。
実行例: uv run pytest -q tests/test_jra_research_runtime.py
注意事項: SELECT専用。本文・全特徴量を保存しない。取得時刻は当時利用可能性を証明しない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any

from .jra_research_contracts import ResearchError, canonical_json, digest, horse_number, timestamp
from .models import RaceCard, RaceOdds, RaceResult


ADAPTER_VERSION = "runtime-receipt-payload-v1"
OPERATIONS = ("race_card", "odds", "race_result")


def _utc(value: str | datetime, *, sql_utc: bool = False) -> str:
    """UTC列だけnaive日時をUTCと扱い、他の日時はtimezone必須で正規化する。"""
    if isinstance(value, datetime):
        if sql_utc and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.isoformat()
    if sql_utc and isinstance(value, str):
        try:
            if datetime.fromisoformat(value).tzinfo is None:
                value += "+00:00"
        except ValueError:
            raise ResearchError("invalid_timestamp") from None
    fraction = re.search(r"T\d{2}:\d{2}:\d{2}\.(\d+)", value) if isinstance(value, str) else None
    if fraction and len(fraction[1]) > 7:
        raise ResearchError("invalid_timestamp")
    normalized = timestamp(value)
    if fraction and len(fraction[1]) == 7 and fraction[1][-1] != "0":
        return normalized.isoformat(timespec="microseconds").removesuffix("+00:00") + fraction[1][-1] + "+00:00"
    return normalized.isoformat()


def _time_key(value: str) -> tuple[datetime, int]:
    """datetime2(7)の100ns桁まで保持してUTC時刻を比較する。"""
    fraction = re.search(r"T\d{2}:\d{2}:\d{2}\.(\d+)", value)
    remainder = int(fraction[1][6]) if fraction and len(fraction[1]) == 7 else 0
    return timestamp(value), remainder


def _sha(value: Any) -> str:
    """SQL binary(32)または小文字16進64桁のSHAを検証する。"""
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).hex()
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ResearchError("invalid_receipt_key")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """固定SQL ID mapで一意に検査されたAPI IDと研究IDを保持する。"""

    api_race_id: str
    unified_race_id: str
    race_date: str
    course: str
    race_no: int
    source_snapshot_id: int
    mapping_status: str


def validate_identity_map(rows: list[dict], api_race_ids: list[str], *, expected_snapshot_id: int,
                          verified_statuses: tuple[str, ...] = ("verified",)) -> dict[str, RuntimeIdentity]:
    """明示版の登録済み対応だけを採用し、正逆の重複と業務属性不正を拒否する。

    Args:
        rows: SQLから取得したID対応と照合済み開催日・競馬場・番号。
        api_race_ids: 解決を必須とするAPI ID。文字列位置による変換をしない。
        expected_snapshot_id: 読み出すID mapの固定版。
        verified_statuses: 実データ契約で承認した状態値。曖昧状態を加えない。

    Raises:
        ResearchError: 未登録、別版、未検証、重複、属性不正。
    """
    if (not api_race_ids or len(api_race_ids) != len(set(api_race_ids)) or
            not verified_statuses or type(expected_snapshot_id) is not int or expected_snapshot_id < 1):
        raise ResearchError("invalid_identity_request")
    result, reverse = {}, set()
    for row in rows:
        try:
            key, unified = row["api_race_id"], row["unified_race_id"]
            if (key not in api_race_ids or not isinstance(unified, str) or not unified or
                    row["source_snapshot_id"] != expected_snapshot_id or
                    row["mapping_status"] not in verified_statuses):
                raise ResearchError("unresolved_id")
            if key in result or unified in reverse:
                raise ResearchError("ambiguous_id")
            day = row["race_date"]
            if str(date.fromisoformat(day)) != day or not row["course"] or type(row["race_no"]) is not int or not 1 <= row["race_no"] <= 12:
                raise ResearchError("identity_attribute_mismatch")
            result[key] = RuntimeIdentity(key, unified, day, row["course"], row["race_no"],
                                          expected_snapshot_id, row["mapping_status"])
            reverse.add(unified)
        except (KeyError, TypeError, ValueError):
            raise ResearchError("unresolved_id") from None
    if set(result) != set(api_race_ids):
        raise ResearchError("unresolved_id")
    return result


def read_receipt_rows(reader, identities: list[RuntimeIdentity], *, knowledge_cutoff: str,
                      max_rows: int = 10000, max_payload_bytes: int | None = None) -> list[dict]:
    """既存race hash索引から同じ元ID・固定時点の3operationだけを有界取得する。

    Args:
        reader: preflight済みSELECT専用reader。
        identities: 固定版で解決済みのAPIレースID集合。
        knowledge_cutoff: timezone付きの受領日時上限。
        max_rows: 全ID合計の最大receipt行数。
        max_payload_bytes: 全ID合計のUTF16本文byte予算。Noneなら本文容量制限を省略。
    Returns:
        SHAとUTC日時を正規化したメモリ内receipt行。
    Raises:
        ResearchError: 不正要求、行数/本文容量超過、race ID不一致、SQL失敗。
    Notes:
        ResearchReaderのcursor/timeout/秘密除去を使う。接続・権限・索引preflightは
        呼出側の責務であり、この関数は別loginへ切り替えない。上限超過で全体を破棄する。
        max_payload_bytesを指定した場合、全ID合計のUTF16本文byteをSQL側で集計し、
        予算を超えた本文をNULLに置換して送信を抑止する。返された部分結果も利用しない。
    """
    if (not identities or len(identities) > 500 or len({i.api_race_id for i in identities}) != len(identities)
            or type(max_rows) is not int or not 1 <= max_rows <= 100000
            or (max_payload_bytes is not None and
                (type(max_payload_bytes) is not int or max_payload_bytes < 1))):
        raise ResearchError("invalid_receipt_query", 3)
    cutoff = _utc(knowledge_cutoff).removesuffix("+00:00")
    rows = []
    payload_bytes = 0
    for identity in identities:
        race_id = identity.api_race_id
        sql = ("SELECT TOP (?) request_sha256,operation,race_id,payload_json,"
               "CONVERT(varchar(33),received_at_utc,126) received_at_utc "
               "FROM api_runtime.write_receipts WHERE race_sha256=CONVERT(binary(32),?) "
               "AND CONVERT(varbinary(max),race_id)=CONVERT(varbinary(max),CONVERT(nvarchar(max),?)) "
               "AND received_at_utc<=CONVERT(datetime2(7),?) AND operation IN (N'race_card',N'odds',N'race_result') "
               "ORDER BY received_at_utc,request_sha256")
        remaining = max_rows - len(rows)
        params = (remaining + 1, hashlib.sha256(race_id.encode("utf-16le")).digest(), race_id, cutoff)
        if max_payload_bytes is not None:
            # 先にTOPとキー/時点で候補を限定し、その集合の総byteだけで本文送信を判定する。
            sql = ("SELECT request_sha256,operation,race_id,received_at_utc,"
                   "CASE WHEN SUM(CONVERT(bigint,DATALENGTH(payload_json))) OVER ()<=? "
                   "THEN payload_json ELSE NULL END payload_json,"
                   "CONVERT(bigint,DATALENGTH(payload_json)) payload_byte_count "
                   "FROM (" + sql + ") bounded_receipts ORDER BY received_at_utc,request_sha256")
            params = (max_payload_bytes - payload_bytes, *params)
        with reader._cursor("runtime:receipt_by_race_cutoff", sql, params) as cursor:
            names = [column[0] for column in cursor.description]
            batch = cursor.fetchmany(remaining + 1)
        if len(batch) > remaining:
            raise ResearchError("receipt_row_limit", 4, maximum=max_rows)
        for raw in batch:
            row = dict(zip(names, raw, strict=True))
            if max_payload_bytes is not None:
                size = row.pop("payload_byte_count")
                if row["payload_json"] is None or type(size) is not int or size < 0:
                    raise ResearchError("receipt_payload_limit", 4, maximum=max_payload_bytes)
                payload_bytes += size
                if payload_bytes > max_payload_bytes:
                    raise ResearchError("receipt_payload_limit", 4, maximum=max_payload_bytes)
            if row["race_id"] != race_id:
                raise ResearchError("race_hash_mismatch", 3)
            row["request_sha256"] = _sha(row["request_sha256"])
            row["received_at_utc"] = _utc(row["received_at_utc"], sql_utc=True)
            rows.append(row)
    return rows


def _payload(row: dict, identity: RuntimeIdentity, operation: str) -> tuple[dict, dict]:
    """現保存契約のpayloadを検査し、wrapperとoperation本体を返す。"""
    try:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise ValueError("object")
        if operation == "race_card":
            if set(payload) != {"date", "course", "race_no", "card"}:
                raise ResearchError("unsupported_receipt_payload_version")
            if (payload["date"] != identity.race_date or payload["course"] != identity.course or
                    payload["race_no"] != identity.race_no):
                raise ResearchError("identity_attribute_mismatch")
            observed, model = payload["card"], RaceCard
        elif operation == "odds":
            if set(payload) != {"bet_type", "odds_timing", "odds"}:
                raise ResearchError("unsupported_receipt_payload_version")
            observed, model = payload["odds"], RaceOdds
        else:
            observed, model = payload, RaceResult
        if not isinstance(observed, dict) or set(observed) - set(model.model_fields):
            raise ResearchError("unsupported_receipt_payload_version")
        collections = {"race_card": ("runners",), "odds": ("entries", "odds"), "race_result": ("results", "payouts")}[operation]
        if any(name not in observed for name in ("race_id", "fetched_at", "source", *collections)):
            raise ResearchError("invalid_receipt_payload")
        if observed["race_id"] != identity.api_race_id or not isinstance(observed["source"], str) or not observed["source"]:
            raise ResearchError("identity_attribute_mismatch")
        model.model_validate(observed)
        _utc(observed["fetched_at"])
        # DB receipt SHAはcache応答metadataを除いた保存時の業務payloadを識別する。
        business = json.loads(canonical_json(payload))
        business_observed = business.get("card") if operation == "race_card" else business.get("odds") if operation == "odds" else business
        business_observed.pop("cache_hit", None)
        business_observed.pop("meta", None)
        expected = hashlib.sha256((operation + "\n" + identity.api_race_id + "\n" + canonical_json(business)).encode("utf-8")).hexdigest()
        if row.get("request_sha256") is not None and expected != _sha(row["request_sha256"]):
            raise ResearchError("receipt_digest_mismatch")
        return payload, observed
    except ResearchError:
        raise
    except (KeyError, TypeError, ValueError):
        raise ResearchError("invalid_receipt_payload") from None


def _has_market(payload: dict, observed: dict, bet_type: str) -> bool:
    """実writerと同じ優先順で券種を解決し、多券種dictと要求wrapperを区別する。"""
    if observed["odds"]:
        return bet_type in observed["odds"]
    return (payload["bet_type"] or observed["bet_type"] or "unknown") == bet_type


def _validate_win_settlement(observed: dict) -> None:
    """通常着順と同じ本文の単勝払戻を照合し、不明精算を全外れへ変換しない。

    Notes:
        現RaceResultには返還/取消の精算状態列が無い。通常整数着順と正額単勝以外は停止する。
        同着は馬ごとの払戻を保持する。他券種の的中判定・精算完全性はこの関数で証明しない。
    """
    payouts, winners = observed["payouts"], set()
    if not payouts:
        raise ResearchError("missing_payout")
    for entry in observed["results"]:
        rank = entry["rank"]
        if not isinstance(rank, str) or not rank.isascii() or not rank.isdigit() or not 1 <= int(rank) <= len(observed["results"]):
            raise ResearchError("settlement_unknown")
        if int(rank) == 1:
            winners.add(horse_number(entry["horse_no"]))
    published = set()
    for row in payouts:
        raw = row["payout"].strip()
        if (re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:円)?", raw) is None or
                int(raw.removesuffix("円").replace(",", "")) <= 0 or not row["combination"].strip()):
            raise ResearchError("settlement_unknown")
        if row["bet_type"] not in {"win", "単勝"}:
            continue
        number = horse_number(row["combination"].strip())
        if number in published:
            raise ResearchError("duplicate_key")
        published.add(number)
    if not published:
        raise ResearchError("missing_payout")
    if not winners or winners != published:
        raise ResearchError("winner_payout_mismatch")


def _validate_roster(observed: dict, operation: str, bet_type: str | None) -> None:
    """operation内の馬番重複と明細の券種混入を検査する。"""
    if operation in {"race_card", "race_result"}:
        rows = observed["runners" if operation == "race_card" else "results"]
        horses = [horse_number(row.get("horse_no")) for row in rows]
        if not horses:
            raise ResearchError("roster_mismatch")
        if len(set(horses)) != len(horses):
            raise ResearchError("duplicate_key")
        if operation == "race_result":
            _validate_win_settlement(observed)
    else:
        selected = observed["odds"].get(bet_type) if observed["odds"] else observed["entries"]
        if not selected:
            raise ResearchError("missing_odds")
        combinations = []
        for row in selected:
            if row.get("bet_type") not in (None, bet_type):
                raise ResearchError("unsupported_market")
            combination = tuple(horse_number(value) for value in row["combination"])
            if not combination or len(set(combination)) != len(combination):
                raise ResearchError("invalid_combination")
            if bet_type in {"quinella", "wide", "trio"}:
                combination = tuple(sorted(combination))
            combinations.append(combination)
        if len(set(combinations)) != len(combinations):
            raise ResearchError("duplicate_key")


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    """本文をメモリだけに保持し、保存用には内容hashだけを公開する完全束。"""

    identity: RuntimeIdentity
    operation: str
    source: str
    selected_origin: str
    selection_key: str
    knowledge_cutoff: str
    known_at: str
    provider_fetched_at: str
    payload_sha256: str
    payload: dict = field(repr=False, compare=False)
    decision_cutoff: str | None = None
    announced_at: None = None
    baseline_snapshot_id: int | None = None
    bet_type: str | None = None
    odds_timing: str | None = None

    def evidence(self) -> dict:
        """元本文を含めず、固定版と利用可能性を区別した保存可能な証跡を返す。"""
        return {"adapter_version": ADAPTER_VERSION, "api_race_id": self.identity.api_race_id,
                "unified_race_id": self.identity.unified_race_id, "id_map_snapshot_id": self.identity.source_snapshot_id,
                "operation": self.operation, "source": self.source, "selected_origin": self.selected_origin,
                "selection_key": self.selection_key, "knowledge_cutoff": self.knowledge_cutoff,
                "known_at": self.known_at, "received_at_utc": self.known_at if self.selected_origin == "receipt" else None,
                "provider_fetched_at": self.provider_fetched_at, "announced_at": None,
                "decision_cutoff": self.decision_cutoff, "baseline_snapshot_id": self.baseline_snapshot_id,
                "bet_type": self.bet_type, "odds_timing": self.odds_timing,
                "payload_sha256": self.payload_sha256, "availability": "research_only",
                "settlement_verified_market": "win" if self.operation == "race_result" else None,
                "strict_live_replay_eligible": False, "availability_reason": "unproven_live_time"}

    def content_digest(self) -> str:
        """選択キー・時点・全本文をcanonical化したreplay照合digestを返す。"""
        if digest(self.payload) != self.payload_sha256:
            raise ResearchError("source_changed", 5)
        return digest(self.evidence())


def _selection_arguments(operation: str, source: str, bet_type: str | None, odds_timing: str | None) -> None:
    """operationと市場条件の省略による別束混入を拒否する。"""
    if operation not in OPERATIONS or not isinstance(source, str) or not source:
        raise ResearchError("invalid_runtime_selection")
    if operation == "odds" and (not isinstance(bet_type, str) or not bet_type or not isinstance(odds_timing, str) or not odds_timing):
        raise ResearchError("explicit_market_required")
    if operation != "odds" and (bet_type is not None or odds_timing is not None):
        raise ResearchError("invalid_runtime_selection")


def select_runtime_bundle(rows: list[dict], identity: RuntimeIdentity, *, operation: str, source: str,
                          knowledge_cutoff: str, decision_cutoff: str | None = None,
                          bet_type: str | None = None, odds_timing: str | None = None) -> RuntimeBundle:
    """同operation/source/市場でcutoff以前の最新受領束を選び、同時刻異本文を拒否する。

    Notes:
        公表時刻は現payloadに存在せず、strict_liveを証明しない。結果の親・明細・払戻は
        一つのpayloadをそのまま保持する。本文不正や曖昧版を古い版で隠さない。
    """
    _selection_arguments(operation, source, bet_type, odds_timing)
    cutoff = _utc(knowledge_cutoff)
    decision = _utc(decision_cutoff) if decision_cutoff is not None else None
    eligible, after_decision = [], False
    seen = set()
    for row in rows:
        if row.get("race_id") != identity.api_race_id or row.get("operation") != operation:
            continue
        received = _utc(row["received_at_utc"], sql_utc=True)
        if _time_key(received) > _time_key(cutoff):
            continue
        key = _sha(row["request_sha256"])
        if key in seen:
            raise ResearchError("duplicate_key")
        seen.add(key)
        payload, observed = _payload(row, identity, operation)
        if observed["source"] != source:
            continue
        if operation == "odds" and (not _has_market(payload, observed, bet_type) or payload["odds_timing"] != odds_timing):
            continue
        fetched = _utc(observed["fetched_at"])
        if decision and (_time_key(received) > _time_key(decision) or _time_key(fetched) > _time_key(decision)):
            after_decision = True
            continue
        _validate_roster(observed, operation, bet_type)
        eligible.append((received, key, payload, observed))
    if not eligible:
        raise ResearchError("after_cutoff" if after_decision else "replay_unavailable")
    latest = max(_time_key(item[0]) for item in eligible)
    selected = [item for item in eligible if _time_key(item[0]) == latest]
    if len({digest(item[2]) for item in selected}) > 1:
        raise ResearchError("ambiguous_revision")
    received, key, payload, observed = min(selected, key=lambda item: item[1])
    fetched = _utc(observed["fetched_at"])
    return RuntimeBundle(identity, operation, source, "receipt", key, cutoff, received, fetched,
                         digest(payload), payload, decision, bet_type=bet_type, odds_timing=odds_timing)


def baseline_bundle(payload: dict, identity: RuntimeIdentity, *, operation: str, source: str,
                    snapshot_id: int, source_key: str, captured_known_at: str, knowledge_cutoff: str,
                    decision_cutoff: str | None = None, bet_type: str | None = None,
                    odds_timing: str | None = None) -> RuntimeBundle:
    """同race/sourceの明示snapshot34完全束をcapture以降に限定して採用する。

    Notes:
        呼出側が同じSQL snapshotから完全束を復元する。元fetched_atへknown_atを遡及しない。
        現在業務表、他source、receiptとの列単位補完は実装しない。
    """
    _selection_arguments(operation, source, bet_type, odds_timing)
    if snapshot_id != 34 or source_key != "analysis-current":
        raise ResearchError("unexpected_baseline")
    known, cutoff = _utc(captured_known_at), _utc(knowledge_cutoff)
    decision = _utc(decision_cutoff) if decision_cutoff is not None else None
    if _time_key(known) > _time_key(cutoff) or decision and _time_key(known) > _time_key(decision):
        raise ResearchError("after_cutoff")
    copied, observed = _payload({"payload_json": canonical_json(payload)}, identity, operation)
    if observed["source"] != source:
        raise ResearchError("version_conflict")
    if operation == "odds" and (not _has_market(copied, observed, bet_type) or copied["odds_timing"] != odds_timing):
        raise ResearchError("version_conflict")
    _validate_roster(observed, operation, bet_type)
    fetched = _utc(observed["fetched_at"])
    if decision and _time_key(fetched) > _time_key(decision):
        raise ResearchError("after_cutoff")
    return RuntimeBundle(identity, operation, source, "baseline", f"analysis-current:{snapshot_id}", cutoff,
                         known, fetched, digest(copied), copied, decision, baseline_snapshot_id=snapshot_id,
                         bet_type=bet_type, odds_timing=odds_timing)


def select_whole_bundle(candidates: list[RuntimeBundle], *, priority: tuple[str, ...]) -> RuntimeBundle:
    """明示されたorigin優先順で一つの完全束だけを採用し、断片の補完をしない。"""
    if not priority or len(set(priority)) != len(priority) or set(priority) - {"receipt", "baseline"}:
        raise ResearchError("explicit_source_priority_required")
    if not candidates:
        raise ResearchError("replay_unavailable")
    reference = candidates[0]
    for item in candidates:
        if (item.identity != reference.identity or item.operation != reference.operation or item.source != reference.source
                or item.knowledge_cutoff != reference.knowledge_cutoff or item.decision_cutoff != reference.decision_cutoff
                or item.bet_type != reference.bet_type or item.odds_timing != reference.odds_timing):
            raise ResearchError("version_conflict")
        item.content_digest()
    for origin in priority:
        matches = [item for item in candidates if item.selected_origin == origin]
        if len(matches) > 1:
            raise ResearchError("ambiguous_revision")
        if matches:
            return matches[0]
    raise ResearchError("replay_unavailable")


def verify_runtime_replay(bundle: RuntimeBundle, expected_digest: str) -> None:
    """固定条件で再選択した束の全本文・選択証跡digest一致を必須にする。"""
    if bundle.content_digest() != _sha(expected_digest):
        raise ResearchError("source_changed", 5)
