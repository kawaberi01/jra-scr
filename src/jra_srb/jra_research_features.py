"""概要: SQLの時点市場とマスク済み特徴量を検証し、予測専用入力を作る。
作成日: 2026-10-15
入力: 同じ固定版のレース、出走、時点市場、特徴量の行。
出力: 結果を含まないInputRace。
実行例: uv run pytest -q tests/test_jra_research_features.py
注意事項: 意図NULLを補完せず、欠損・時点不整合はレース単位で除外する。
"""

from __future__ import annotations

import json
import math

from .jra_research_contracts import (
    EXPECTED_FEATURE_NAMES, FEATURE_NAMES, MASKED_NAMES, InputRace, ResearchError, digest, finite, horse_number, timestamp,
)


def unique_rows(rows: list[dict], key: str) -> dict:
    """業務キーを重複検査して辞書へ変換する。"""
    result = {}
    for row in rows:
        identifier = horse_number(row[key]) if key == "horse_no" else row[key]
        if identifier in result:
            raise ResearchError("duplicate_key")
        result[identifier] = row
    return result


def numeric_market(row: dict, market: str) -> dict:
    """解析版O1/O2の数値オッズだけを整数10倍単位から抽出する。"""
    try:
        entries = json.loads(row["entries_json"])
    except (TypeError, ValueError):
        raise ResearchError("invalid_market_json") from None
    if not isinstance(entries, list):
        raise ResearchError("invalid_market_json")
    result = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ResearchError("invalid_market_json")
        if item.get("market") != market or item.get("odds_status_low") != "numeric":
            continue
        raw = item.get("selection_key")
        if market == "win":
            key = horse_number(raw)
        else:
            if not isinstance(raw, str) or len(raw) != 4:
                raise ResearchError("invalid_pair")
            key = tuple(sorted((horse_number(raw[:2]), horse_number(raw[2:]))))
            if key[0] == key[1]:
                raise ResearchError("invalid_pair")
        odds = finite(item.get("odds_low_x10")) / 10
        if odds < 1:
            raise ResearchError("invalid_odds")
        if key in result:
            raise ResearchError("duplicate_key")
        result[key] = odds
    return result


def build_input(race: dict, feature_rows: list[dict], entry_rows: list[dict], market_rows: list[dict],
                *, snapshot: int, horizon: str) -> InputRace:
    """ロスター・時刻・mask・市場数式を検査し、予測入力だけを生成する。

    Args:
        race: 対象レースの識別情報。statusなどの結果状態を入力へ持ち込まない。
        feature_rows: 同じ時点・版の1頭1行の生成済み特徴量。
        entry_rows: 同じ版のロスターと馬ID。
        market_rows: 同じ時点・版の単勝と馬連選択行。
        snapshot: 具体的に固定した採用版番号。
        horizon: T30またはT10。

    Returns:
        結果・払戻を含まない不変のInputRace。

    Raises:
        ResearchError: 欠損、重複、時点、特徴量定義や数値の不整合。
    """
    if not feature_rows:
        raise ResearchError("missing_features")
    if not entry_rows:
        raise ResearchError("missing_card")
    features, entries = unique_rows(feature_rows, "horse_no"), unique_rows(entry_rows, "horse_no")
    markets = unique_rows([r for r in market_rows if r["market"] in {"win", "quinella"}], "market")
    if set(markets) != {"win", "quinella"}:
        raise ResearchError("missing_O1" if "win" not in markets else "missing_O2")
    for market in markets.values():
        if market["selection_status"] != "selected":
            reason = "not_sold" if "not_sold" in market["selection_status"] else "version_conflict"
            raise ResearchError(reason)
        if market["parser_version"] != "jv-o1o2-v2" or market["horizon"] != horizon:
            raise ResearchError("unexpected_parser_or_horizon")
        if not market["content_sha256"]:
            raise ResearchError("missing_source_hash")
        if timestamp(market["announced_at"]) > timestamp(market["cutoff_at"]):
            raise ResearchError("after_cutoff")
    win, pair = numeric_market(markets["win"], "win"), numeric_market(markets["quinella"], "quinella")
    horses = tuple(sorted(win))
    if len(horses) < 5 or set(horses) != set(features) or set(horses) != set(entries):
        raise ResearchError("roster_mismatch")
    if any(not entries[key]["horse_id"] for key in horses):
        raise ResearchError("unresolved_id")
    pair = {key: value for key, value in pair.items() if set(key).issubset(horses)}
    if len(pair) != len(horses) * (len(horses) - 1) // 2:
        raise ResearchError("missing_O2_pairs")
    win_total, pair_total = sum(1 / value for value in win.values()), sum(1 / value for value in pair.values())
    marginal = {key: 0.0 for key in horses}
    for (left, right), price in pair.items():
        marginal[left] += 1 / price / (2 * pair_total)
        marginal[right] += 1 / price / (2 * pair_total)
    cutoff = timestamp(markets["win"]["cutoff_at"])
    if timestamp(markets["quinella"]["cutoff_at"]) != cutoff:
        raise ResearchError("cutoff_mismatch")
    values, evidence = [], []
    for key in horses:
        feature = features[key]
        if feature["feature_status"] != "research_only_final_SE_identity_mapping_unverified":
            raise ResearchError("unexpected_feature_quality")
        if feature["horizon"] != horizon or timestamp(feature["market_cutoff_at"]) != cutoff:
            raise ResearchError("cutoff_mismatch")
        for prefix, market in (("o1", "win"), ("o2", "quinella")):
            if feature["source_" + prefix + "_sha256"] != markets[market]["content_sha256"]:
                raise ResearchError("source_hash_mismatch")
            if timestamp(feature[prefix + "_announced_at"]) != timestamp(markets[market]["announced_at"]):
                raise ResearchError("announcement_mismatch")
        try:
            data, mask = json.loads(feature["features_json"]), json.loads(feature["masked_feature_names_json"])
        except (TypeError, ValueError):
            raise ResearchError("invalid_feature_json") from None
        if (not isinstance(data, dict) or set(data) != EXPECTED_FEATURE_NAMES or not isinstance(mask, list)
                or len(mask) != 23 or any(not isinstance(name, str) for name in mask) or frozenset(mask) != MASKED_NAMES):
            raise ResearchError("unexpected_mask")
        if any(data.get(name) is not None for name in MASKED_NAMES):
            raise ResearchError("unexpected_mask")
        for name, number in data.items():
            if name not in MASKED_NAMES:
                finite(number)
        row = tuple(finite(data.get(name)) for name in FEATURE_NAMES)
        expected = (math.log(win[key]), (1 / win[key]) / win_total,
                    math.log(marginal[key] / ((1 / win[key]) / win_total)))
        if any(not math.isclose(actual, target, rel_tol=1e-7, abs_tol=1e-7)
               for actual, target in zip((row[0], row[1], row[-1]), expected, strict=True)):
            raise ResearchError("market_feature_mismatch")
        values.append(row)
        evidence.append(digest({"feature": feature, "entry": entries[key]}))
    evidence.extend(digest(markets[market]) for market in ("win", "quinella"))
    return InputRace(race["race_key"], race["race_date"], race["venue_code"], horizon, cutoff.isoformat(),
                     horses, tuple(win[key] for key in horses), tuple(values), snapshot, tuple(evidence))
