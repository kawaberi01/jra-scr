"""概要: モデルの馬連予想から検証用の仮想買い目と予算配分を作る。
作成日: 2026-10-25
入力: 選択モデル、馬連確率順位、取得済み実オッズ、任意の仮想予算（円）。
出力: 実購入と分離した研究プランの辞書。ファイル出力なし。
実行例: scripts/jra_selected_model.py predictから利用する。
注意事項: 外部通信・実購入なし。配分規則は未検証であり利益優位を表さない。
"""

import math


POLICY_ID = "research-quinella-top3-532-v1"


def pair_key(horses):
    """馬番2頭を検証し、順不同のゼロ埋めタプルへ正規化する。"""
    values = [int(str(h)) for h in horses]
    if len(values) != 2 or len(set(values)) != 2 or any(not 1 <= h <= 18 for h in values):
        raise ValueError("馬連は異なる馬番2頭が必要です")
    return tuple(f"{h:02d}" for h in sorted(values))


def allocate_tickets(candidates, budget):
    """確率順位の重み5:3:2を100円単位の最大剰余法で配分する。

    Args:
        candidates: 取得済み実オッズを持つ確率上位の最大3組。
        budget: 100円以上、100円単位の仮想予算。
    Returns:
        正の配分額を持つ仮想買い目。少額予算では配分0円の組を除く。
    Raises:
        ValueError: 予算が不正、候補が空または4点以上の場合。
    """
    if type(budget) is not int or budget < 100 or budget % 100 or not 1 <= len(candidates) <= 3:
        raise ValueError("仮想予算は100円以上の100円単位、候補は1～3点が必要です")
    weights = [5, 3, 2][:len(candidates)]
    units = budget // 100
    total = sum(weights)
    amounts = [units * weight // total for weight in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(units * weights[i] % total), i))
    for index in order[:units - sum(amounts)]:
        amounts[index] += 1
    return [{**row, "amount": amount * 100} for row, amount in zip(candidates, amounts) if amount]


def build_research_plan(model, forecast, snapshot, budget=0):
    """研究利用可の馬連モデルで、事前に固定する仮想プランを作る。

    Args:
        model: 研究利用可否と対応確率を持つ選択モデル。
        forecast: 馬連確率順位。着順順位から馬連確率を推測しない。
        snapshot: 発走前の公式カードと実オッズ。
        budget: 0は未指定として仮想1000円。指定時は100円単位。
    Returns:
        仮想予算・買い目・予算別例・規則IDと取得時点。不足時も理由を返す。
    Notes:
        購入承認の有無は研究予想を止める理由にしない。上位候補の実オッズが
        不足した場合は別の組へ差し替えず、金額配分だけを止める。
    """
    selected_budget = 1000 if budget == 0 else budget
    if type(selected_budget) is not int or selected_budget < 100 or selected_budget % 100:
        raise ValueError("仮想予算は100円以上の100円単位で指定してください")
    plan = {"policy_id": POLICY_ID, "status": "unavailable", "virtual_only": True,
            "virtual_budget_yen": selected_budget, "total_stake_yen": 0,
            "observed_at": snapshot["odds"].get("fetched_at"), "tickets": [], "budget_plans": [],
            "reason": "馬連確率が未対応のため、印と評価順位を検証対象にします"}
    if not model.get("research_allowed") or "quinella" not in model.get("probabilities", []):
        return plan
    try:
        active = {str(row["horse_no"]).zfill(2) for row in snapshot["card"]["runners"] if row["status"] == "active"}
        pairs = []
        seen = set()
        for row in forecast.get("pair_ranking", []):
            horses = pair_key(row["horses"])
            probability = float(row["probability"])
            if (horses in seen or not set(horses) <= active or
                    not math.isfinite(probability) or not 0 < probability <= 1):
                raise ValueError("馬連確率または出走馬集合が不正です")
            seen.add(horses)
            pairs.append((horses, probability))
        pairs.sort(key=lambda row: (-row[1], row[0]))
        if not pairs:
            raise ValueError("馬連確率順位が未取得です")
        prices = {}
        for row in snapshot["odds"].get("odds", {}).get("quinella", []):
            horses = pair_key(row["combination"])
            if horses in prices:
                raise ValueError("馬連オッズに重複があります")
            price = float(row["odds"])
            if not math.isfinite(price) or price < 1:
                raise ValueError("馬連実オッズが不正です")
            prices[horses] = price
        candidates = []
        for rank, (horses, probability) in enumerate(pairs[:3], 1):
            if horses not in prices:
                raise ValueError("検証対象の馬連上位候補の実オッズが未取得です")
            candidates.append({"bet_type": "quinella", "selection": list(horses),
                               "probability": probability, "odds": prices[horses],
                               "reason": f"選択モデルの馬連確率{rank}位・検証用"})
        plan.update(status="available", reason="確率上位最大3点・順位重み5:3:2の未検証仮想配分",
                    tickets=allocate_tickets(candidates, selected_budget), total_stake_yen=selected_budget,
                    budget_plans=[{"budget_yen": amount, "tickets": allocate_tickets(candidates, amount)}
                                  for amount in sorted({1000, 2000, 3000, selected_budget})])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        plan["reason"] = str(error)
    return plan
