import asyncio

from jra_srb.provider import HttpProvider
from jra_srb.service import JraService


async def main() -> None:
    service = JraService(provider=HttpProvider())
    card = await service.get_race_card("202606280301")
    for runner in card.runners:
        print(
            {
                "horse_no": runner.horse_no,
                "horse_name": runner.horse_name,
                "sex_age": runner.sex_age,
                "weight_carried": runner.weight_carried,
                "jockey": runner.jockey,
                "trainer": runner.trainer,
            }
        )


if __name__ == "__main__":
    asyncio.run(main())
