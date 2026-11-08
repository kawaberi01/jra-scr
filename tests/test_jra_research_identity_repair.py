"""概要: 登録identity補修planと承認前の更新境界をfake接続で検証する。
作成日: 2026-10-16
入力: 合成map/JV参照行と、SQLを記録するfake DB-API接続。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_research_identity_repair.py
注意事項: 実SQL/実DBは使用せず、applyは明示承認付きfake接続だけで検証する。
"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json

import pytest

from jra_srb.jra_history_dataset import COURSE_CODES
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_identity_repair import (
    OLD_EVIDENCE_RULE, TARGET_COUNT, apply_repair_plan, build_repair_plan,
    validate_reference_evidence,
)


def _fixtures(count: int = TARGET_COUNT):
    """一意な登録mapとJV参照の合成行を作成する。"""
    codes = sorted(COURSE_CODES)
    maps, refs = [], []
    first_day = date(2025, 1, 1)
    for index in range(count):
        day = first_day + timedelta(days=index // (len(codes) * 12))
        venue = codes[(index // 12) % len(codes)]
        race_no = index % 12 + 1
        full = f"{day:%Y%m%d}{venue}{index % 10000:04d}{race_no:02d}"
        api_id = f"api-native-{index:05d}"
        source_sha = hashlib.sha256(f"map-{index}".encode()).hexdigest()
        evidence = {
            "source_relation": "live.races", "original_id": api_id,
            "stored_full_id": full, "stored_date": day.isoformat(),
            "stored_venue": f"走路説明-{venue}", "stored_race_no": race_no,
            "rule": OLD_EVIDENCE_RULE,
        }
        maps.append({
            "map_id": index + 1, "source_snapshot_id": 34, "source_relation": "live.races",
            "source_original_id": api_id, "api_race_id": api_id,
            "jv_race_key_full_16": full, "race_date": day.isoformat(), "venue_code": None,
            "race_no": race_no, "unified_race_id": f"legacy:JRA:{full}", "mapping_status": "unresolved",
            "evidence_json": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            "source_row_sha256": source_sha,
        })
        refs.append({
            "source_snapshot_id": 31, "source_relation": "history.races", "source_rowid": index + 10001,
            "selected_sha256": hashlib.sha256(f"reference-{index}".encode()).hexdigest(),
            "race_key_full": full, "race_date": day.isoformat(), "venue_code": venue, "race_no": race_no,
        })
    return maps, refs


class _FakeCursor:
    """指定SQLマーカーへfake結果を返し、更新件数を模擬する。"""
    def __init__(self, connection):
        """合成SQL検証用の接続状態と応答を初期化する。"""
        self.connection = connection
        self.rows = []
        self.one = None
        self.rowcount = -1
        self.closed = False

    def execute(self, sql, params=()):
        """SQLを分類してfake結果または指定障害を設定する。"""
        mode = self.connection.mode
        self.rows, self.one, self.rowcount = [], None, -1
        self.connection.sql_log.append((sql, tuple(params)))
        if sql == "SET NOCOUNT ON; SET XACT_ABORT ON":
            self.connection.begun = True
        elif sql == "SELECT @@TRANCOUNT":
            self.one = (2 if mode == "nested_transaction" else 1,)
        elif "SELECT DB_NAME()" in sql:
            self.one = ("wrong_db" if mode == "wrong_db" else "jra_unified",)
        elif "HAS_PERMS_BY_NAME" in sql:
            self.one = (0, 1, 1) if mode == "role_denied" else (1, 1, 1)
        elif "ops.source_snapshot" in sql:
            self.rows = [(31, "verified", "prediction-full-20261008"),
                         (34, "unverified" if mode == "source_unverified" else "verified", "analysis-current")]
        elif "repair:locked_map" in sql:
            self.rows = [dict(row) for row in self.connection.maps]
            if mode == "map_changed":
                self.rows[0]["source_row_sha256"] = "f" * 64
            if mode == "sha_representation_flip":
                for index, row in enumerate(self.rows):
                    if index % 2 == 0 and isinstance(row["source_row_sha256"], str):
                        row["source_row_sha256"] = bytes.fromhex(row["source_row_sha256"])
                    elif index % 2 == 1 and isinstance(row["source_row_sha256"], bytes):
                        row["source_row_sha256"] = row["source_row_sha256"].hex()
        elif "repair:identity_conflicts" in sql:
            split = (len(params) - 2) // 2
            assert "source_snapshot_id=? AND source_relation=?" in sql
            assert params[:2] == (34, "live.races")
            fulls, unified = set(params[2:2 + split]), set(params[2 + split:])
            self.rows = [(row["map_id"], row["jv_race_key_full_16"], row["unified_race_id"])
                         for row in self.connection.maps
                         if row["jv_race_key_full_16"] in fulls or row["unified_race_id"] in unified]
            if mode == "other_scope_collision":
                # 同一full16を別snapshot/relationで使う登録はこのscopeの競合ではない。
                self.connection.other_scope_collision_seen = True
        elif "repair:locked_reference" in sql:
            assert "race_key_full" in sql and "selected_sha256" in sql and "race_key race_key_full" not in sql
            ids = set(params[1:])
            self.rows = [dict(source_rowid=row["source_rowid"], race_key_full=row["race_key_full"],
                              race_date=row["race_date"], venue_code=row["venue_code"], race_no=row["race_no"],
                              selected_sha256=row["selected_sha256"])
                         for row in self.connection.references if row["source_rowid"] in ids]
            if mode == "reference_changed" and self.rows:
                self.rows[0]["race_no"] = 12 if self.rows[0]["race_no"] != 12 else 11
            if mode == "reference_sha_changed" and self.rows:
                self.rows[0]["selected_sha256"] = "f" * 64
        elif sql.startswith("UPDATE history.race_identity_map"):
            assert "CONVERT(varbinary(max),CONVERT(nvarchar(max),source_relation))" in sql
            assert "CONVERT(varbinary(max),CONVERT(nvarchar(max),?))" in sql
            assert "SELECT @@ROWCOUNT" in sql
            self.connection.update_calls += 1
            self.connection.update_params.append(params)
            self.rowcount = 0 if mode == "update_count" and self.connection.update_calls == 1 else 1
            self.one = (self.rowcount,)
        else:
            raise AssertionError(f"unexpected SQL: {sql[:100]}")
        return self

    def fetchone(self):
        """fake単一結果を返す。"""
        return self.one

    def fetchall(self):
        """fake複数結果を返す。"""
        return self.rows

    def close(self):
        """cursor終了を記録する。"""
        self.closed = True


class _FakeConnection:
    """transactionと限定SELECT/UPDATEだけを模擬する。"""
    def __init__(self, maps, refs, mode="ok", autocommit=False):
        """合成SQL検証用の接続状態と応答を初期化する。"""
        self.maps, self.references, self.mode = maps, refs, mode
        self.autocommit = autocommit
        self.begun = self.committed = self.rolled_back = False
        self.update_calls = 0
        self.update_params = []
        self.sql_log = []
        self.other_scope_collision_seen = False

    def cursor(self):
        """fake cursorを返す。"""
        return _FakeCursor(self)

    def rollback(self):
        """rollback発生を記録する。"""
        self.rolled_back = True

    def commit(self):
        """DB-API transaction commitを記録する。"""
        self.committed = True


def test_plan_validation_evidence_and_fake_apply_success():
    """3455件のexact plan/v2 evidenceを作り、承認付きfake applyを通す。"""
    maps, refs = _fixtures()
    maps[1]["source_row_sha256"] = bytes.fromhex(maps[1]["source_row_sha256"])
    plan = build_repair_plan(maps, refs)
    assert plan.count == TARGET_COUNT
    assert plan.summary["count"] == TARGET_COUNT
    assert "api-native" not in repr(plan)
    item = plan._items[0]
    mapping = dict(maps[0])
    mapping.update(venue_code=item.new_venue_code, unified_race_id=item.new_unified_race_id,
                   mapping_status="verified", evidence_json=item.new_evidence_json)
    validate_reference_evidence(mapping)
    connection = _FakeConnection(maps, refs, mode="sha_representation_flip")
    result = apply_repair_plan(connection, plan, approved=True, metadata_verified=True)
    assert result["status"] == "applied" and result["updated_count"] == TARGET_COUNT
    assert connection.begun and connection.committed and not connection.rolled_back
    assert all(sql.count("'") % 2 == 0 for sql, _ in connection.sql_log)
    assert any("HAS_PERMS_BY_NAME(N'ops.source_snapshot',N'OBJECT',N'SELECT')" in sql for sql, _ in connection.sql_log)
    assert connection.update_calls == TARGET_COUNT
    assert any(sql == "SET NOCOUNT ON; SET XACT_ABORT ON" for sql, _ in connection.sql_log)
    assert not any("BEGIN TRANSACTION" in sql for sql, _ in connection.sql_log)
    assert any("TOP (9000)" in sql for sql, _ in connection.sql_log if "repair:locked_map" in sql)
    assert connection.other_scope_collision_seen is False
    assert any(any(isinstance(value, bytes) and len(value) == 32 for value in params)
               for params in connection.update_params)


@pytest.mark.parametrize("mode", ["role_denied", "source_unverified", "map_changed", "reference_changed", "reference_sha_changed", "update_count", "wrong_db", "nested_transaction"])
def test_plan_boundaries_and_failed_apply_rollback(mode):
    """計画違反とtransaction内競合を拒否し、DB接続をrollbackする。"""
    maps, refs = _fixtures()
    plan = build_repair_plan(maps, refs)
    connection = _FakeConnection(maps, refs, mode=mode)
    with pytest.raises(ResearchError):
        apply_repair_plan(connection, plan, approved=True, metadata_verified=True)
    assert connection.begun and connection.rolled_back and not connection.committed
    with pytest.raises(ResearchError, match="identity_repair_approval_required"):
        apply_repair_plan(_FakeConnection(maps, refs), plan)
    with pytest.raises(ResearchError):
        build_repair_plan(maps[:-1], refs)
    duplicate = list(refs)
    duplicate[-1] = dict(duplicate[0])
    with pytest.raises(ResearchError):
        build_repair_plan(maps, duplicate)


def test_plan_rejects_tampered_update_and_accepts_other_scope_collision():
    """plan改変は拒否し、別snapshot/relationの同一IDは競合にしない。"""
    from dataclasses import replace

    maps, refs = _fixtures()
    plan = build_repair_plan(maps, refs)
    altered_item = replace(plan._items[0], new_unified_race_id="JRA:tampered")
    altered = replace(plan, _items=(altered_item, *plan._items[1:]))
    with pytest.raises(ResearchError, match="identity_repair_plan_integrity_failed"):
        apply_repair_plan(_FakeConnection(maps, refs), altered, approved=True, metadata_verified=True)
    connection = _FakeConnection(maps, refs, mode="other_scope_collision")
    result = apply_repair_plan(connection, plan, approved=True, metadata_verified=True)
    assert result["updated_count"] == TARGET_COUNT and connection.committed
