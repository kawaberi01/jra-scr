from __future__ import annotations

from .models import RaceOdds


MIN_EXPECTED_RETURN = 1.05
MIN_MARKET_EDGE = 0.03
MIN_WIN_ODDS = 2.0
NEWCOMER_MAX_MARKET_RANK = 3
HISTORY_WIN_EV_POLICY_VERSION = "history_win_ev_revalidation_v1"


def build_win_betting_decision(
    race_name: str | None,
    history_ranking: list[dict],
    materials_ranking: list[dict],
    odds_summary: RaceOdds,
    *,
    budget: int = 1000,
) -> dict:
    if is_newcomer_race(race_name):
        return build_newcomer_win_decision(materials_ranking, odds_summary, budget=budget)
    return build_win_ev_decision(history_ranking, odds_summary, budget=budget)


def build_newcomer_win_decision(
    materials_ranking: list[dict],
    odds_summary: RaceOdds,
    *,
    budget: int = 1000,
) -> dict:
    """新馬戦は公開指数と市場支持の一致だけで単勝候補を判定する。"""
    odds_by_horse = _win_odds(odds_summary)
    if not odds_by_horse:
        return _newcomer_no_bet("unavailable", "単勝オッズ未取得のため新馬戦の買い目を判定できません")

    market_rank = {
        horse_no: rank
        for rank, (horse_no, _) in enumerate(
            sorted(odds_by_horse.items(), key=lambda item: (item[1], _horse_number(item[0]))),
            1,
        )
    }
    candidates = []
    for public_rank, item in enumerate(materials_ranking, 1):
        horse_no = str(item.get("horse_no") or "")
        odds = odds_by_horse.get(horse_no)
        rank = market_rank.get(horse_no)
        eligible = public_rank == 1 and rank is not None and rank <= NEWCOMER_MAX_MARKET_RANK
        candidates.append(
            {
                "horse_no": horse_no,
                "horse_name": item.get("horse_name"),
                "public_rank": public_rank,
                "market_rank": rank,
                "win_odds": odds,
                "eligible": eligible,
            }
        )

    selection = next((candidate for candidate in candidates if candidate["eligible"]), None)
    if selection is None:
        return {
            **_newcomer_no_bet("no_bet", "公開材料1位と単勝支持上位の一致馬がいません"),
            "candidates": candidates,
        }

    amount = (budget // 100) * 100
    if amount < 100:
        return _newcomer_no_bet("no_bet", "予算が100円未満です")
    return {
        "status": "recommended",
        "strategy": "newcomer_public_market_consensus",
        "reason": "新馬戦は公開材料1位と単勝支持上位の一致で判定しました",
        "thresholds": {"max_market_rank": NEWCOMER_MAX_MARKET_RANK},
        "selection": selection,
        "tickets": [
            {
                "bet_type": "win",
                "selection": selection["horse_no"],
                "amount": amount,
                "reason": "公開材料1位かつ単勝支持上位",
            }
        ],
        "candidates": candidates,
    }


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
    selected = max(eligible, key=lambda item: (item["expected_return"], item["market_edge"])) if eligible else None
    return {
        "status": "shadow_only",
        "strategy": "history_win_ev",
        "ticket_status": "shadow_only",
        "policy_version": HISTORY_WIN_EV_POLICY_VERSION,
        "reason": "未校正・購入非推奨: 通常戦の単勝EV候補は再検証完了までシャドー評価のみです",
        "market_overround": round(market_total, 6),
        "thresholds": {
            "min_expected_return": MIN_EXPECTED_RETURN,
            "min_market_edge": MIN_MARKET_EDGE,
            "min_win_odds": MIN_WIN_ODDS,
        },
        "selection": selected,
        "tickets": [],
        "candidates": sorted(candidates, key=lambda item: item["expected_return"], reverse=True),
    }


def _no_bet(status: str, reason: str) -> dict:
    return {
        "status": status,
        "strategy": "history_win_ev",
        "ticket_status": "shadow_only",
        "policy_version": HISTORY_WIN_EV_POLICY_VERSION,
        "reason": reason,
        "tickets": [],
        "candidates": [],
        "thresholds": {
            "min_expected_return": MIN_EXPECTED_RETURN,
            "min_market_edge": MIN_MARKET_EDGE,
            "min_win_odds": MIN_WIN_ODDS,
        },
    }


def _newcomer_no_bet(status: str, reason: str) -> dict:
    return {
        "status": status,
        "strategy": "newcomer_public_market_consensus",
        "reason": reason,
        "tickets": [],
        "candidates": [],
        "thresholds": {"max_market_rank": NEWCOMER_MAX_MARKET_RANK},
    }


def is_newcomer_race(race_name: str | None) -> bool:
    return "新馬" in (race_name or "") or "メイクデビュー" in (race_name or "")


def _horse_number(horse_no: str) -> int:
    try:
        return int(horse_no)
    except ValueError:
        return 999


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
