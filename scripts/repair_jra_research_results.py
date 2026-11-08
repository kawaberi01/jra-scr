"""概要: SQLで不足を検証したJRA結果だけを既存保存APIで補充する。
作成日: 2026-10-15
入力: 研究設定、対象開始日、最大件数、明示--apply。
出力: artifacts/jra_research/runs内の不足一覧・投入件数・事後照合。
実行例: uv run python scripts/repair_jra_research_results.py --config configs/research/cross_pool_sql_masked_v2.json --since 2026-10-12 --limit 24 --apply
注意事項: --apply時に既存APIが公式providerへ通信してSQLへ保存する。APIコード・設定・旧DBは変更しない。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jra_srb.jra_research_artifacts import RunArtifacts
from jra_srb.jra_research_contracts import ResearchConfig, ResearchError
from jra_srb.jra_research_reader import ResearchReader
from jra_srb.jra_research_readiness import audit_readiness


def verify_saved(reader: ResearchReader, race_id: str) -> dict:
    """公式出典・結果・払戻・受領履歴の存在をSQLから再確認する。"""
    hash_value = hashlib.sha256(race_id.encode("utf-16le")).digest()
    records = reader._small("verify_repaired_result", """
        SELECT rr.race_id,rr.source,
               (SELECT COUNT_BIG(*) FROM api_runtime.result_entries e WHERE e.__hash_race_id=rr.__hash_race_id AND e.race_id=rr.race_id) entries,
               (SELECT COUNT_BIG(*) FROM api_runtime.payouts p WHERE p.__hash_race_id=rr.__hash_race_id AND p.race_id=rr.race_id) payouts
        FROM api_runtime.race_results rr WHERE rr.__hash_race_id=? AND rr.race_id=?
    """, (hash_value, race_id))
    if len(records) != 1 or not records[0]["entries"] or not records[0]["payouts"]:
        raise ResearchError("saved_result_incomplete", 4, race_id=race_id)
    if urlparse(records[0]["source"]).hostname not in {"www.jra.go.jp", "jra.go.jp"}:
        raise ResearchError("nonofficial_result_source", 4, race_id=race_id)
    receipts = reader._small("verify_result_receipt", """
        SELECT TOP(1) request_sha256,received_at_utc FROM api_runtime.write_receipts
        WHERE race_sha256=? AND race_id=? AND operation='race_result'
        ORDER BY received_at_utc DESC,request_sha256 DESC
    """, (hash_value, race_id))
    if not receipts:
        raise ResearchError("missing_result_receipt", 4, race_id=race_id)
    return {"race_id": race_id, "entries": records[0]["entries"], "payouts": records[0]["payouts"],
            "official_source": True, "receipt_sha256": receipts[0]["request_sha256"]}


async def discover_meetings(since: str) -> list:
    """公式の結果/払戻/開催一覧fallbackで対象期間の開催を独立に取得する。"""
    from jra_srb.service import JraService
    service = JraService()
    start, end = date.fromisoformat(since), date.today()
    if start > end or (end - start).days > 31:
        raise ResearchError("discovery_date_range_limit", 2)
    found = []
    day = start
    while day <= end:
        meetings = await service.get_meetings_for_date(day)
        for meeting in meetings:
            if urlparse(meeting.source).hostname not in {"www.jra.go.jp", "jra.go.jp"}:
                raise ResearchError("nonofficial_meeting_source", 4, race_date=str(day))
            found.append((day, meeting))
        day += timedelta(days=1)
    return found


def repair(config: ResearchConfig, since: str, limit: int, *, apply: bool, discover: bool = False) -> dict:
    """不足分だけを直列投入し、失敗時は後続要求を止める。"""
    if not 1 <= limit <= 120:
        raise ResearchError("invalid_repair_limit", 2)
    artifacts = RunArtifacts(config.raw, "repair-results")
    repaired = []
    try:
        with ResearchReader(config) as reader:
            artifacts.write_json("preflight.json", reader.preflight())
            before = audit_readiness(reader, since)
            artifacts.write_json("coverage.json", before)
            if discover:
                meetings = asyncio.run(discover_meetings(since))
                known = {row["race_id"] for row in reader._small("known_races_for_discovery", "SELECT race_id FROM api_runtime.races WHERE race_date>=?", (since,))}
                missing_headers = [(day, meeting, race) for day, meeting in meetings for race in meeting.races if race.race_id not in known]
                artifacts.manifest["discovery"] = {"since": since, "through": str(date.today()),
                    "expected_races": sum(len(meeting.races) for _, meeting in meetings), "missing_headers": len(missing_headers),
                    "meetings": [{"date": str(day), "course": meeting.course, "races": len(meeting.races)} for day, meeting in meetings]}
                if apply and missing_headers:
                    from jra_srb.storage import build_analysis_store
                    from jra_srb.storage_config import storage_backend
                    if storage_backend() != "sqlserver":
                        raise ResearchError("repair_requires_sql_writer", 3)
                    store = build_analysis_store()
                    for day, meeting, race in missing_headers:
                        store.write_race(day, str(meeting.course), race, source=meeting.source, fetched_at=meeting.fetched_at)
                    before = audit_readiness(reader, since)
                    artifacts.write_json("coverage.json", before)
            selected = before["runtime_missing_result_bundles"][:limit]
            if not apply:
                artifacts.finish(planned=len(selected), writes=0)
                return {"run_id": artifacts.run_id, "planned": len(selected), "writes": 0}
            with httpx.Client(base_url="http://127.0.0.1:8000", timeout=45) as client:
                response = client.get("/health")
                if response.status_code != 200 or response.json() != {"status": "ok"}:
                    raise ResearchError("api_not_ready", 3)
                for item in selected:
                    if item["course"] not in {"sapporo", "hakodate", "fukushima", "niigata", "tokyo", "nakayama", "chukyo", "kyoto", "hanshin", "kokura"} or not 1 <= item["race_no"] <= 12:
                        raise ResearchError("invalid_repair_target", 2)
                    path = f"/jra/meetings/{item['race_date']}/{item['course']}/races/{item['race_no']}/result/save"
                    response = client.post(path)
                    if response.status_code != 200:
                        raise ResearchError("result_collection_failed", 4, race_id=item["race_id"], http_status=response.status_code)
                    body = response.json()
                    if body.get("race_id") != item["race_id"]:
                        raise ResearchError("result_identity_mismatch", 4, race_id=item["race_id"])
                    repaired.append(verify_saved(reader, item["race_id"]))
                    artifacts.write_json("metrics.json", {"repaired": repaired, "requested": len(selected)})
            after = audit_readiness(reader, since)
            artifacts.write_json("metrics.json", {"repaired": repaired, "before_missing": len(before["runtime_missing_result_bundles"]),
                                                  "after_missing": len(after["runtime_missing_result_bundles"]), "by_date_course": after["by_date_course"]})
            artifacts.finish(repaired=len(repaired), remaining=len(after["runtime_missing_result_bundles"]))
            return {"status": "passed", "run_id": artifacts.run_id, "repaired": len(repaired), "remaining": len(after["runtime_missing_result_bundles"])}
    except ResearchError as error:
        artifacts.fail(error)
        error.details["run_id"] = artifacts.run_id
        raise
    except Exception as error:
        safe = ResearchError("repair_execution_failed", 1, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None


def main() -> int:
    """明示投入フラグと上限を解析して非秘密のJSON結果を返す。"""
    parser = argparse.ArgumentParser(description="不足JRA結果を既存SQL保存APIへ補充")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--since", required=True)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--discover", action="store_true", help="最大31日を公式開催一覧と独立照合し、欠落レース行も既存SQL writerで補充")
    args = parser.parse_args()
    try:
        print(json.dumps(repair(ResearchConfig.load(args.config), args.since, args.limit, apply=args.apply, discover=args.discover), ensure_ascii=True))
        return 0
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=True))
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
