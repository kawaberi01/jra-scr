import asyncio
from datetime import date

from jra_srb.provider import HttpProvider


async def main() -> None:
    provider = HttpProvider(timeout=10, retries=0, max_concurrency=1, min_interval_seconds=0.05)
    target = date(2025, 1, 5)
    course_code = "06"
    kai = "20250101"
    race_no = 11
    for status in ("0", "1"):
        prefix = f"pw01dde{status}{course_code}{kai}{race_no:02d}{target:%Y%m%d}"
        for value in range(256):
            cname = f"{prefix}/{value:02X}"
            try:
                page = await provider.fetch_jradb("/JRADB/accessD.html", cname)
            except Exception:
                continue
            if "race_header" in page.content and "basic narrow-xy" in page.content:
                print(f"found={cname}|source={page.source}|len={len(page.content)}")
                return
    print("not_found")


if __name__ == "__main__":
    asyncio.run(main())
