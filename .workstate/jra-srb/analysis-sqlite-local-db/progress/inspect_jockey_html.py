import asyncio

from bs4 import BeautifulSoup

from jra_srb.provider import HttpProvider


async def main() -> None:
    provider = HttpProvider()
    page = await provider.fetch_race_card("202606280301")
    soup = BeautifulSoup(page.content, "html.parser")
    for row in soup.select("table.basic.narrow-xy.mt20 tbody tr"):
        horse_name = row.select_one("td.horse .name a")
        jockey_cell = row.select_one("td.jockey")
        if horse_name is None or jockey_cell is None:
            continue
        name = horse_name.get_text(" ", strip=True)
        if name in {"ブランフォルテ", "ラパンラピッド", "ヴォンヌヴォー"}:
            print("horse=", name)
            print("text=", jockey_cell.get_text(" ", strip=True))
            print("html=", jockey_cell.decode_contents())
            print("---")


if __name__ == "__main__":
    asyncio.run(main())
