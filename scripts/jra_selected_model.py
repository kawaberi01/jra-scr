"""概要: 共通設定のJRAモデルで個別予想・当日候補抽出・表示保存を実行する。
作成日: 2026-10-25
入力: モデル指定（省略可）、公式入力フォルダーまたは日付/場/R、共通SQL設定。
出力: 排他的な新規出力先へ予想・表示本文・保存読戻し・全日分析状態。
実行例: uv run --extra ml python scripts/jra_selected_model.py resolve
注意事項: ローカルAPI準備はスキルのensure_api.ps1を先に実行。--save時にSQL書込。
    live入力準備は既存SQL履歴処理を再利用する。再学習・実購入・結果取得なし。
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import math
from types import SimpleNamespace
from uuid import uuid4

import httpx

from jra_srb.jra_model_selection import DEFAULT_CONFIG, ROOT, read_json, resolve_model, sha256
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_plan import build_research_plan


def write_json(path, value):
    """JSONを排他的に作成し、過去の証跡を保持する。"""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def post_time(day, text):
    """JRAの時刻表記を日本時間の発走日時へ変換する。欠測は拒否する。"""
    match = re.fullmatch(r"(\d{1,2})(?:時|:)(\d{2})(?:分)?", text or "")
    if not match:
        raise ValueError("発走時刻が不明です")
    return datetime.fromisoformat(f"{day}T{int(match[1]):02d}:{match[2]}:00+09:00")


def api_get(client, path, **params):
    """ローカルAPIを再試行せず取得し、HTTP失敗を伝える。"""
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def acquire_snapshot(client, day, course, race_no, model, folder):
    """既存の公式束取得と履歴特徴準備を使い、新しい入力を作る。

    Notes:
        既存のprepare_jra_condition_inputが履歴・同定・日付境界を確認する。
        保存済み早朝入力を最新入力へ改名しない。取得失敗時は代替しない。
    """
    folder.mkdir(parents=True, exist_ok=False)
    meeting = api_get(client, f"/meetings/{day}/{course}")
    race = next(r for r in meeting["races"] if r["race_no"] == race_no)
    if datetime.now(timezone.utc) >= post_time(day, race["start_time"]):
        raise ValueError("発走済みのため事前予想を作成できません")
    coordinates = {"meeting_no": meeting["meeting_no"], "meeting_day": meeting["meeting_day"]}
    base = f"/jra/meetings/{day}/{course}/races/{race_no}"
    # 束のrefreshは外部分析/価格に適用されるため、カードは既存serviceのrefreshも明示する。
    fresh_card = api_get(client, f"/meetings/{day}/{course}/races/{race_no}/card", refresh="true")
    if model["adapter"] in {"attribute_chimera", "j23_frozen"}:
        # 必須入力だけを既存APIから取得し、未使用の外部分析取得の遅延に依存させない。
        bundle = {"card": fresh_card, "odds_summary": api_get(client, base + "/odds-summary",
                   bet_types="win,quinella", refresh="true")}
    else:
        bundle = api_get(client, base + "/prediction-bundle", **coordinates,
                         bet_types="win,quinella", refresh="true")
    if bundle["card"]["runners"] != fresh_card["runners"]:
        raise ValueError("取得中に公式出走馬情報が変化しました。入力を再準備してください")
    write_json(folder / ("official-inputs.json" if model["adapter"] in {"attribute_chimera", "j23_frozen"} else "prediction-bundle.json"), bundle)
    write_json(folder / "official-card.json", bundle["card"])
    write_json(folder / "official-odds.json", bundle["odds_summary"])
    if model["adapter"] in {"attribute_chimera", "j23_frozen"}:
        from prepare_jra_condition_input import prepare
        prepare(SimpleNamespace(training_run=ROOT / model["history_checkpoint_run"],
                                card=folder / "official-card.json", date=day, course=course,
                                race_no=race_no, output=folder / "input"))
        # 履歴準備に時間がかかった場合も、取消・条件・入力特徴の変化を検知してから価格を観測する。
        final_card = api_get(client, f"/meetings/{day}/{course}/races/{race_no}/card", refresh="true")
        fields = ("horse_no", "horse_name", "status", "sex_age", "frame_no", "weight_carried", "official_recent_races")
        previous = [{k: r.get(k) for k in fields} for r in bundle["card"]["runners"]]
        current = [{k: r.get(k) for k in fields} for r in final_card["runners"]]
        if (previous != current or any(bundle["card"].get(k) != final_card.get(k)
                                       for k in ("race_id", "surface", "distance", "start_time"))):
            raise ValueError("履歴準備中に出走馬または競走条件が変化しました。新入力で再準備が必要です")
        final_odds = api_get(client, base + "/odds-summary", bet_types="win,quinella", refresh="true")
        ready = folder / "ready"
        (ready / "input").mkdir(parents=True, exist_ok=False)
        write_json(ready / "official-card.json", final_card)
        write_json(ready / "official-odds.json", final_odds)
        write_json(ready / "input/input.json", read_json(folder / "input/input.json"))
        j23_features = folder / "input/j23_public_features.json"
        if j23_features.is_file():
            write_json(ready / "input/j23_public_features.json", read_json(j23_features))
        elif model["adapter"] == "j23_frozen":
            raise ValueError("J23用の12特徴入力がありません。別モデルへ切り替えません")
        quality = read_json(folder / "input/quality.json")
        write_json(ready / "input/quality.json", {**quality, "card_sha256": sha256(ready / "official-card.json"),
                   "card_fetched_at": final_card["fetched_at"], "post_preparation_roster_equal": True,
                   "prepared_from_card_sha256": quality["card_sha256"]})
        return ready
    else:
        write_json(folder / "model-comparison.json",
                   api_get(client, base + "/model-comparison", **coordinates, refresh="true"))
    return folder


def input_state(snapshot, day, now):
    """実際の観測時刻と履歴品質を保存し、古さを明示する。"""
    card, odds = snapshot["card"], snapshot["odds"]
    states = {}
    for key, value in (("card", card), ("odds", odds)):
        observed = datetime.fromisoformat(value["fetched_at"].replace("Z", "+00:00"))
        age = (now - observed).total_seconds()
        if not 0 <= age <= 86400:
            raise ValueError(f"{key}入力が未来時刻または24時間超です")
        states[key] = {"observed_at": value["fetched_at"], "age_seconds": age,
                       "observed_jst": observed.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S JST"),
                       "freshness": "recent_observation" if age <= 900 else "older_snapshot_recheck_required"}
    quality = snapshot.get("input_quality", {})
    states["history"] = {"before": quality.get("history_before"),
                         "coverage": quality.get("additional_coverage"),
                         "all_course_latest_verified": quality.get("all_course_history_latest_verified", False)}
    states["horse_weight"] = card.get("data_status", {}).get("horse_weight", "未取得")
    states["target_date"] = day
    states["near_post_latest_verified"] = False
    return states


def dansou_reference(odds):
    """同時点の単勝上位6人気から独立参考を計算し、本体の買い目は作らない。"""
    from jra_srb.jra_research_contracts import horse_number
    try:
        rows = odds["odds"]["win"]
        ordered = []
        for row in rows:
            if len(row["combination"]) != 1:
                raise ValueError("単勝の組合せ不正")
            number, price = horse_number(row["combination"][0]), float(row["odds"])
            if not math.isfinite(price) or price < 1:
                raise ValueError("単勝価格不正")
            ordered.append((number, price))
        ordered.sort(key=lambda item: (item[1], int(item[0])))
        if len(ordered) < 6 or len({h for h, _ in ordered}) != len(ordered):
            raise ValueError("上位6頭不足または重複")
        top = ordered[:6]
        ratios = [top[i+1][1] / top[i][1] for i in range(5)]
        largest = max(range(5), key=lambda i: ratios[i])
        breaks = sum(value >= 2 for value in ratios)
        pattern = 4 if breaks >= 2 else 1 if ratios[0] >= 2.5 else 2 if largest == 1 and ratios[1] >= 2 else 3 if largest >= 2 and ratios[largest] >= 2 else None
        candidate, price = top[largest]
        return {"status": "available", "observed_at": odds["fetched_at"], "top6": [list(item) for item in top], "ratios": ratios,
                "pattern": pattern, "largest_break_above": candidate,
                "reference_win_candidate": candidate if pattern is not None and 3 <= price <= 10.9 else None,
                "purchase_yen": 0, "main_tickets_changed": False, "movement": "変動未確認",
                "combination_tickets": [], "reason": "独立参考のみ。連系配当根拠・補助材料の確認不足で購入見送り"}
    except (KeyError, ValueError, TypeError, ResearchError):
        return {"status": "unavailable", "reason": "同時点の単勝上位6人気を確定できません", "main_tickets_changed": False}


def build_payload(model, forecast, snapshot, now=None, budget=0, research_prediction=True):
    """確率の意味を保った表示用データと保存payloadを同時に作る。

    Notes:
        2着内周辺順位から予想着順・勝率・上位3着予測を作らない。
        実購入0円と検証用の仮想買い目・予算を分離し、同じJSONへ保存する。
        全日探索ではresearch_prediction=Falseで仮想買い目の生成も省く。
    """
    now = now or datetime.now(timezone.utc)
    day = forecast["race_date"]
    if now >= post_time(day, snapshot["card"]["start_time"]):
        raise ValueError("発走後のため事前予想として保存できません")
    if model.get("trained_through") and model["trained_through"] >= day:
        raise ValueError("学習期間が対象日より前ではありません")
    state = input_state(snapshot, day, now)
    rows = forecast["horse_ranking"]
    horses = [str(r["horse_no"]) for r in rows]
    if not horses or len(set(horses)) != len(horses):
        raise ValueError("順位が空または重複しています")
    active = {str(r["horse_no"]).zfill(2) for r in snapshot["card"]["runners"] if r["status"] == "active"}
    if {h.zfill(2) for h in horses} != active:
        raise ValueError("選択モデルの順位と最新出走馬集合が一致しません")
    marks = dict(zip(horses[:6], ["◎", "○", "▲", "△", "△", "☆"]))
    prediction_id = f"jra-{forecast['race_id']}-{model['id']}-{uuid4().hex}"
    prediction = {
        "selected_model": model, "input_state": state,
        "race_conditions": {"date": day, **{key: snapshot["card"].get(key) for key in (
            "course", "surface", "distance", "start_time", "weather_label", "track_condition_label")},
            "withdrawn_or_excluded": [r["horse_no"] for r in snapshot["card"]["runners"] if r["status"] != "active"]},
        "ranking_semantics": model["ranking_semantics"],
        "probability_capabilities": model["probabilities"],
        "predicted_ranking": [{**r, "mark": marks.get(r["horse_no"], "")} for r in rows],
        "predicted_top3": [], "finish_order_prediction_available": False,
        "marks": marks, "head_horse_numbers": [], "axis_horse_numbers": horses[:1],
        "opponent_horse_numbers": horses[1:6], "axis_semantics": "モデル順位に基づく参考軸・購入指示なし",
        "betting_decision_status": "research_prediction_virtual_only",
        "no_bet_reasons": ["購入推奨の検証・承認済み購入方針がありません", "予算指定だけでは購入条件を満たしません"],
        "requested_budget": budget, "purchase_yen": 0, "prediction_tickets": [],
        "forecast": forecast, "generated_before_result": True,
        "comparison": {"v_theory": "本体に使用・追加比較未取得" if model["adapter"] == "v_theory" else "未取得（本体への適用なし）", "other_models": "未取得"},
        "evaluation_semantics": "馬連確率・2着内周辺順位は着順予測の的中率と区別。購入0円は未購入",
        "dansou_reference": dansou_reference(snapshot["odds"]),
    }
    if research_prediction:
        prediction["research_plan"] = build_research_plan(model, forecast, snapshot, budget)
    payload = {"prediction_id": prediction_id, "race_id": forecast["race_id"],
               "theory_version": f"{model['id']}:{model['version']}", "mode": "research_prediction",
               "budget": 0, "created_at": now.isoformat(), "pre_race_snapshot": snapshot,
               "prediction_json": prediction, "prediction_tickets": []}
    return payload


def render(payload):
    """保存する構造化値から表示本文を生成し、別の順位や買い目を混ぜない。"""
    p, snapshot = payload["prediction_json"], payload["pre_race_snapshot"]
    model, forecast = p["selected_model"], p["forecast"]
    if any(r["mark"] != p["marks"].get(r["horse_no"], "") for r in p["predicted_ranking"]):
        raise ValueError("表示本文と保存する印が一致しません")
    if ([r["horse_no"] for r in p["predicted_ranking"]] != [r["horse_no"] for r in forecast["horse_ranking"]]
            or payload["budget"] != 0 or payload["prediction_tickets"] or p["prediction_tickets"]
            or p["purchase_yen"] != 0):
        raise ValueError("表示本文と選択モデル・購入0円の保存契約が一致しません")
    top2 = "top2_marginal" in model["probabilities"]
    research = p.get("research_plan")
    if research is not None and research != build_research_plan(model, forecast, snapshot, p["requested_budget"]):
        raise ValueError("研究プランと選択モデル・実オッズ・仮想予算が一致しません")
    text = ["# レース情報", f"{payload['race_id']} {snapshot['card'].get('race_name', '')}",
            json.dumps(p["race_conditions"], ensure_ascii=False),
            "## 予想モード", "研究予想・仮想買い目で検証（実購入0円）", "## 使用モデル",
            f"{model['name']} / {model['version']} / {model['selection_source']}",
            f"学習期間: {model.get('training_start')} ～ {model.get('trained_through')}（V系は学習期間の概念なし）",
            f"利用状態: {model['availability']} / {model['validation']} / 研究利用={model['research_allowed']} / 購入推奨={model['purchase_allowed']}",
            "馬連確率と2着内周辺確率。単勝勝率・予想着順ではありません。" if top2 else "V系の評価順位。確率ではありません。",
            "## 取得時点・データ状態", json.dumps(p["input_state"], ensure_ascii=False),
            "## 使用データと欠損", "公式カード・実オッズ・モデル入力品質は保存束を参照。履歴全場最新性の未確認を保持。",
            "## 当日傾向", "未取得（本体順位の上書きなし）", "## 熱さ判定", "未判定・購入推奨なし",
            "## 予想順位", "2着内周辺順位（着順・勝率順位ではない）" if top2 else "選択したV系モデルの評価順位",
            "| 順位 | 印 | 馬番 | 馬名 | 2着内周辺確率 |" if top2 else "| 順位 | 印 | 馬番 | 馬名 | 評価 |",
            "| --- | --- | --- | --- | --- |"]
    names = forecast.get("horse_names", {})
    for index, row in enumerate(p["predicted_ranking"], 1):
        value = f"{row['top2_probability']:.3%}" if top2 else "確率なし"
        text.append(f"| {index} | {row['mark']} | {row['horse_no']} | {names.get(row['horse_no'], '')} | {value} |")
    text += ["## 予想の根拠", f"参考軸: {p['axis_horse_numbers']} / 参考相手: {p['opponent_horse_numbers']} / 頭候補: なし",
             "選択モデルの評価順に印を付与。各馬の能力要因の寄与は未計算。"]
    if top2:
        text.append("馬連確率上位（購入指示なし）:")
        for row in forecast["pair_ranking"][:5]:
            text.append(f"- {'-'.join(row['horses'])}: {row['probability']:.3%}")
    text += ["## V系評価（任意の補助比較）", p["comparison"]["v_theory"],
             "## 評価系統の比較", "追加比較値は未取得。同じ市場情報を使うモデルの一致を独立根拠としません。",
             "## 買い方", "検証用の仮想買い目。実購入0円。配分規則の利益優位は未検証。",
             "| 券種 | 組合せ | 実オッズ | 仮想金額 | 採用理由 |", "| --- | --- | --- | --- | --- |"]
    for ticket in (research or {}).get("tickets", []):
        text.append(f"| 馬連 | {'-'.join(ticket['selection'])} | {ticket['odds']} | {ticket['amount']}円 | {ticket['reason']} |")
    if not research or research["status"] != "available":
        text.append("仮想配分なし: " + (research or {}).get("reason", "研究プラン未保存"))
    text += [f"オッズ取得時点: {p['input_state']['odds']['observed_jst']}。",
             "実購入の見送り理由: " + " / ".join(p["no_bet_reasons"]), "## 予算別の買い方"]
    if research:
        text.append(f"選択した検証用仮想予算: {research['virtual_budget_yen']}円（未指定時1000円）。規則: {research['policy_id']}")
        for plan in research["budget_plans"]:
            text.append(f"仮想{plan['budget_yen']}円: " + " / ".join(
                f"馬連{'-'.join(t['selection'])} {t['amount']}円" for t in plan["tickets"]))
    text += ["保存評価対象は選択した仮想プラン1つだけ。実購入への配分なし。",
             "## マークシート向け", "検証用転記（実購入指示ではありません）"]
    text += [f"馬連: {'-'.join(t['selection'])}（実オッズ{t['odds']}倍・仮想{t['amount']}円）"
             for t in (research or {}).get("tickets", [])] or ["仮想配分の記入対象なし"]
    text += ["## 注意点", *model.get("limitations", []),
             "保存時刻を入力観測時刻や発走直前観測へ読み替えません。未実装券種の確率はありません。",
             "## 断層競馬参考", "#### ■ 断層競馬", "独立参考。本体の順位・印・購入判断は変更しません。"]
    d = p["dansou_reference"]
    text += ["#### ■ 取得時点", d.get("observed_at", "未取得"), "#### ■ 上位1〜6人気"]
    text += [f"{h} {names.get(h, '')} {price}倍" for h, price in d.get("top6", [])] or ["未取得"]
    text += ["#### ■ 断層チェック", f"倍率: {d.get('ratios', '未取得')} / パターン: {d.get('pattern', '未取得')} / 最大断層直上: {d.get('largest_break_above', '未取得')}",
             "#### ■ 総合判定", "見送り（独立参考・購入0円）", "#### ■ 単勝", f"参考候補: {d.get('reference_win_candidate') or 'なし'}・購入なし",
             "#### ■ 3連複", "見送り・配当根拠未確認", "#### ■ 追加提案", "なし・連系購入条件未確認",
             "#### ■ 補助材料", "追加比較未取得", "#### ■ 見送り条件", d.get("reason", "条件未確認"),
             d.get("movement", "変動未確認"), f"prediction_id: {payload['prediction_id']}"]
    return ("\n\n".join(text) + "\n").replace("|\n\n|", "|\n|")


def save_prediction(payload, client=None):
    """共通SQLへ新IDで保存し、予想全文・入力束・買い目・金額を読み戻す。

    Raises:
        ValueError: SQL以外、ID衝突、表示不一致、読戻し不一致または発走後。
    Notes:
        API client指定時はGET応答も全文比較する。失敗時は結果取得へ進まない。
    """
    from jra_srb.storage import build_analysis_store
    from jra_srb.storage_config import storage_backend
    p = payload["prediction_json"]
    if p["presentation_markdown"] != render(payload):
        raise ValueError("表示本文と保存する構造化値が一致しません")
    if datetime.now(timezone.utc) >= post_time(p["forecast"]["race_date"], payload["pre_race_snapshot"]["card"]["start_time"]):
        raise ValueError("保存直前に発走時刻を過ぎました")
    if storage_backend() != "sqlserver":
        raise ValueError("共通SQL Server設定が必要です")
    store = build_analysis_store(ROOT / "data/db/analysis.sqlite")
    try:
        try:
            store.get_prediction_record(payload["prediction_id"])
        except LookupError:
            pass
        else:
            raise ValueError("既存予想IDは上書きしません")
        store.upsert_prediction_record(payload)
        saved = store.get_prediction_record(payload["prediction_id"])
        if not (saved.prediction == p and saved.pre_race_snapshot == payload["pre_race_snapshot"]
                and saved.race_id == payload["race_id"] and saved.budget == 0 and not saved.prediction_tickets):
            raise ValueError("SQL読戻し不一致")
        if client is not None:
            actual = api_get(client, "/jra/predictions/" + payload["prediction_id"])
            if not (actual["prediction"] == p and actual["pre_race_snapshot"] == payload["pre_race_snapshot"]
                    and actual["budget"] == 0 and not actual["prediction_tickets"]):
                raise ValueError("API読戻し不一致")
        return {"prediction_id": payload["prediction_id"], "sql_readback_verified": True,
                "api_readback_verified": client is not None, "purchase_yen": 0}
    finally:
        if hasattr(store, "close"):
            store.close()


def score_j23_snapshot(model, source):
    """既存の固定J23と12特徴で推論し、確率の意味を保った参考出力を返す。

    Args:
        model: 明示指定された検証済みJ23設定。購入・既定への昇格は認めない。
        source: 公式カード/単勝/馬連と準備済み12特徴を持つフォルダー。
    Returns:
        馬連/2着内周辺順位と、入力・取消処理・固定モデルの監査snapshot。
    Raises:
        ValueError: 入力、時刻、取消根拠、モデルSHA、学習期間または確率が不一致。
    Notes:
        既存learnerを使い、D0推論・再学習・旧購入政策の転用はしない。
        明示取消馬のオッズ行だけを除外し、原本と元の観測時刻を保持する。
    """
    from copy import deepcopy
    from itertools import combinations
    import numpy as np
    from compare_jra_condition_preview import price_array, ranking
    from jra_srb import jra_research_j23_live as legacy
    from jra_srb.jra_research_native_card import _official_source_url

    card = read_json(source / "official-card.json")
    original_odds = read_json(source / "official-odds.json")
    quality = read_json(source / "input/quality.json")
    public = read_json(source / "input/j23_public_features.json")
    context = read_json(source / "input/input.json")
    day = public["race_date"]
    now = datetime.now(timezone.utc)
    if (quality.get("status") != "passed" or quality["card_sha256"] != sha256(source / "official-card.json")
            or len({card["race_id"], original_odds["race_id"], public["race_id"], context["race_id"]}) != 1
            or public["horses"] != context["horses"] or context["race_date"] != day
            or now >= post_time(day, card["start_time"])):
        raise ValueError("J23の入力品質・同定・発走前条件を満たしません")
    if (not all(_official_source_url(value["source"]) for value in (card, original_odds))
            or card.get("data_status", {}).get("runner_set") != "complete"
            or card.get("data_status", {}).get("source_kind") != "pre_race_card"):
        raise ValueError("J23の公式発走前カード/価格を確認できません")
    horses = public["horses"]
    active = {str(row["horse_no"]).zfill(2) for row in card["runners"] if row["status"] == "active"}
    inactive = {str(row["horse_no"]).zfill(2): row for row in card["runners"] if row["status"] != "active"}
    if (not 8 <= len(horses) <= 18 or set(horses) != active or len(set(horses)) != len(horses)
            or any(row["status"] not in {"withdrawn", "excluded"} or row.get("status_source") != "explicit" for row in inactive.values())):
        raise ValueError("J23の出走馬集合・取消根拠を確認できません")
    odds = deepcopy(original_odds)
    counts = {}
    for kind, rows in odds["odds"].items():
        if any(str(h).zfill(2) not in active | set(inactive) for row in rows for h in row["combination"]):
            raise ValueError("J23のオッズに未同定馬が含まれます")
        kept = [row for row in rows if row["combination"] and all(str(h).zfill(2) in active for h in row["combination"])]
        odds["odds"][kind] = kept
        counts[kind] = {"original": len(rows), "active_only": len(kept)}
    odds["normalization"] = {"source_sha256": sha256(source / "official-odds.json"), "counts": counts,
                             "excluded_horses": sorted(inactive), "rule": "公式明示取消・除外を含む行のみ除去。価格補完なし"}
    if odds.get("entries"):
        odds["entries"] = [row for row in odds["entries"] if row["combination"] and all(str(h).zfill(2) in active for h in row["combination"])]
    snapshot = {"card": card, "odds": odds, "source_odds": original_odds, "input_quality": quality,
                "j23_public_features": public, "feature_file_sha256": sha256(source / "input/j23_public_features.json")}
    input_state(snapshot, day, now)
    fitted, _, provenance = legacy.load_frozen(day)
    if provenance["model_sha256"] != model["sha256"] or provenance["trained_through"] != model["trained_through"]:
        raise ValueError("指定J23と既存固定モデルが一致しません。自動代替しません")
    x = np.asarray(public["x"], dtype=np.float32)
    if x.shape != (len(horses), 12) or not np.isfinite(x).all():
        raise ValueError("J23の12特徴契約を満たしません。ゼロ補完しません")
    prices = price_array(odds, "quinella", list(combinations(horses, 2)))
    win = price_array(odds, "win", [(h,) for h in horses])
    market = 1 / prices
    market /= market.sum()
    record = {"x": x, "market": market, "pl": legacy.features.pl_pairs(1 / win),
              "addition": np.empty((len(horses), 0)), "basic": np.empty((len(horses), 0)),
              "styles": np.zeros(len(horses)), "density": 0.,
              "group": context["surface"] * 2 + int(context["distance"] >= 2000)}
    p = legacy.learner.predict(fitted, legacy.learner.clean_record(record))
    changed = legacy.learner.predict(fitted, legacy.learner.clean_record({**record, "winner": -1, "payout_yen": -1}))
    if not (len(p) == len(prices) and np.isfinite(p).all() and np.all(p > 0)
            and abs(float(p.sum())-1) < 1e-9 and np.array_equal(p, changed)):
        raise ValueError("J23の確率契約・結果遮断を満たしません")
    snapshot["model_provenance"] = provenance
    forecast = {**ranking(p, horses), "case": "J23", "race_id": public["race_id"], "race_date": day,
                "created_at": now.isoformat(), "trained_through": provenance["trained_through"],
                "model_sha256": provenance["model_sha256"], "provenance": provenance,
                "horse_names": {str(row["horse_no"]).zfill(2): row["horse_name"] for row in card["runners"]},
                "probability_type": "quinella_and_top2_marginal_not_win_probability", "market_input": True,
                "research_only": True, "purchase_allowed": False, "result_ignored": True}
    return forecast, snapshot


def predict(model, source, output, budget=0, course=None, research_prediction=True):
    """選択したアダプターだけを実行し、表示と保存用payloadを作る。"""
    output.mkdir(parents=True, exist_ok=False)
    if model["adapter"] == "attribute_chimera":
        from score_jra_attribute_chimera import score
        score(SimpleNamespace(training_run=(ROOT / model["artifact"]).parent,
                              snapshot_dir=source, output=output / "score", save=False))
        forecast = read_json(output / "score/forecast.json")
        snapshot = read_json(output / "score/input.json")
    elif model["adapter"] == "j23_frozen":
        forecast, snapshot = score_j23_snapshot(model, source)
        write_json(output / "forecast.json", forecast)
        write_json(output / "input.json", snapshot)
    else:
        if course not in model["courses"]:
            raise ValueError(f"指定Vモデルは対象場に対応しません: {model['id']} / {course}")
        comparison = read_json(source / "model-comparison.json")
        v = comparison["v_theory"]
        if v.get("theory_version", "").lower() != model["id"] or v.get("status") not in {"available", "provisional"} or not v.get("ranking"):
            raise ValueError(f"指定Vモデルが利用不可です: {v.get('reason', v.get('status'))}")
        card, odds = read_json(source / "official-card.json"), read_json(source / "official-odds.json")
        snapshot = {"card": card, "odds": odds, "model_comparison": comparison}
        forecast = {"race_id": card["race_id"], "race_date": f"{card['race_id'][:4]}-{card['race_id'][4:6]}-{card['race_id'][6:8]}",
                    "horse_ranking": v["ranking"], "horse_names": {r["horse_no"]: r["horse_name"] for r in card["runners"]},
                    "raw_v_status": v, "pair_ranking": []}
    payload = build_payload(model, forecast, snapshot, budget=budget, research_prediction=research_prediction)
    payload["prediction_json"]["presentation_markdown"] = render(payload)
    write_json(output / "prediction_payload.json", payload)
    (output / "presentation.md").write_text(payload["prediction_json"]["presentation_markdown"], encoding="utf-8")
    return payload


def scout_metric(model, payload):
    """設定された比較可能な値だけを返す。的中確度として校正された値ではない。"""
    if model.get("scout_metric") != "top_pair_probability":
        raise ValueError("このモデルのレース間比較指標は未実装です")
    return payload["prediction_json"]["forecast"]["pair_ranking"][0]["probability"]


def scout(args, model, client):
    """当日全レースを列挙し、同一モデルで分析できた範囲と未分析を保存する。

    Notes:
        発走済み・不足・取得上限を全て残す。旧APIの勝率差へ戻さない。
        チケットや購入予想は保存せず、分析証跡だけをローカルに残す。
    """
    if model.get("scout_metric") != "top_pair_probability":
        raise ValueError("指定モデルのレース間比較は未実装です。個別予想と区別し、他モデルへ代替しません")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.snapshot_index:
        index = read_json(args.snapshot_index)
        if index["date"] != args.date:
            raise ValueError("snapshot indexの対象日が一致しません")
        races = index.get("races", index.get("entries"))
        if not isinstance(races, list):
            raise ValueError("snapshot indexに全競走のracesまたはentriesが必要です")
    else:
        summaries = api_get(client, "/races", date=args.date)
        races = [{"race_id": r["race_id"], "course": r["course"], "race_no": int(r["race_id"][-2:]),
                  "race_name": r["name"], "start_time": r["start_time"]} for r in summaries]
    entries, fetched, common_failure = [], 0, None
    for race in races:
        entry = {**{key: value for key, value in race.items() if key not in {"reason", "metric", "input_state", "status"}}, "status": "unavailable"}
        try:
            if common_failure:
                raise ValueError(common_failure)
            if not race["race_id"].startswith(args.date.replace("-", "")):
                raise ValueError("一覧の対象日が一致しません")
            if datetime.now(timezone.utc) >= post_time(args.date, race["start_time"]):
                raise ValueError("発走済み")
            source = Path(race["snapshot_dir"]) if race.get("snapshot_dir") else None
            if source is None:
                if fetched >= args.max_fetches:
                    raise ValueError("取得上限・次回逐次補完対象")
                fetched += 1
                source = acquire_snapshot(client, args.date, race["course"], race["race_no"], model,
                                          args.output / (race["race_id"] + "-snapshot"))
            payload = predict(model, source, args.output / race["race_id"], course=race["course"], research_prediction=False)
            if payload["race_id"] != race["race_id"]:
                raise ValueError("一覧と入力の競走が一致しません")
            entry.update(status="analyzed", metric=scout_metric(model, payload),
                         input_state=payload["prediction_json"]["input_state"], snapshot_dir=str(source.resolve()))
        except (OSError, ValueError, KeyError, StopIteration, ResearchError, httpx.HTTPError) as error:
            entry["reason"] = str(error) or type(error).__name__
            if isinstance(error, httpx.ConnectError):
                common_failure = "ローカルAPI接続不能のため残件の取得を停止しました"
        entries.append(entry)
        write_json(args.output / f"entry-{len(entries):03d}.json", entry)
    ranked = sorted((e for e in entries if e["status"] == "analyzed"), key=lambda e: (-e["metric"], e["race_id"]))
    report = {"date": args.date, "selected_model": model, "entries": entries, "ranked": ranked,
              "status": "completed" if entries and len(ranked) == len(entries) else "partial",
              "metric": model.get("scout_metric"), "metric_meaning": "馬連最大予測確率による探索的比較。券種的中確度・利益の優位は未検証",
              "all_day_highest_confidence_proven": False, "purchase_yen": 0}
    write_json(args.output / "scout.json", report)
    lines = ["# JRA全レース相対比較", "## 実行状況", f"{args.date} {model['name']} / {model['version']} 分析済み{len(ranked)}/{len(entries)}",
             f"学習期間: {model.get('training_start')} ～ {model.get('trained_through')} / 利用状態: {model['validation']} / 研究={model['research_allowed']} / 購入推奨={model['purchase_allowed']}",
             "## 相対指標ランキング", report["metric_meaning"]]
    lines += [f"- {e['course']} {e['race_no']}R {e.get('race_name', '')}: {e['metric']:.3%} / 入力時点: {e['input_state']['odds']['observed_at']} / {e['input_state']['odds']['freshness']}" for e in ranked]
    lines += ["## 重賞", "公式格の追加照合は未実施。レース名や旧スカウトgradeから補完しません。"]
    lines += ["## 未分析・除外"] + [f"- {e['race_id']}: {e['reason']}" for e in entries if e["status"] != "analyzed"]
    lines += ["## 読み方", "分析範囲の比較。的中確度や購入推奨ではありません。選んだレースは直前に同じ選択規則で個別予想します。"]
    (args.output / "presentation.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    """モデル選択・単発予想・全日比較をCLIへ公開する。"""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ.setdefault("JRA_SRB_STORAGE_ENV_FILE", str(ROOT / "data/storage/runtime.env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["resolve", "predict", "scout"])
    parser.add_argument("--model")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--snapshot-index", type=Path)
    parser.add_argument("--date")
    parser.add_argument("--course")
    parser.add_argument("--race-no", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--budget", type=int, default=0)
    parser.add_argument("--max-fetches", type=int, default=5)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    model = resolve_model(args.model, args.config)
    if args.command == "resolve":
        print(json.dumps(model, ensure_ascii=False, indent=2))
        return
    if args.output is None or args.budget < 0 or args.max_fetches < 0:
        parser.error("--outputと非負の予算・取得件数が必要です")
    with httpx.Client(base_url=args.api_base, timeout=20) as client:
        if args.command == "scout":
            if args.save or not args.date:
                parser.error("scoutは--date必須、--save不可です")
            result = scout(args, model, client)
            print(json.dumps({"status": result["status"], "analyzed": len(result["ranked"]), "model": model["id"]}, ensure_ascii=False))
        else:
            source = args.snapshot_dir
            if source is None:
                if not all([args.date, args.course, args.race_no]):
                    parser.error("--snapshot-dirまたは--date/--course/--race-noが必要です")
                acquisition = args.output.with_name(args.output.name + "-snapshot")
                try:
                    source = acquire_snapshot(client, args.date, args.course, args.race_no, model, acquisition)
                except Exception as error:
                    if acquisition.is_dir() and not (acquisition / "failure.json").exists():
                        write_json(acquisition / "failure.json", {"stage": "official_input_acquisition_or_preparation",
                            "error_type": type(error).__name__, "prediction_saved": False, "outcome_reads": 0})
                    raise
            payload = predict(model, source, args.output, args.budget, args.course)
            if args.save:
                try:
                    receipt = save_prediction(payload, client)
                    write_json(args.output / "save-verification.json", receipt)
                    print(json.dumps(receipt, ensure_ascii=False))
                except Exception as error:
                    write_json(args.output / "save-failure.json", {"status": "予想未保存または読戻し未確認", "reason": type(error).__name__})
                    raise
            else:
                print("未保存: " + payload["prediction_id"])


if __name__ == "__main__":
    main()
