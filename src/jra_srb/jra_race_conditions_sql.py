"""概要: 条件予想に必要な同名競走・対象馬履歴・RA条件だけをSQLで読む。
作成日: 2026-11-08。
入力: 非秘密設定、既存研究readerの環境設定、任意の追加カード。
出力: 原文を含まない解析済みデータと来歴・欠損・読取診断。
実行例: uv run python scripts/run_jra_race_conditions.py export --help
注意事項: SELECT専用。固定版以外、過大権限、破損原文、上限超過は停止する。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

from .jra_race_conditions import public_race, require, validate_card, validate_race
from .jra_research_contracts import digest, horse_number
from .jra_research_reader import ResearchReader


TABLES = ("history.races", "history.entries", "raw.year_raw_records")


def _integer(value) -> int | None:
    """数字だけの原文値を整数にし、空欄や未確定値はNoneにする。"""
    text = str(value or "").strip()
    return int(text) if text.isascii() and text.isdigit() else None


def parse_ra(payload: bytes, sha256: str, race_key: str) -> dict:
    """SDK定義のRA原文を検証し、条件コードと時点診断を抽出する。

    Args:
        payload: 保存RAの1272byte原文。
        sha256: 保存時の本文SHA256。
        race_key: 日付・場・レース番号の12桁管理キー。
    Returns:
        競走条件コードと、原文から再計算した識別値。
    Raises:
        ResearchError: 長さ・SHA・識別情報・コードの不正。
    """
    require(len(payload) == 1272 and payload[:2] == b"RA" and payload[-2:] == b"\r\n", "conditions_RA_length")
    require(hashlib.sha256(payload).hexdigest() == sha256.lower(), "conditions_RA_sha")
    require((payload[11:21] + payload[25:27]).decode("ascii") == race_key, "conditions_RA_identity")
    fields = {"grade": (614, 615), "race_type": (616, 618), "symbol": (618, 621), "weight_rule": (621, 622),
              "condition_code": (634, 637), "distance_raw": (697, 701), "track_code": (705, 707),
              "weather": (887, 888), "turf_going": (888, 889), "dirt_going": (889, 890)}
    result = {name: payload[start:end].decode("ascii").strip() for name, (start, end) in fields.items()}
    require(result["distance_raw"].isdigit() and result["track_code"].isdigit(), "conditions_RA_codes")
    return result


def normalize_row(row: dict) -> dict:
    """固定history行を共通表現へ変換し、当該結果と属性を明示的に保持する。"""
    metadata = json.loads(row["metadata"])
    attrs = json.loads(row["attrs"])
    key, day = row["race_key"], row["race_date"]
    require(key[:8] == day.replace("-", "") and len(key) == 12, "conditions_history_date")
    abnormal = str(row["abnormal_code"] or "0").strip()
    rank = _integer(row["rank"])
    return {"race_key": key, "race_date": day, "race_name": metadata.get("race_name") or "",
        "venue_code": row["venue_code"], "distance": int(metadata["distance_raw"]), "track_code": metadata["track_code"],
        "horse_id": str(row["horse_id"]), "horse_no": horse_number(row["horse_no"]), "horse_name": attrs.get("horse_name") or "",
        "age": _integer(attrs.get("age")), "sex": attrs.get("sex"), "frame_no": _integer(attrs.get("frame_no")),
        "weight_carried": (_integer(attrs.get("weight_carried_raw")) or 0) / 10,
        "jockey": attrs.get("jockey"), "trainer": attrs.get("trainer"), "rank": rank if rank and rank > 0 else None,
        "abnormal_code": abnormal, "status": "excluded" if abnormal in ("1", "2") else "active",
        "retrospective_attributes": True}


class ConditionsReader(ResearchReader):
    """既存SELECT専用接続上で、今回の範囲に固定した読取経路を提供する。"""

    def __init__(self, config: dict, connection_string: str | None = None):
        """研究接続の最小設定を渡し、条件設定を保持する。"""
        super().__init__(SimpleNamespace(raw=config), connection_string)
        self.settings = config

    def rows(self, query_id: str, sql: str, params=(), limit: int = 20000) -> list[dict]:
        """既存cursorの秘密保護を使い、指定上限までをbyte値を保持して読む。"""
        with self._cursor(query_id, sql, params) as cursor:
            names = [c[0] for c in cursor.description]
            values = cursor.fetchmany(limit + 1)
            require(len(values) <= limit, "conditions_SQL_row_limit")
            return [dict(zip(names, row, strict=True)) for row in values]

    def preflight(self) -> dict:
        """固定DB・reader権限・sourceの状態を確認し、書込可能なら拒否する。"""
        identity = self._small("conditions:identity", "SELECT DB_NAME() db,IS_ROLEMEMBER('db_owner') owner_role,"
            "IS_SRVROLEMEMBER('sysadmin') admin_role,IS_ROLEMEMBER('db_datawriter') writer_role")[0]
        require(identity == {"db": "jra_unified", "owner_role": 0, "admin_role": 0, "writer_role": 0}, "conditions_reader_role")
        for table in (*TABLES, "ops.source_snapshot", "ops.source_database"):
            for permission in ("SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL"):
                value = self._small("conditions:permissions", "SELECT HAS_PERMS_BY_NAME(?,N'OBJECT',?) permitted",
                                    (table, permission))[0]["permitted"]
                require(value == int(permission == "SELECT"), "conditions_reader_permissions")
        source = self._small("conditions:source", "SELECT d.source_key,s.status FROM ops.source_snapshot s "
            "JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (31,))
        require(source == [{"source_key": self.settings["source_key"], "status": "verified"}], "conditions_source_not_verified")
        self.report = {"identity": identity, "source": source[0], "snapshot": 31, "scope": "fixed_retrospective_research"}
        return self.report

    def target_races(self) -> list[dict]:
        """同名競走の候補を固定年範囲から取得する。"""
        rows = self.rows("conditions:targets", "SELECT TOP (51) race_key,CONVERT(varchar(10),race_date,23) race_date,"
            "venue_code,retrospective_metadata_json metadata,__unified_race_sha256 race_hash FROM history.races "
            "WHERE __migration_source_snapshot_id=31 AND race_date>=? AND race_date<? "
            "AND JSON_VALUE(retrospective_metadata_json,'$.race_name')=? ORDER BY race_date,race_key",
            (f"{self.settings['first_year']}-01-01", f"{self.settings['last_year']+1}-01-01", self.settings["race_name"]), 50)
        require(bool(rows) and len({r["race_date"][:4] for r in rows}) == len(rows), "conditions_target_year_identity")
        return rows

    def target_entries(self, races: list[dict]) -> list[dict]:
        """保存hashと文字列の同値で対象出走行だけを読む。"""
        values, params = [], []
        for race in races:
            values.append("(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))")
            params.extend((bytes(race["race_hash"]), race["race_key"]))
        return self.rows("conditions:target_entries", "SELECT e.race_key,CONVERT(varchar(10),r.race_date,23) race_date,"
            "r.venue_code,r.retrospective_metadata_json metadata,e.horse_no,e.horse_id,e.rank,e.abnormal_code,"
            "e.retrospective_se_json attrs FROM history.entries e JOIN (VALUES " + ",".join(values) + ") k(h,race_key) "
            "ON e.__unified_race_sha256=k.h AND e.race_key=k.race_key JOIN history.races r "
            "ON r.__migration_source_snapshot_id=31 AND r.__unified_race_sha256=e.__unified_race_sha256 AND r.race_key=e.race_key "
            "WHERE e.__migration_source_snapshot_id=31 ORDER BY r.race_date,e.horse_no", params, 1000)

    def horse_history(self, horse_ids: list[str], through: str) -> list[dict]:
        """対象馬だけの保存済み履歴を一括取得し、全履歴の無制限exportを避ける。"""
        require(0 < len(horse_ids) <= 1000, "conditions_history_id_limit")
        values = ",".join("(CONVERT(nvarchar(10),?))" for _ in horse_ids)
        return self.rows("conditions:horse_history", "SELECT e.race_key,CONVERT(varchar(10),r.race_date,23) race_date,"
            "r.venue_code,r.retrospective_metadata_json metadata,e.horse_no,e.horse_id,e.rank,e.abnormal_code,"
            "e.retrospective_se_json attrs FROM history.entries e JOIN (VALUES " + values + ") h(horse_id) "
            "ON CONVERT(nvarchar(10),e.horse_id)=h.horse_id JOIN history.races r "
            "ON r.__migration_source_snapshot_id=31 AND r.__unified_race_sha256=e.__unified_race_sha256 "
            "AND CONVERT(nvarchar(12),r.race_key)=CONVERT(nvarchar(12),e.race_key) "
            "WHERE e.__migration_source_snapshot_id=31 AND r.race_date<? "
            "ORDER BY e.horse_id,r.race_date,e.race_key OPTION (HASH JOIN)", (*horse_ids, through),
            self.settings["limits"]["max_history_rows"])

    def race_conditions(self, keys: set[str]) -> tuple[dict, dict]:
        """必要競走のRAだけを年別固定版から読み、SHAと最新同順位競合を検査する。"""
        by_year = defaultdict(list)
        for key in sorted(keys):
            by_year[int(key[:4])].append(key)
        selected, total, sources, scanned_metadata = {}, 0, [], 0
        indexes = self._small("conditions:RA_indexes", "SELECT i.name,c.name column_name,ic.key_ordinal "
            "FROM sys.indexes i JOIN sys.index_columns ic ON i.object_id=ic.object_id AND i.index_id=ic.index_id "
            "JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id "
            "WHERE i.object_id=OBJECT_ID('raw.year_raw_records') AND i.is_unique=1 AND ic.key_ordinal>0 "
            "AND i.is_disabled=0 ORDER BY i.index_id,ic.key_ordinal")
        routes = defaultdict(list)
        for index in indexes:
            routes[index["name"]].append(index["column_name"])
        require(["__migration_source_snapshot_id", "__migration_source_rowid"] in routes.values(), "conditions_RA_index_route")
        for year, race_keys in sorted(by_year.items()):
            require(2003 <= year <= 2026, "conditions_raw_year")
            source = self._small("conditions:raw_source", "SELECT d.source_key,s.status FROM ops.source_snapshot s "
                "JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (year-1999,))
            require(source == [{"source_key": f"jv-results-{year}", "status": "verified"}], "conditions_raw_source")
            sources.append({"year": year, "snapshot": year-1999})
            # LOB競走キーの複数比較は避け、年partitionの小さなRA索引台帳だけを読む。
            catalog = self.rows("conditions:RA_catalog", "SELECT TOP (10001) __migration_source_rowid rowid,"
                "CONVERT(nvarchar(12),race_key) race_key,LEN(race_key) key_length FROM raw.year_raw_records "
                "WHERE __migration_source_snapshot_id=? AND record_type=N'RA' AND is_valid=1 ORDER BY __migration_source_rowid",
                (year-1999,), 10000)
            scanned_metadata += len(catalog)
            require(scanned_metadata <= self.settings["limits"]["max_ra_metadata_rows"], "conditions_RA_catalog_limit")
            require(all(row["key_length"] == 12 for row in catalog), "conditions_RA_catalog_key_length")
            wanted = {row["rowid"]: row["race_key"] for row in catalog if row["race_key"] in set(race_keys)}
            rowids = sorted(wanted)
            for start in range(0, len(rowids), 500):
                chunk = rowids[start:start+500]
                raw_rows = self.rows("conditions:RA", "SELECT y.__migration_source_rowid rowid,"
                    "CONVERT(nvarchar(12),y.race_key) race_key,y.is_valid,CONVERT(nvarchar(64),y.sha256) sha256,"
                    "CONVERT(varbinary(1272),y.payload) payload,DATALENGTH(y.payload) payload_length "
                    "FROM raw.year_raw_records y JOIN (VALUES "
                    + ",".join("(CONVERT(bigint,?))" for _ in chunk)
                    + ") k(rowid) ON y.__migration_source_rowid=k.rowid "
                    "WHERE y.__migration_source_snapshot_id=?", (*chunk, year-1999), self.settings["limits"]["max_raw_rows"])
                total += len(raw_rows)
                require(total <= self.settings["limits"]["max_raw_rows"], "conditions_raw_total_limit")
                for row in raw_rows:
                    if not row["is_valid"]:
                        continue
                    key, raw = row["race_key"], bytes(row["payload"])
                    require(row["rowid"] in wanted and key == wanted[row["rowid"]] and row["payload_length"] == 1272,
                            "conditions_RA_full_key_mismatch")
                    parsed = parse_ra(raw, row["sha256"], key)
                    version = (raw[3:11], raw[2:3])
                    before = selected.get(key)
                    require(not before or before[0] != version or before[1] == row["sha256"], "conditions_RA_version_conflict")
                    if before is None or version > before[0]:
                        selected[key] = (version, row["sha256"], parsed)
        return {k: value[2] for k, value in selected.items()}, {
            "queried_records": total, "catalog_rows": scanned_metadata, "needed_races": len(keys), "verified_races": len(selected),
            "missing_keys": sorted(keys - set(selected)), "sources": sources,
            "selected_sha256": {k: v[1] for k, v in sorted(selected.items())}}


def export_dataset(reader: ConditionsReader, config: dict, card: dict | None = None) -> dict:
    """対象馬の解析済みデータだけを構成し、履歴境界・原文整合・欠損を記録する。"""
    preflight = reader.preflight()
    targets = reader.target_races()
    target_rows = [normalize_row(r) for r in reader.target_entries(targets)]
    ids = {r["horse_id"] for r in target_rows if r["status"] == "active"}
    through = f"{config['last_year']+1}-01-01"
    if card is not None:
        validate_card(card, config)
        ids.update(r["horse_id"] for r in card["runners"] if r["status"] == "active")
        through = max(through, card["race_date"])
    history = [normalize_row(r) for r in reader.horse_history(sorted(ids), through)]
    require(all(h["horse_id"] in ids for h in history), "conditions_history_full_id_mismatch")
    require(len({(h["race_key"], h["horse_id"]) for h in history}) == len(history), "conditions_history_duplicates")
    conditions, ra_audit = reader.race_conditions({r["race_key"] for r in target_rows + history})
    for row in target_rows + history:
        attrs = conditions.get(row["race_key"])
        row["ra_verified"] = attrs is not None
        if attrs:
            require(row["distance"] == int(attrs["distance_raw"]) and row["track_code"] == attrs["track_code"],
                    "conditions_RA_metadata_mismatch")
            row.update({name: attrs[name] for name in ("grade", "weight_rule", "symbol")})
    grouped = defaultdict(list)
    for row in target_rows:
        grouped[row["race_key"]].append(row)
    races = []
    for target in targets:
        metadata = json.loads(target["metadata"])
        race = {"race_key": target["race_key"], "race_date": target["race_date"], "race_name": config["race_name"],
                "venue_code": target["venue_code"], "distance": int(metadata["distance_raw"]), "track_code": metadata["track_code"],
                "conditions": conditions.get(target["race_key"], {}), "runners": grouped[target["race_key"]]}
        validate_race(race)
        races.append(race)
    dataset = {"schema_version": 1, "race_name": config["race_name"], "races": races, "history": history,
               "provenance": {**preflight, "exported_at_utc": datetime.now(timezone.utc).isoformat(),
                              "retrospective": True, "history_before": through, "raw_audit": ra_audit,
                              "source_ra_digests": digest(ra_audit["selected_sha256"])}}
    dataset["input_sha256"] = digest(dataset)
    dataset["coverage"] = {"race_count": len(races), "target_rows": len(target_rows), "history_rows": len(history),
        "venue_counts": {venue: sum(r["venue_code"] == venue for r in races) for venue in ("08", "09")},
        "ra_verified": ra_audit["verified_races"], "ra_missing": len(ra_audit["missing_keys"]),
        "notes": ["属性と実出走集合は事後版。発走前可用性の完全証明ではない。", "前走はDB内直近確認走。海外・地方等の履歴不足がある。"]}
    # coverageを含む入力全体を再計算し、offline検算の境界を固定する。
    dataset["input_sha256"] = digest({k: v for k, v in dataset.items() if k != "input_sha256"})
    return dataset
