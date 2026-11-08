"""概要: SQL内の最新開催・結果束・研究生成範囲と不足を再検証する。
作成日: 2026-10-15
入力: 研究reader、対象開始日。
出力: 保存済みレースを母集団とした不足一覧と採用版。
実行例: uv run python scripts/run_jra_research.py readiness --config configs/research/cross_pool_sql_masked_v2.json --since 2026-09-27
注意事項: SQL読取りのみ。レース行の存在を結果や特徴量の充足と同一視しない。
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from .jra_research_contracts import ResearchError


def audit_readiness(reader, since: str) -> dict:
    """既存runtimeの結果束と固定研究版の範囲を限定SELECTで確認する。"""
    try:
        if date.fromisoformat(since).isoformat() != since:
            raise ValueError("date")
    except (ValueError, TypeError):
        raise ResearchError("invalid_since_date", 2) from None
    rows = reader._small("runtime_readiness", """
        SELECT r.race_id,r.race_date,r.course,r.race_no,
               CASE WHEN rr.race_id IS NULL THEN 0 ELSE 1 END has_result,
               (SELECT COUNT_BIG(*) FROM api_runtime.result_entries e WHERE e.__hash_race_id=r.__hash_race_id AND e.race_id=r.race_id) result_entries,
               (SELECT COUNT_BIG(*) FROM api_runtime.payouts p WHERE p.__hash_race_id=r.__hash_race_id AND p.race_id=r.race_id) payout_rows
        FROM api_runtime.races r
        LEFT JOIN api_runtime.race_results rr ON rr.__hash_race_id=r.__hash_race_id AND rr.race_id=r.race_id
        WHERE r.race_date>=? ORDER BY r.race_date,r.course,r.race_no
    """, (since,))
    fixed = [row for row in reader.keyset("history.races", maximum=100000) if row["race_date"] >= since]
    grouped = Counter((r["race_date"], r["course"]) for r in rows)
    missing = [r for r in rows if not r["has_result"] or not r["result_entries"] or not r["payout_rows"]]
    sources = reader._small("adopted_versions", """
        SELECT d.source_key,c.source_snapshot_id,s.status
        FROM ops.current_source_snapshot c JOIN ops.source_database d ON d.source_database_id=c.source_database_id
        JOIN ops.source_snapshot s ON s.source_snapshot_id=c.source_snapshot_id ORDER BY d.source_key
    """)
    return {"coverage_basis": "stored_races", "independent_meeting_coverage_verified": False,
            "since": since, "runtime_races": len(rows), "runtime_complete_result_bundles": len(rows) - len(missing),
            "runtime_missing_result_bundles": missing,
            "by_date_course": [{"race_date": day, "course": course, "stored_races": count,
                                "complete_results": sum(r["race_date"] == day and r["course"] == course and r not in missing for r in rows)}
                               for (day, course), count in sorted(grouped.items())],
            "fixed_research_recent_races": len(fixed),
            "fixed_research_statuses": dict(Counter(r["status"] for r in fixed)),
            "fixed_research_feature_eligibility": dict(Counter(r["feature_eligibility"] for r in fixed)),
            "source_versions": sources, "data_complete": not missing}
