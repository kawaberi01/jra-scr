import asyncio
from datetime import date
from pathlib import Path

from jra_srb.provider import HttpProvider
from jra_srb.service import JraService


async def main() -> None:
    service = JraService(
        provider=HttpProvider(timeout=20, retries=1, max_concurrency=1, min_interval_seconds=0.2)
    )
    page = await service._load_result_race_page(date(2025, 1, 5), "nakayama", 11)
    path = Path("data/jradb_accessS_race_202501050611_live.html")
    path.write_text(page.content, encoding="utf-8")
    print(f"wrote={path}|len={len(page.content)}|source={page.source}")


if __name__ == "__main__":
    asyncio.run(main())
