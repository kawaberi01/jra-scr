from __future__ import annotations

from datetime import UTC, datetime
import logging

from .cache import TTLCache
from .errors import BadRequestError
from .models import NetkeibaRaceResult, RaceOdds
from .netkeiba_extractors import parse_netkeiba_odds_payload, parse_netkeiba_race_result
from .netkeiba_provider import BaseNetkeibaProvider, NetkeibaHttpProvider

logger = logging.getLogger(__name__)


SUPPORTED_NETKEIBA_BET_TYPES = {
    "win",
    "place",
    "bracket_quinella",
    "quinella",
    "wide",
    "exacta",
    "trio",
    "trifecta",
}

UNORDERED_NETKEIBA_BET_TYPES = {
    "bracket_quinella",
    "quinella",
    "wide",
    "trio",
}


class NetkeibaService:
    def __init__(self, provider: BaseNetkeibaProvider | None = None, cache: TTLCache | None = None) -> None:
        self.provider = provider or NetkeibaHttpProvider()
        self.cache = cache or TTLCache()

    async def get_race_result(self, race_id: str) -> NetkeibaRaceResult:
        logger.info("get_netkeiba_race_result", extra={"race_id": race_id})
        cache_key = f"netkeiba:result:{race_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})
        page = await self.provider.fetch_race_result(race_id)
        parsed = parse_netkeiba_race_result(page.content)
        result = NetkeibaRaceResult(
            race_id=race_id,
            fetched_at=datetime.now(UTC),
            source=page.source,
            **parsed,
        )
        self.cache.set(cache_key, result, ttl_seconds=3600)
        return result

    async def get_race_odds(
        self,
        race_id: str,
        bet_type: str | None = None,
        combination: list[str] | None = None,
        refresh: bool = False,
    ) -> RaceOdds:
        logger.info(
            "get_netkeiba_race_odds",
            extra={"race_id": race_id, "bet_type": bet_type, "combination": combination},
        )
        if bet_type is not None and bet_type not in SUPPORTED_NETKEIBA_BET_TYPES:
            raise BadRequestError(f"unsupported netkeiba bet_type={bet_type}")
        cache_key = f"netkeiba:odds:{race_id}"
        cached = self.cache.get(cache_key)
        if cached is not None and not refresh:
            return self._filter_odds(cached, bet_type, combination, cache_hit=True)
        await self.provider.fetch_odds_view(race_id)
        page = await self.provider.fetch_odds_api(race_id)
        odds = parse_netkeiba_odds_payload(page.content)
        result = RaceOdds(
            race_id=race_id,
            odds=odds,
            fetched_at=datetime.now(UTC),
            source=page.source,
        )
        self.cache.set(cache_key, result, ttl_seconds=300)
        return self._filter_odds(result, bet_type, combination)

    @staticmethod
    def _filter_odds(
        odds: RaceOdds,
        bet_type: str | None,
        combination: list[str] | None,
        cache_hit: bool = False,
    ) -> RaceOdds:
        if bet_type is None:
            return odds.model_copy(update={"cache_hit": cache_hit})
        entries = odds.odds.get(bet_type, [])
        if combination:
            ordered = bet_type not in UNORDERED_NETKEIBA_BET_TYPES
            normalized = NetkeibaService._normalize_combination(combination, ordered=ordered)
            entries = [
                entry
                for entry in entries
                if NetkeibaService._normalize_combination(entry.combination, ordered=ordered) == normalized
            ]
        return odds.model_copy(
            update={
                "bet_type": bet_type,
                "entries": entries,
                "odds": {},
                "cache_hit": cache_hit,
            }
        )

    @staticmethod
    def _normalize_combination(combination: list[str], ordered: bool) -> list[str]:
        normalized = []
        for item in combination:
            value = item.strip()
            normalized.append(str(int(value)) if value.isdigit() else value)
        if ordered:
            return normalized
        return sorted(normalized, key=lambda item: (0, int(item)) if item.isdigit() else (1, item))
