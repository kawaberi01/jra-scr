"""概要: win市場とwide市場の不一致を旧定義どおり純計算する。
作成日: 2026-10-16
入力: 版固定済みSQL readerから受け取ったrace単位のwin/wide価格と明示払戻。
出力: cross-ratio候補、threshold別選択、払戻集計のreport辞書。
実行例: evaluate_candidates(rows, payouts)
注意事項: DB/HTTP/ファイルI/Oを行わず、availabilityや時点適合性を判定しない。
"""

from __future__ import annotations

from datetime import date
import math
from typing import Any

from .jra_research_contracts import ResearchError, finite


MIN_WIDE_ODDS = 3.0
MAX_WIDE_ODDS = 20.0
VALUE_THRESHOLDS = tuple(round(1.1 + index * 0.1, 1) for index in range(10))
INFORMATION_THRESHOLDS = tuple(round(0.9 - index * 0.05, 2) for index in range(10))


def _race_identity(race_id: Any, race_date: Any) -> tuple[str, str]:
    """race IDの文字列同一性とISO開催日を検査して返す。"""
    if not isinstance(race_id, str) or not race_id or not isinstance(race_date, str):
        raise ResearchError("invalid_cross_market_race")
    try:
        parsed = date.fromisoformat(race_date)
    except ValueError:
        raise ResearchError("invalid_cross_market_race_date") from None
    if parsed.isoformat() != race_date:
        raise ResearchError("invalid_cross_market_race_date")
    return race_id, race_date


def _pair(value: Any) -> tuple[str, str]:
    """二頭の正規化可能な馬番を検査し、旧実装と同じ数値昇順へ揃える。"""
    if (not isinstance(value, tuple) or len(value) != 2
            or any(not isinstance(item, str) or not item.isascii() or not item.isdigit() for item in value)):
        raise ResearchError("invalid_cross_market_pair")
    pair = tuple(sorted(value, key=int))
    if int(pair[0]) == int(pair[1]):
        raise ResearchError("invalid_cross_market_pair")
    return pair


def _price_map(values: Any, *, pairs: bool) -> dict:
    """horse/pair価格を検査し、非有限・非正値・正規化重複を拒否する。"""
    if not isinstance(values, dict):
        raise ResearchError("invalid_cross_market_prices")
    result = {}
    for key, raw_price in values.items():
        if pairs:
            normalized = _pair(key)
        else:
            if not isinstance(key, str) or not key:
                raise ResearchError("invalid_cross_market_horse")
            normalized = key
        price = finite(raw_price)
        if price <= 0:
            raise ResearchError("invalid_cross_market_price")
        if not math.isfinite(1.0 / price):
            raise ResearchError("nonfinite_value")
        if normalized in result:
            raise ResearchError("duplicate_key")
        result[normalized] = price
    return result


def build_race_candidates(
    race_id: str,
    race_date: str,
    win_prices: dict[str, float],
    wide_prices: dict[tuple[str, str], float],
) -> list[dict[str, Any]]:
    """旧win/wide比率定義で一race内の全wide pair候補を作る。

    Args:
        race_id: 元値を保つrace識別子。
        race_date: YYYY-MM-DD形式の開催日。
        win_prices: 馬番文字列から単勝価格への対応。
        wide_prices: 馬番pairからwide価格への対応。

    Returns:
        `race_id`, `race_date`, `pair`, `price`, `cross_ratio`を持つ候補列。

    Raises:
        ResearchError: 不正価格、pair、race識別子、非有限の計算結果。
    """
    race_id, race_date = _race_identity(race_id, race_date)
    wins = _price_map(win_prices, pairs=False)
    wides = _price_map(wide_prices, pairs=True)
    if len(wides) != len(wide_prices):
        raise ResearchError("duplicate_key")

    win_inverse = {horse: 1.0 / odds for horse, odds in wins.items()}
    win_total = sum(win_inverse.values())
    wide_inverse = {pair: 1.0 / price for pair, price in wides.items()}
    wide_total = sum(wide_inverse.values())
    if not math.isfinite(win_total) or not math.isfinite(wide_total):
        raise ResearchError("nonfinite_value")
    expected_raw = {
        pair: (win_inverse.get(pair[0], 0.0) / win_total if win_total else 0.0)
        * (win_inverse.get(pair[1], 0.0) / win_total if win_total else 0.0)
        for pair in wides
    }
    expected_total = sum(expected_raw.values())
    if not expected_total or not wide_total:
        return []
    candidates = []
    for pair, price in wides.items():
        expected_share = expected_raw[pair] / expected_total
        observed_share = wide_inverse[pair] / wide_total
        ratio = expected_share / observed_share
        if not all(math.isfinite(value) for value in (expected_share, observed_share, ratio)):
            raise ResearchError("nonfinite_value")
        candidates.append({"race_id": race_id, "race_date": race_date, "pair": pair,
                           "price": price, "cross_ratio": ratio})
    return candidates


def _candidate(row: Any) -> dict[str, Any]:
    """候補辞書の必要列と数値範囲を検査し、既知列だけを返す。"""
    if not isinstance(row, dict) or not {"race_id", "race_date", "pair", "price", "cross_ratio"}.issubset(row):
        raise ResearchError("invalid_cross_market_candidate")
    race_id, race_date = _race_identity(row["race_id"], row["race_date"])
    pair = _pair(row["pair"])
    price, ratio = finite(row["price"]), finite(row["cross_ratio"])
    if price <= 0 or ratio < 0:
        raise ResearchError("invalid_cross_market_candidate")
    return {"race_id": race_id, "race_date": race_date, "pair": pair,
            "price": price, "cross_ratio": ratio}


def select_candidates(rows: list[dict], direction: str, threshold: float) -> list[dict]:
    """旧threshold政策でwide価格範囲内からraceごとに一候補を選ぶ。"""
    if not isinstance(direction, str) or direction not in {"value", "information"}:
        raise ResearchError("invalid_cross_market_direction")
    threshold = finite(threshold)
    by_race: dict[str, list[dict]] = {}
    seen = set()
    for raw in rows:
        row = _candidate(raw)
        key = row["race_id"], row["pair"]
        if key in seen:
            raise ResearchError("duplicate_key")
        seen.add(key)
        if MIN_WIDE_ODDS <= row["price"] <= MAX_WIDE_ODDS:
            by_race.setdefault(row["race_id"], []).append(row)
    selected = []
    for candidates in by_race.values():
        if direction == "value":
            row = max(candidates, key=lambda item: item["cross_ratio"])
            if row["cross_ratio"] >= threshold:
                selected.append(row)
        else:
            row = min(candidates, key=lambda item: item["cross_ratio"])
            if row["cross_ratio"] <= threshold:
                selected.append(row)
    return selected


def summarize_candidates(rows: list[dict], payouts: dict[tuple[str, tuple[str, str]], int]) -> dict[str, Any]:
    """明示払戻だけで旧100円ticket集計を再現し、払戻欠損を停止する。"""
    if not isinstance(payouts, dict):
        raise ResearchError("invalid_cross_market_payouts")
    normalized_payouts = {}
    for key, raw_payout in payouts.items():
        if not isinstance(key, tuple) or len(key) != 2 or not isinstance(key[0], str) or not key[0]:
            raise ResearchError("invalid_cross_market_payout_key")
        payout_key = key[0], _pair(key[1])
        if payout_key in normalized_payouts or type(raw_payout) is not int or raw_payout < 0:
            raise ResearchError("invalid_cross_market_payout")
        normalized_payouts[payout_key] = raw_payout
    settled = []
    seen = set()
    for raw in rows:
        row = _candidate(raw)
        key = row["race_id"], row["pair"]
        if key in seen:
            raise ResearchError("duplicate_key")
        seen.add(key)
        if key not in normalized_payouts:
            raise ResearchError("settlement_unknown", 4, race_id=row["race_id"])
        settled.append(normalized_payouts[key])
    ordered = sorted(settled)
    bet = len(settled) * 100
    return {
        "tickets": len(settled),
        "hits": sum(value > 0 for value in ordered),
        "return_rate": round(sum(ordered) / bet, 4) if bet else 0.0,
        "no_max_return_rate": round(sum(ordered[:-1]) / (bet - 100), 4) if len(settled) > 1 else 0.0,
        "no_top3_return_rate": round(sum(ordered[:-3]) / (bet - 300), 4) if len(settled) > 3 else 0.0,
        "max_payout": max(ordered, default=0),
    }


def evaluate_candidates(rows: list[dict], payouts: dict[tuple[str, tuple[str, str]], int]) -> dict[str, Any]:
    """20 threshold・旧3期間の選択と払戻reportをメモリ内で生成する。"""
    normalized_rows = [_candidate(row) for row in rows]
    keys = [(row["race_id"], row["pair"]) for row in normalized_rows]
    if len(keys) != len(set(keys)):
        raise ResearchError("duplicate_key")
    periods = {
        "development_2025h1": [row for row in normalized_rows if row["race_date"] <= "2025-06-30"],
        "external_2025q3": [row for row in normalized_rows if "2025-07-01" <= row["race_date"] <= "2025-09-30"],
        "external_2025q4": [row for row in normalized_rows if row["race_date"] >= "2025-10-01"],
    }
    configs = [("value", value) for value in VALUE_THRESHOLDS] + [
        ("information", value) for value in INFORMATION_THRESHOLDS
    ]
    candidates = []
    for direction, threshold in configs:
        metrics = {
            period: summarize_candidates(select_candidates(period_rows, direction, threshold), payouts)
            for period, period_rows in periods.items()
        }
        passed = all(
            item["tickets"] >= 100
            and item["return_rate"] >= 1.0
            and item["no_max_return_rate"] >= 1.0
            and item["no_top3_return_rate"] >= 1.0
            for item in metrics.values()
        )
        candidates.append({"name": f"cross_{direction}_{threshold:.2f}", "direction": direction,
                           "threshold": threshold, "metrics": metrics, "pass": passed})
    return {
        "theory": "win-wide-cross-pool-disagreement-v1",
        "definition": "expected wide pool share from normalized win shares divided by observed wide pool share",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "eligible": [item["name"] for item in candidates if item["pass"]],
    }
