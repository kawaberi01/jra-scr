from __future__ import annotations

from datetime import UTC, datetime

from .models import JraPredictionBundle


THEORY_VERSION = "jra-public-live-v1"


def build_prediction_record(bundle: JraPredictionBundle, budget: int = 1000) -> dict:
    """公開材料だけで再現可能な、控えめな順位・ワイド案を作る。"""
    omega = {}
    for runner in bundle.public_analysis.sources["keibalab"].runners:
        if runner.omega_index is not None:
            omega[runner.horse_no] = runner.omega_index
    best = {item.horse_no: item.rank for item in bundle.best_time_lite.runners if item.rank}
    closing = {item.horse_no: item.rank for item in bundle.closing_speed_lite.runners if item.rank}
    win_odds = _win_odds(bundle)
    scored = []
    for runner in bundle.card.runners:
        no = runner.horse_no or ""
        odds = win_odds.get(no) or _float(runner.odds)
        score = 0.0
        reasons = []
        if no in omega:
            score += omega[no]
            reasons.append(f"公開Ω指数 {omega[no]:g}")
        if odds and odds > 0:
            score += 30 / odds
            reasons.append(f"単勝 {odds:g}倍")
        if no in best:
            score += max(0, 8 - best[no])
            reasons.append(f"近走時計順位 {best[no]}")
        if no in closing:
            score += max(0, 6 - closing[no])
            reasons.append(f"近走上がり順位 {closing[no]}")
        scored.append({
            "horse_no": no,
            "horse_name": runner.horse_name,
            "score": round(score, 3),
            "win_odds": odds,
            "reasons": reasons or ["公開材料が少ないため出馬表のみ"],
        })
    ranking = sorted(scored, key=lambda item: (-item["score"], _horse_no(item["horse_no"])))
    top = ranking[:3]
    tickets = []
    if len(top) >= 3:
        amount = max(100, budget // 2 // 100 * 100)
        for index, other in enumerate(top[1:3], start=1):
            tickets.append({
                "ticket_id": f"{bundle.race_id}-wide-{index}",
                "bucket": "main" if index == 1 else "cover",
                "bet_type": "wide",
                "selection": f"{top[0]['horse_no']}-{other['horse_no']}",
                "selection_json": [top[0]["horse_no"], other["horse_no"]],
                "amount": amount if index == 1 else budget - amount,
                "reason": "公開指数・単勝支持・近走時計の総合上位",
            })
    created_at = datetime.now(UTC).isoformat()
    return {
        "prediction_id": f"jra-{bundle.race_id}-{created_at.replace(':', '').replace('+', '-')}",
        "race_id": bundle.race_id,
        "theory_version": THEORY_VERSION,
        "mode": "integrated_betting",
        "budget": budget,
        "created_at": created_at,
        "race_context": {
            "race_id": bundle.race_id,
            "race_date": bundle.date.isoformat(),
            "course": bundle.course,
            "race_no": bundle.race_no,
            "race_name": bundle.card.race_name,
        },
        "pre_race_snapshot": bundle.model_dump(mode="json"),
        "prediction_json": {
            "predicted_ranking": ranking,
            "predicted_top3": top,
            "axis_horse_numbers": [top[0]["horse_no"]] if top else [],
            "data_status": bundle.meta.component_status,
            "generated_before_result": True,
        },
        "prediction_tickets": tickets,
    }


def _win_odds(bundle: JraPredictionBundle) -> dict[str, float]:
    entries = bundle.odds_summary.odds.get("win", []) or (
        bundle.odds_summary.entries if bundle.odds_summary.bet_type == "win" else []
    )
    return {
        entry.combination[0]: value
        for entry in entries
        if entry.combination and (value := _float(entry.odds)) is not None
    }


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _horse_no(value: str) -> int:
    return int(value) if value.isdigit() else 999
