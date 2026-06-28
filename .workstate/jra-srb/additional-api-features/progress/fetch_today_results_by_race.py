from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from jra_srb.provider import HttpProvider
from jra_srb.service import JraService


async def main() -> None:
    target = date(2026, 6, 28)
    courses = ["fukushima", "kokura", "hakodate"]
    service = JraService(provider=HttpProvider(min_interval_seconds=0.2))
    records = []
    for course in courses:
        meeting = await service.get_meeting(target, course)
        for race in meeting.races:
            record = {
                "date": target.isoformat(),
                "course": course,
                "race_no": race.race_no,
                "race_id": race.race_id,
                "race_name": race.race_name,
                "start_time": race.start_time,
                "status": "pending",
                "result": None,
                "error": None,
            }
            try:
                result = await service.get_race_result_by_number(target, course, race.race_no)
            except Exception as exc:
                record["status"] = "failed"
                record["error"] = f"{type(exc).__name__}: {exc}"
            else:
                record["status"] = "succeeded"
                record["result"] = result.model_dump(mode="json")
            records.append(record)

    output = Path("data/live-2026-06-28-results-by-race.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    succeeded = sum(1 for item in records if item["status"] == "succeeded")
    failed = sum(1 for item in records if item["status"] == "failed")
    output.write_text(
        json.dumps(
            {
                "date": target.isoformat(),
                "total": len(records),
                "succeeded": succeeded,
                "failed": failed,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "total": len(records), "succeeded": succeeded, "failed": failed}, ensure_ascii=False))
    for item in records:
        if item["status"] == "failed":
            print(f"FAILED {item['course']} {item['race_no']}R {item['race_id']} {item['error']}")


if __name__ == "__main__":
    asyncio.run(main())
