from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from jra_srb.service import JraService


async def main() -> None:
    target = date(2026, 6, 28)
    service = JraService()
    races = await service.get_races(target)
    payload = [race.model_dump(mode="json") for race in races]
    output = Path("data/live-2026-06-28-races.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "date": target.isoformat(),
                "total": len(payload),
                "courses": sorted({item["course"] for item in payload if item.get("course")}),
                "races": payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "date": target.isoformat(),
                "total": len(payload),
                "courses": sorted({item["course"] for item in payload if item.get("course")}),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    for race in payload[:20]:
        print(
            f"{race.get('course')} {race.get('race_number')} "
            f"{race.get('race_id')} {race.get('name')} {race.get('start_time')}"
        )


if __name__ == "__main__":
    asyncio.run(main())
