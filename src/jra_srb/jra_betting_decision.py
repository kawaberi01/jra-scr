from __future__ import annotations

from .models import RaceOdds


MIN_EXPECTED_RETURN = 1.05
MIN_MARKET_EDGE = 0.03
MIN_WIN_ODDS = 2.0


def build_win_ev_decision(
    history_ranking: list[dict],
    odds_summary: RaceOdds,
    *,
    budget: int = 1000,
) -> dict:
    odds_by_horse = _win_odds(odds_summary)
    if not odds_by_horse:
        return _no_bet("unavailable", "単勝オッズ未取得のため期待値を判定できません")
    market_raw = {horse_no: 1 / odds for horse_no, odds in odds_by_horse.items() if odds > 0}
    market_total = sum(market_raw.values())
    candidates = []
    for item in history_ranking:
        horse_no = str(item.get("horse_no") or "")
        odds = odds_by_horse.get(horse_no)
        probability = float(item.get("win_probability_race_normalized") or 0.0)
        if odds is None or market_total <= 0:
            continue
        market_probability = market_raw[horse_no] / market_total
        expected_return = probability * odds
        market_edge = probability - market_probability
        eligible = (
            odds >= MIN_WIN_ODDS
            and expected_return >= MIN_EXPECTED_RETURN
            and market_edge >= MIN_MARKET_EDGE
        )
        candidates.append(
            {
                "horse_no": horse_no,
                "horse_name": item.get("horse_name"),
                "model_probability": round(probability, 6),
                "market_probability": round(market_probability, 6),
                "market_edge": round(market_edge, 6),
                "win_odds": odds,
                "expected_return": round(expected_return, 6),
                "eligible": eligible,
            }
        )
    eligible = [candidate for candidate in candidates if candidate["eligible"]]
    if not eligible:
        return {
            **_no_bet("no_bet", "単勝期待値の条件を満たす馬がいません"),
            "market_overround": round(market_total, 6),
            "candidates": sorted(candidates, key=lambda item: item["expected_return"], reverse=True),
        }
    selected = max(eligible, key=lambda item: (item["expected_return"], item["market_edge"]))
    amount = (budget // 100) * 100
    if amount < 100:
        return _no_bet("no_bet", "予算が100円未満です")
    return {
        "status": "recommended",
        "reason": "単勝期待値と市場確率差の条件を満たしました",
        "market_overround": round(market_total, 6),
        "thresholds": {
            "min_expected_return": MIN_EXPECTED_RETURN,
            "min_market_edge": MIN_MARKET_EDGE,
            "min_win_odds": MIN_WIN_ODDS,
        },
        "selection": selected,
        "tickets": [
            {
                "bet_type": "win",
                "selection": selected["horse_no"],
                "amount": amount,
                "reason": f"期待回収倍率 {selected['expected_return']:.3f}",
            }
        ],
        "candidates": sorted(candidates, key=lambda item: item["expected_return"], reverse=True),
    }


def _no_bet(status: str, reason: str) -> dict:
    return {
        "status": status,
        "reason": reason,
        "tickets": [],
        "candidates": [],
        "thresholds": {
            "min_expected_return": MIN_EXPECTED_RETURN,
            "min_market_edge": MIN_MARKET_EDGE,
            "min_win_odds": MIN_WIN_ODDS,
        },
    }


def _win_odds(odds_summary: RaceOdds) -> dict[str, float]:
    entries = odds_summary.odds.get("win", []) or (
        odds_summary.entries if odds_summary.bet_type == "win" else []
    )
    result = {}
    for entry in entries:
        if not entry.combination or entry.odds is None:
            continue
        try:
            result[str(entry.combination[0])] = float(entry.odds)
        except ValueError:
            continue
    return result
