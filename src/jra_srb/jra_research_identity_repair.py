"""概要: 登録済みfull16と独立JV参照を照合し、承認後の限定補修計画を扱う。
作成日: 2026-10-16
入力: 登録map行、独立snapshot31 history.races行、承認済み管理接続。
出力: digest/countだけを公開する補修planと更新後summary。
実行例: 本moduleはCLIを持たない。apply_repair_planは明示承認後のみ呼び出す。
注意事項: DB更新は未承認。DDL・temp table・reader権限変更は行わず、scopeは3455件に固定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .jra_history_dataset import COURSE_CODES
from .jra_research_contracts import ResearchError

TARGET_COUNT = 3455
DEPENDENT_VIEWS = (
    "history.v_races", "history.v_entries", "history.v_payouts", "market.v_odds_selected",
    "market.v_odds_observations", "prediction.v_features_asof", "prediction.v_predictions",
    "prediction.v_evaluations", "prediction.v_bets",
)
OLD_EVIDENCE_KEYS = frozenset((
    "source_relation", "original_id", "stored_full_id", "stored_date", "stored_venue", "stored_race_no", "rule",
))
OLD_EVIDENCE_RULE = "stored_full16_and_coordinates; no 12-to-16 synthesis"
NEW_EVIDENCE_RULE = "registered_full16_reference_v1_no_id_synthesis"
MAP_FIELDS = (
    "map_id", "source_snapshot_id", "source_relation", "source_original_id", "api_race_id",
    "jv_race_key_full_16", "race_date", "venue_code", "race_no", "unified_race_id",
    "mapping_status", "evidence_json", "source_row_sha256",
)
REFERENCE_FIELDS = ("source_rowid", "race_key_full", "race_date", "venue_code", "race_no", "selected_sha256")


@dataclass(frozen=True, repr=False)
class _RepairItem:
    """単一map行の旧値、独立参照値、新しい登録値を内部だけで保持する。"""
    map_before: tuple[Any, ...]
    reference_before: tuple[Any, ...]
    new_venue_code: str
    new_unified_race_id: str
    new_evidence_json: str


@dataclass(frozen=True, repr=False)
class RepairPlan:
    """実行対象行を内部保持し、外部には件数とdigestだけを公開する。"""
    count: int
    mapping_digest_sha256: str
    reference_digest_sha256: str
    plan_digest_sha256: str
    _items: tuple[_RepairItem, ...] = field(repr=False)

    @property
    def summary(self) -> dict[str, Any]:
        """個別IDや本文を含めず、planの件数・digestだけを返す。"""
        return {"count": self.count, "mapping_digest_sha256": self.mapping_digest_sha256,
                "reference_digest_sha256": self.reference_digest_sha256,
                "plan_digest_sha256": self.plan_digest_sha256}

    def __repr__(self) -> str:
        """行データを露出せず、planのsummaryだけを表す。"""
        return f"RepairPlan({self.summary!r})"


def _iso_date(value: Any) -> str:
    """date/datetime/ISO文字列を日付ISOへ正規化する。"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


def _id_bytes(value: Any) -> bytes:
    """API元IDを文字列のUTF-16LE表現として厳密に返す。"""
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_id")
    return value.encode("utf-16le")


def _sha_hex(value: Any) -> str:
    """32-byte値または64桁hexを小文字SHA256文字列へ正規化する。"""
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) != 32:
            raise ValueError("invalid_sha256")
        return raw.hex()
    if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return value.lower()
    raise ValueError("invalid_sha256")


def _digest(value: Any) -> str:
    """安定したcanonical JSONのSHA256 digestを返す。"""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _map_values(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """指定されたmap列を固定順で抽出し、日付・shaを正規化する。"""
    values = [row[name] for name in MAP_FIELDS]
    values[6] = _iso_date(values[6])
    values[12] = _sha_hex(values[12])
    return tuple(values)


def _reference_values(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """独立参照列を固定順で抽出し、日付・SHAを正規化する。"""
    values = [row[name] for name in REFERENCE_FIELDS]
    values[2] = _iso_date(values[2])
    values[5] = _sha_hex(values[5])
    return tuple(values)


def _check_old_evidence(row: Mapping[str, Any], full16: str, day: str, race_no: int) -> dict[str, Any]:
    """旧7-key evidenceを厳密検証し、誤った走路説明を場コードに使わず返す。"""
    evidence = json.loads(row["evidence_json"])
    if not isinstance(evidence, dict) or set(evidence) != OLD_EVIDENCE_KEYS:
        raise ValueError("old_evidence_schema")
    if evidence["rule"] != OLD_EVIDENCE_RULE or evidence["source_relation"] != "live.races":
        raise ValueError("old_evidence_rule")
    if _id_bytes(evidence["original_id"]) != _id_bytes(row["source_original_id"]):
        raise ValueError("old_evidence_original_id")
    if evidence["stored_full_id"] != full16 or evidence["stored_date"] != day:
        raise ValueError("old_evidence_identity")
    if type(evidence["stored_race_no"]) is not int or evidence["stored_race_no"] != race_no:
        raise ValueError("old_evidence_race_no")
    if not isinstance(evidence["stored_venue"], str) or not evidence["stored_venue"]:
        raise ValueError("old_evidence_venue_label")
    return evidence


def validate_reference_evidence(mapping: Mapping[str, Any]) -> None:
    """新v2 evidenceを登録mapのfull16・座標・API元ID・独立参照へ照合する。

    Args:
        mapping: SQL readerが返すmap列。source_row_sha256は不要。
    Raises:
        ResearchError: schema、status、ID、venue、日付、race番号または参照の不一致。
    """
    try:
        if mapping["source_snapshot_id"] != 34 or mapping["source_relation"] != "live.races":
            raise ValueError("registration_source")
        if mapping["mapping_status"] != "verified":
            raise ValueError("mapping_status")
        original = mapping["source_original_id"]
        if _id_bytes(mapping["api_race_id"]) != _id_bytes(original):
            raise ValueError("native_api_id")
        full = mapping["jv_race_key_full_16"]
        if not isinstance(full, str) or not re.fullmatch(r"[0-9]{16}", full):
            raise ValueError("full16")
        day, number = _iso_date(mapping["race_date"]), mapping["race_no"]
        venue = mapping["venue_code"]
        if mapping["unified_race_id"] != "JRA:" + full or full[:8] != day.replace("-", ""):
            raise ValueError("unified_or_date")
        if venue not in COURSE_CODES or full[8:10] != venue:
            raise ValueError("venue_code")
        if type(number) is not int or int(full[-2:]) != number:
            raise ValueError("race_no")
        evidence = json.loads(mapping["evidence_json"])
        expected_keys = {"source_relation", "original_id", "stored_full_id", "stored_date", "stored_race_no",
                         "source_venue_label", "rule", "reference"}
        if not isinstance(evidence, dict) or set(evidence) != expected_keys:
            raise ValueError("evidence_schema")
        if evidence["rule"] != NEW_EVIDENCE_RULE or evidence["source_relation"] != "live.races":
            raise ValueError("evidence_rule")
        if _id_bytes(evidence["original_id"]) != _id_bytes(original):
            raise ValueError("evidence_original_id")
        if (evidence["stored_full_id"] != full or evidence["stored_date"] != day
                or type(evidence["stored_race_no"]) is not int or evidence["stored_race_no"] != number):
            raise ValueError("evidence_coordinates")
        if not isinstance(evidence["source_venue_label"], str) or not evidence["source_venue_label"]:
            raise ValueError("source_venue_label")
        reference = evidence["reference"]
        ref_keys = {"source_snapshot_id", "source_relation", "source_rowid", "selected_sha256",
                    "race_key_full", "race_date", "venue_code", "race_no"}
        if not isinstance(reference, dict) or set(reference) != ref_keys:
            raise ValueError("reference_schema")
        if reference["source_snapshot_id"] != 31 or reference["source_relation"] != "history.races":
            raise ValueError("reference_source")
        if type(reference["source_rowid"]) is not int or reference["source_rowid"] <= 0:
            raise ValueError("reference_rowid")
        _sha_hex(reference["selected_sha256"])
        if (reference["race_key_full"] != full or _iso_date(reference["race_date"]) != day
                or reference["venue_code"] != venue or type(reference["race_no"]) is not int
                or reference["race_no"] != number):
            raise ValueError("reference_identity")
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        raise ResearchError("invalid_reference_evidence", 4) from None


def build_repair_plan(mapping_rows: Sequence[Mapping[str, Any]], reference_rows: Sequence[Mapping[str, Any]], expected_count: int = TARGET_COUNT) -> RepairPlan:
    """登録full16とJV snapshot31を完全一致照合し、digest限定planを作る。

    Args:
        mapping_rows: snapshot34/live.races/2025 unresolvedの既存map行。
        reference_rows: snapshot31/history.racesから独立走査した参照行。
        expected_count: 必須対象件数。productionでは3455。
    Returns:
        個別行を非公開で保持し、件数とdigestだけを公開するRepairPlan。
    Raises:
        ResearchError: 件数、schema、重複、ID、SHA、座標または参照一意性の違反。
    Notes:
        API IDをJV IDへ組み替えず、登録済みfull16だけを照合する。SQL/IOなし。
    """
    try:
        if type(expected_count) is not int or expected_count <= 0 or len(mapping_rows) != expected_count:
            raise ValueError("target_count")
        reference_by_identity: dict[tuple[str, str, int], tuple[Mapping[str, Any], tuple[Any, ...]]] = {}
        ref_rowids, ref_fulls, ref_coordinates = set(), set(), set()
        for reference in reference_rows:
            values = _reference_values(reference)
            source_rowid, full, day, venue, race_no, selected_sha = values
            if type(reference["source_snapshot_id"]) is not int or reference["source_snapshot_id"] != 31 or reference["source_relation"] != "history.races":
                raise ValueError("reference_source")
            if type(source_rowid) is not int or source_rowid <= 0 or not isinstance(full, str) or not re.fullmatch(r"[0-9]{16}", full):
                raise ValueError("reference_identity")
            if not day.startswith("2025-") or venue not in COURSE_CODES or type(race_no) is not int or not 1 <= race_no <= 12:
                raise ValueError("reference_coordinates")
            if full[:8] != day.replace("-", "") or full[8:10] != venue or int(full[-2:]) != race_no:
                raise ValueError("reference_key_coordinates")
            coordinate = (day, venue, race_no)
            key = (full, day, race_no)
            if source_rowid in ref_rowids or full in ref_fulls or coordinate in ref_coordinates or key in reference_by_identity:
                raise ValueError("duplicate_reference")
            ref_rowids.add(source_rowid)
            ref_fulls.add(full)
            ref_coordinates.add(coordinate)
            reference_by_identity[key] = (reference, values)

        map_ids, native_ids, full_ids, map_signatures = set(), set(), set(), set()
        used_ref_rowids: set[int] = set()
        items: list[_RepairItem] = []
        map_digest_rows, ref_digest_rows, candidate_digest_rows = [], [], []
        for mapping in mapping_rows:
            old = _map_values(mapping)
            (map_id, snapshot, relation, original, api_id, full, day, old_venue, race_no,
             old_unified, status, old_evidence_json, old_sha) = old
            if type(snapshot) is not int or snapshot != 34 or relation != "live.races" or status != "unresolved" or not day.startswith("2025-"):
                raise ValueError("mapping_scope")
            if type(map_id) is not int or map_id <= 0 or type(race_no) is not int or not 1 <= race_no <= 12:
                raise ValueError("mapping_key")
            if not isinstance(full, str) or not re.fullmatch(r"[0-9]{16}", full):
                raise ValueError("registered_full16")
            if full[:8] != day.replace("-", "") or full[-2:] != f"{race_no:02d}":
                raise ValueError("mapping_coordinates")
            if full in full_ids or map_id in map_ids or _id_bytes(original) in native_ids:
                raise ValueError("duplicate_mapping_identity")
            if _id_bytes(api_id) != _id_bytes(original):
                raise ValueError("api_original_id_mismatch")
            # unified_race_idはNOT NULLの実列なので、既存値をCAS旧値として保持する。
            if old_venue not in (None, ""):
                raise ValueError("unresolved_venue_not_empty")
            evidence = _check_old_evidence(mapping, full, day, race_no)
            identity = (full, day, race_no)
            matched = reference_by_identity.get(identity)
            if matched is None:
                raise ValueError("missing_reference_match")
            reference, ref_values = matched
            source_rowid, ref_full, ref_day, venue, ref_no, selected_sha = ref_values
            if venue not in COURSE_CODES or source_rowid in used_ref_rowids:
                raise ValueError("reference_not_unique")
            if (ref_full, ref_day, ref_no) != (full, day, race_no):
                raise ValueError("reference_mismatch")
            used_ref_rowids.add(source_rowid)
            new_evidence = {
                "source_relation": "live.races", "original_id": original,
                "stored_full_id": full, "stored_date": day, "stored_race_no": race_no,
                "source_venue_label": evidence["stored_venue"], "rule": NEW_EVIDENCE_RULE,
                "reference": {"source_snapshot_id": 31, "source_relation": "history.races",
                              "source_rowid": source_rowid, "selected_sha256": selected_sha,
                              "race_key_full": ref_full, "race_date": ref_day,
                              "venue_code": venue, "race_no": ref_no},
            }
            evidence_json = json.dumps(new_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            item = _RepairItem(old, ref_values, venue, "JRA:" + full, evidence_json)
            items.append(item)
            map_ids.add(map_id)
            native_ids.add(_id_bytes(original))
            full_ids.add(full)
            map_digest_rows.append([map_id, snapshot, relation, original, api_id, full, day, old_venue,
                                    race_no, old_unified, status, old_evidence_json, old_sha])
            ref_digest_rows.append(list(ref_values))
            candidate_digest_rows.append([map_id, source_rowid, venue, "JRA:" + full, evidence_json])
        if len(items) != expected_count or len(used_ref_rowids) != expected_count:
            raise ValueError("matched_count")
        ordered = sorted(zip(map_digest_rows, ref_digest_rows, candidate_digest_rows, strict=True), key=lambda row: row[0][0])
        mapping_digest = _digest([row[0] for row in ordered])
        reference_digest = _digest(sorted((row[1] for row in ordered), key=lambda row: row[0]))
        plan_digest = _digest([row[2] for row in ordered])
        items.sort(key=lambda item: item.map_before[0])
        return RepairPlan(expected_count, mapping_digest, reference_digest, plan_digest, tuple(items))
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError) as error:
        reason = str(error) if str(error) and str(error).isidentifier() else "invalid_repair_plan"
        raise ResearchError(reason, 4) from None


def _dict_rows(cursor: Any, columns: Sequence[str]) -> list[dict[str, Any]]:
    """cursor結果を列名付きdictへ変換する。"""
    rows = cursor.fetchall()
    result = []
    for row in rows:
        if isinstance(row, Mapping):
            result.append(dict(row))
        else:
            result.append(dict(zip(columns, row, strict=True)))
    return result


def _same_value(left: Any, right: Any) -> bool:
    """DB再読値とplan値を文字列byte・日付・SHAの意味を保って比較する。"""
    if left is None or right is None:
        return left is right
    if isinstance(left, str) and isinstance(right, str):
        return left.encode("utf-16le") == right.encode("utf-16le")
    if isinstance(left, (bytes, bytearray, memoryview)) or isinstance(right, (bytes, bytearray, memoryview)):
        try:
            return _sha_hex(left) == _sha_hex(right)
        except ValueError:
            return bytes(left) == bytes(right)
    if isinstance(left, (date, datetime)) or isinstance(right, (date, datetime)):
        try:
            return _iso_date(left) == _iso_date(right)
        except ValueError:
            return False
    return left == right


def _execute(cursor: Any, sql: str, params: Sequence[Any] = ()) -> None:
    """SQLとbound parametersをcursorへ渡す。"""
    try:
        cursor.execute(sql, tuple(params))
    except Exception as error:
        # SQL本文・bound値・接続秘密を保存せず、driver診断の分類だけを残す。
        message = str(error)
        state = re.search(r"\b(?:HY[0-9]{3}|[0-9]{2}[A-Z0-9]{3})\b", message)
        code = re.search(r"\(([0-9]{3,6})\)", message)
        query = sql.split("*/", 1)[0] + "*/" if sql.startswith("/* repair:") else sql.split(" ", 1)[0]
        raise ResearchError("identity_repair_sql_failed", 4, error_type=type(error).__name__,
                            query_id=query, sqlstate=state.group(0) if state else None,
                            native_code=code.group(1) if code else None) from None


def _row_dict(cursor: Any, columns: Sequence[str]) -> dict[str, Any] | None:
    """fetchoneのtuple/mapを列名dictへ変換する。"""
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True))


def _mapping_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """ロック下で再読したmap行を固定列順へ正規化する。"""
    return _map_values(row)


def _verify_plan_integrity(plan: RepairPlan) -> None:
    """非公開plan行から全digestと更新内容を再構築し、改変を拒否する。"""
    maps, refs = [], []
    for item in plan._items:
        before = dict(zip(MAP_FIELDS, item.map_before, strict=True))
        ref = dict(zip(REFERENCE_FIELDS, item.reference_before, strict=True))
        ref.update(source_snapshot_id=31, source_relation="history.races")
        maps.append(before)
        refs.append(ref)
    rebuilt = build_repair_plan(maps, refs, expected_count=TARGET_COUNT)
    if (rebuilt._items != plan._items or rebuilt.count != plan.count
            or rebuilt.mapping_digest_sha256 != plan.mapping_digest_sha256
            or rebuilt.reference_digest_sha256 != plan.reference_digest_sha256
            or rebuilt.plan_digest_sha256 != plan.plan_digest_sha256):
        raise ResearchError("identity_repair_plan_integrity_failed", 4)


def _reference_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """ロック下で再読したJV行の使用列を固定順へ正規化する。"""
    values = tuple(row[name] for name in REFERENCE_FIELDS)
    return (values[0], values[1], _iso_date(values[2]), values[3], values[4], _sha_hex(values[5]))


def apply_repair_plan(connection: Any, plan: RepairPlan, *, approved: bool = False, metadata_verified: bool = False) -> dict[str, Any]:
    """明示承認とschema/index事前検証後、CAS・transaction付きで限定map更新する。

    Args:
        connection: jra_unified管理接続。autocommit=Falseが必須。
        plan: build_repair_planが返したdigest限定plan。
        approved: 利用者の明示承認がある場合だけTrueにする。
        metadata_verified: 列型、map_id PK、map source prefix、reference unique(snapshot,rowid)、
            9つの依存view参照条件を確認済みの場合だけTrue。
    Returns:
        更新statusと件数/digestのみ。
    Raises:
        ResearchError: 承認・接続・権限・source・行値・競合・件数の不一致。失敗時rollback。
    Notes:
        実データ更新は承認されていない。呼出側は承認前に本関数を呼ばない。
        metadata_verifiedは列型/index契約と依存view確認の完了を意味する。対象viewは
        DEPENDENT_VIEWSの9件であり、存在だけで安全と推定せず参照条件を確認する。
    """
    if not approved:
        raise ResearchError("identity_repair_approval_required", 4)
    if not metadata_verified:
        raise ResearchError("identity_repair_metadata_unverified", 4)
    if getattr(connection, "autocommit", None) is not False:
        raise ResearchError("identity_repair_requires_transaction", 4)
    if not isinstance(plan, RepairPlan) or plan.count != TARGET_COUNT or len(plan._items) != TARGET_COUNT:
        raise ResearchError("identity_repair_plan_count", 4)
    _verify_plan_integrity(plan)
    cursor = None
    transaction_started = False
    try:
        cursor = connection.cursor()
        # autocommit=Falseのdriverが開始するtransactionを使い、二重BEGINを避ける。
        _execute(cursor, "SET NOCOUNT ON; SET XACT_ABORT ON")
        transaction_started = True
        _execute(cursor, "SELECT @@TRANCOUNT")
        if cursor.fetchone()[0] > 1:
            raise ResearchError("identity_repair_nested_transaction", 4)
        _execute(cursor, "SELECT DB_NAME()")
        db_row = cursor.fetchone()
        db_name = db_row[0] if not isinstance(db_row, Mapping) else next(iter(db_row.values()))
        if db_name != "jra_unified":
            raise ResearchError("identity_repair_wrong_database", 4)
        _execute(cursor, "SELECT HAS_PERMS_BY_NAME(N'history.race_identity_map',N'OBJECT',N'UPDATE'), HAS_PERMS_BY_NAME(N'history.races',N'OBJECT',N'SELECT'), HAS_PERMS_BY_NAME(N'ops.source_snapshot',N'OBJECT',N'SELECT')")
        permissions = cursor.fetchone()
        if permissions is None or not all(bool(value) for value in permissions):
            raise ResearchError("identity_repair_management_permission_required", 4)
        _execute(cursor, "SELECT s.source_snapshot_id,s.status,d.source_key FROM ops.source_snapshot AS s WITH (UPDLOCK,HOLDLOCK) JOIN ops.source_database AS d WITH (HOLDLOCK) ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id IN (?,?) ORDER BY s.source_snapshot_id", (31, 34))
        source_rows = cursor.fetchall()
        source_status = {int(row[0]): (row[1], row[2]) for row in source_rows}
        if source_status != {31: ("verified", "prediction-full-20261008"),
                             34: ("verified", "analysis-current")}:
            raise ResearchError("identity_repair_source_not_verified", 4)

        map_sql = ("SELECT map_id,source_snapshot_id,source_relation,source_original_id,api_race_id,"
                   "jv_race_key_full_16,CONVERT(varchar(10),race_date,23) race_date,venue_code,race_no,"
                   "unified_race_id,mapping_status,evidence_json,source_row_sha256 "
                   "FROM history.race_identity_map WITH (UPDLOCK,HOLDLOCK) "
                   "WHERE source_snapshot_id=? AND source_relation=? AND race_date>=? AND race_date<? AND mapping_status=? ORDER BY map_id")
        bounded_map_sql = map_sql.replace("SELECT map_id", "SELECT TOP (9000) map_id", 1)
        _execute(cursor, "/* repair:locked_map */ " + bounded_map_sql,
                 (34, "live.races", "2025-01-01", "2026-01-01", "unresolved"))
        locked_maps = _dict_rows(cursor, MAP_FIELDS)
        if len(locked_maps) >= 9000:
            raise ResearchError("identity_repair_map_cap_reached", 4)
        expected_maps = [item.map_before for item in plan._items]
        actual_maps = [_mapping_signature(row) for row in locked_maps]
        if len(actual_maps) != plan.count or sorted(actual_maps, key=lambda value: value[0]) != sorted(expected_maps, key=lambda value: value[0]):
            raise ResearchError("identity_repair_mapping_changed", 4)

        # Target IDs are chunked under SQL Server's 2100 parameter ceiling.
        for offset in range(0, plan.count, 700):
            batch = plan._items[offset:offset + 700]
            fulls = [item.map_before[5] for item in batch]
            unified = [item.new_unified_race_id for item in batch]
            placeholders = ",".join("?" for _ in batch)
            conflicts_sql = ("/* repair:identity_conflicts */ SELECT map_id,jv_race_key_full_16,unified_race_id "
                             "FROM history.race_identity_map WITH (UPDLOCK,HOLDLOCK) WHERE source_snapshot_id=? AND source_relation=? AND ("
                             f"jv_race_key_full_16 IN ({placeholders}) OR unified_race_id IN ({placeholders}))")
            _execute(cursor, conflicts_sql, (34, "live.races", *fulls, *unified))
            candidates = {item.map_before[0] for item in plan._items}
            if any(int(row[0]) not in candidates for row in cursor.fetchall()):
                raise ResearchError("identity_repair_registration_conflict", 4)

        ref_ids = [item.reference_before[0] for item in plan._items]
        ref_seen: dict[int, tuple[Any, ...]] = {}
        for offset in range(0, plan.count, 1000):
            batch_ids = ref_ids[offset:offset + 1000]
            placeholders = ",".join("?" for _ in batch_ids)
            ref_sql = ("/* repair:locked_reference */ SELECT __migration_source_rowid source_rowid,race_key_full,"
                       "CONVERT(varchar(10),race_date,23) race_date,venue_code,race_no,selected_sha256 FROM history.races WITH (HOLDLOCK) "
                       "WHERE __migration_source_snapshot_id=? AND __migration_source_rowid IN (" + placeholders + ")")
            _execute(cursor, ref_sql, (31, *batch_ids))
            for row in _dict_rows(cursor, REFERENCE_FIELDS):
                ref_seen[int(row["source_rowid"])] = _reference_signature(row)
        expected_refs = {item.reference_before[0]: item.reference_before for item in plan._items}
        if ref_seen != expected_refs:
            raise ResearchError("identity_repair_reference_changed", 4)

        updated = 0
        string_fields = {"source_relation", "source_original_id", "api_race_id", "jv_race_key_full_16",
                         "venue_code", "unified_race_id", "mapping_status", "evidence_json"}
        for item in plan._items:
            before = dict(zip(MAP_FIELDS, item.map_before, strict=True))
            clauses, where_params = [], []
            for name in MAP_FIELDS:
                value = before[name]
                if value is None:
                    clauses.append(f"{name} IS NULL")
                elif name in string_fields:
                    clauses.append(f"CONVERT(varbinary(max),CONVERT(nvarchar(max),{name}))=CONVERT(varbinary(max),CONVERT(nvarchar(max),?))")
                    where_params.append(value)
                else:
                    clauses.append(f"{name}=?")
                    if name == "source_row_sha256" and isinstance(value, str):
                        where_params.append(bytes.fromhex(value))
                    else:
                        where_params.append(value)
            sql = ("UPDATE history.race_identity_map SET venue_code=?,unified_race_id=?,mapping_status='verified',evidence_json=? "
                   "WHERE " + " AND ".join(clauses) + "; SELECT @@ROWCOUNT")
            params = (item.new_venue_code, item.new_unified_race_id, item.new_evidence_json, *where_params)
            _execute(cursor, sql, params)
            rowcount_row = cursor.fetchone()
            affected = rowcount_row[0] if rowcount_row is not None else None
            if affected != 1:
                raise ResearchError("identity_repair_compare_and_set_failed", 4)
            updated += affected
        if updated != TARGET_COUNT:
            raise ResearchError("identity_repair_updated_count_mismatch", 4)
        _execute(cursor, "SELECT @@TRANCOUNT")
        if cursor.fetchone()[0] != 1:
            raise ResearchError("identity_repair_nested_transaction", 4)
        connection.commit()
        transaction_started = False
        return {"status": "applied", "updated_count": updated, **plan.summary}
    except ResearchError:
        if transaction_started:
            try:
                connection.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if transaction_started:
            try:
                connection.rollback()
            except Exception:
                pass
        raise ResearchError("identity_repair_failed", 4) from None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
