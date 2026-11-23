"""概要: 対応三重賞の公式全頭履歴を取得照合し、固定研究v2予想へ接続する。
作成日: 2026-11-14。
入力: collect/predict、対象日・系列、新規保存先、既存研究設定と読取専用SQL。
出力: 公式原文・カード・全履歴・照合結果・予想JSON・表示本文・manifest。
実行例: uv run python scripts/run_jra_graded_live.py collect --date 2026-11-14 --series musashino --output artifacts/live-musashino
注意事項: collectは公式JRAとローカルAPIへ通信、研究SQLはSELECTのみ。実購入・当日結果取得なし。
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from itertools import combinations
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx
from bs4 import BeautifulSoup
from audit_elizabeth_2026_inputs import parse_history, compare_recent
from jra_srb.provider import HttpProvider
from jra_srb.jra_race_conditions import load_config, require, FEATURE_LABELS
from jra_srb.jra_race_conditions_sql import ConditionsReader
from jra_srb.jra_research_contracts import horse_number, digest
from jra_srb.jra_graded_live import SERIES, score_live


def read(path):
    """UTF-8の保存JSONを読む。"""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    """新規JSONを保存し、丸め前値と原文を上書きしない。"""
    with Path(path).open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False, indent=2)
        f.write("\n")


def table(columns, rows):
    """固定列のMarkdown表を作り、セル内改行と区切りを保護する。"""
    clean = lambda v: str(v).replace("|", "／").replace("\n", " ")
    return "\n".join(["|"+"|".join(columns)+"|", "|"+"|".join("---" for _ in columns)+"|",
                      *["|"+"|".join(clean(v) for v in row)+"|" for row in rows]])


def jst(value):
    """保存した観測時刻を日本時間で表示する。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M:%S JST")


def condition_label(item):
    """研究特徴のコードを表示用の日本語へ変換する。"""
    value = item["value"]
    if item["feature"] == "previous_weight_rule":
        value = {"1": "ハンデ", "2": "別定", "3": "馬齢", "4": "定量"}.get(value, value)
    elif item["feature"] == "previous_grade":
        value = {"A": "GI", "B": "GII", "C": "GIII", "L": "リステッド"}.get(value, value)
    return FEATURE_LABELS[item["feature"]].replace("DB内直近走", "直近JRA走")+"＝"+str(value)


def observed_price(odds, bet, selection):
    """対象組の一意な実価格を検証し、未取得はNoneで返す。"""
    chosen = sorted(map(horse_number, selection), key=int)
    matches = [r for r in odds["odds"].get(bet, [])
               if sorted(map(horse_number, r["combination"]), key=int) == chosen]
    require(len(matches) <= 1, "live_duplicate_odds")
    if not matches:
        return None
    price = matches[0]
    if bet == "wide":
        low, high = price.get("odds_min"), price.get("odds_max")
        if low is None or high is None:
            return None
        require(1 <= float(low) <= float(high) < float("inf"), "live_invalid_wide_odds")
    else:
        if price.get("odds") is None:
            return None
        require(1 <= float(price["odds"]) < float("inf"), "live_invalid_trio_odds")
    return price


def history_statuses(history, profiles):
    """公式の取消・除外を非出走として保持し、過去実績集計へ混入させない。"""
    source = {(r["horse_id"], r["race_key"]): r for r in profiles if r["race_key"]}
    output = []
    for row in history:
        profile = source[(row["horse_id"], row["race_key"])]
        status = "excluded" if profile["rank_raw"] in ("取消", "除外") else "active"
        output.append({**row, "status": status})
    return output


def render(result):
    """研究専用の固定10節を保存データから生成する。"""
    c, f, odds = result["card"], result["forecast"], result["odds"]
    win = {horse_number(r["combination"][0]): r for r in odds["odds"].get("win", [])}
    popular = {h: i for i, h in enumerate(sorted(win, key=lambda h: (float(win[h]["odds"]), int(h))), 1)}
    market_first = min(popular, key=popular.get) if popular else None
    plan = result["condition_parts_plan"]
    lines = ["使用方式：条件パーツ研究v2／選択理由：今回の明示指定／モデル：frozen_v2", "",
             "## 1. レースと使用方式", "",
             table(["項目", "内容"], [["対象", f"{c['race_date']} {c['race_name']} {c['race_key']}"],
                ["使用方式", "条件パーツ研究v2"], ["選択理由", "今回の明示指定"],
                ["使用モデル", f"frozen_v2／{f['prior_races']}開催／集計最終{f['prior_latest_date']}／設定SHA {result['config_sha256'][:12]}"],
                ["予想作成時刻", jst(result["created_at"])], ["予想の状態", result["prediction_state"]],
                ["確率の意味", "3着内参考確率。未校正。◎は1着予想ではない。"]]), "",
             "## 2. 入力データの状態", "",
             table(["材料", "観測時刻", "確認結果・不足"], [
                ["出馬表・取消", jst(result["final_card"]["fetched_at"]), f"{len(c['runners'])}頭。公式ID・生年・近走一致。取消再確認済み"],
                ["過去走・競走条件", jst(result["input_completed_at"]), f"JRA履歴{result['history_rows']}件（取消・除外{result['inactive_history_rows']}件は集計外）。地方・海外{result['excluded_rows']}走は別保存・計算外"],
                ["馬場・馬体重", jst(result["final_card"]["fetched_at"]), f"馬場{result['final_card'].get('track_condition_label') or '未取得'}。馬体重・馬場はモデル未使用"],
                ["単勝オッズ", jst(odds["fetched_at"]), f"{len(win)}頭"],
                ["ワイド・3連複オッズ", jst(odds["fetched_at"]), "主案価格を下表へ記載"],
                ["補助券種オッズ", "未取得", "補助案なし"]]), "",
             "## 3. 全頭評価", "",
             table(["評価順位", "印", "馬番・馬名", "3着内参考確率", "単勝オッズ・人気", "市場人気との差"], [
                [r["rank"], r["mark"], f"{int(r['horse_no'])} {r['horse_name']}", f"{r['probability_top3']:.1%}",
                 f"{win[r['horse_no']]['odds']}倍・{popular[r['horse_no']]}人気" if r["horse_no"] in win else "未取得",
                 popular[r["horse_no"]]-r["rank"] if r["horse_no"] in popular else "未取得"] for r in f["runners"]]),
             "", "人気との差は順位比較で、期待値ではありません。", "",
             "## 4. 使用パーツと評価の根拠", ""]
    evidence = {r["horse_no"]: r for r in f["evidence"]}
    lead = f["runners"][0]
    groups = evidence[lead["horse_no"]]
    rows = []
    for i, e in enumerate(groups["evidence"]):
        varying = [v for v in e["items"] if len({r["values"][v["feature"]] for r in f["features"]}) > 1]
        item = max(varying or e["items"], key=lambda v: v["n"]) if e["items"] else None
        rows.append([e["group"], f"◎{int(lead['horse_no'])}：{condition_label(item)}" if item else "該当集計なし",
                     f"3着内{item['weighted_top3']:g}/{item['n']}頭" if item else "未計算",
                     "上限制御前の群評価は"+("上向き" if groups["deltas"][i] > 0 else "下向き" if groups["deltas"][i] < 0 else "中立")])
    lines += [table(["条件群", "今回使った条件", "過去の根拠", "今回の評価への影響"], rows), "",
              "5群を固定強度4で合成し、同じ入力の基準比±5ポイントに制限。全馬の詳細根拠は予想JSONに保存。騎手・調教・血統・仕上がりは未評価。", "",
              "## 5. 市場比較と採否", "",
              table(["対象馬", "モデル評価", "市場評価", "扱い", "理由"], [
                  [f"{int(r['horse_no'])} {r['horse_name']}", f"{r['rank']}位・{r['probability_top3']:.1%}",
                   f"{popular.get(r['horse_no'], '未取得')}人気", "主案に含める" if r["rank"] <= 3 else "主案から外す",
                   "固定した上位3頭の規則。単勝人気でモデル順位を変更しない"]
                  for r in f["runners"] if r["rank"] <= 3 or r["horse_no"] == market_first]), "",
              "## 6. 主案の検証用仮想買い目", "",
              f"主案ID：{plan['plan_id']}／規則：{plan['policy_id']}／評価対象：この主案1つ", "",
              table(["券種", "組合せ", "実オッズ", "仮想金額", "採用理由"], [
                  ["ワイド" if t["bet_type"] == "wide" else "3連複", "−".join(str(int(h)) for h in t["selection"]),
                   t["display_odds"], "100円" if plan["status"] == "priced" else "基準100円・採用保留", "研究v2上位3頭の固定主案"] for t in plan["tickets"]]),
              "", "主案合計："+("仮想400円" if plan["status"] == "priced" else "基準400円・価格不足で採用保留")+"。実購入0円。", "",
              "## 7. 補助案・追加仮説", "",
              table(["案ID", "券種・組合せ", "実オッズ", "仮想金額", "仮説・根拠", "評価上の扱い"],
                    [["なし", "非適用", "非適用", "非適用", "追加案なし", "主案に非合算"]]), "",
              "## 8. 保存状況", "",
              table(["項目", "状態"], [["予想ID", "SQL未保存"], ["主案・入力・表示全文", f"研究ファイル保存：{result['artifact_id']}"],
                    ["事前保存の確認", result["prediction_state"]+"。ファイル読戻しで照合"], ["自動評価の対応", "ワイド・3連複の共通自動評価は未接続"]]), "",
              "## 9. 結果検証", "",
              table(["評価項目", "結果"], [["公式結果・払戻", "未取得・結果は参照していない"], ["モデル評価と実際の3着内馬", "未確定"],
                     ["主案：仮想購入額・払戻・回収率", "未確定"], ["券種別的中・トリガミ", "未確定"], ["補助仮説", "追加案なし"]]), "",
              "## 10. 断層競馬の独立参考", "", "未判定。本体の印・確率・買い目へ混入しない。", ""]
    return "\n".join(lines)


def predict(args):
    """照合済み入力を固定v2へ適用し、最新カード・価格を確認して新規保存する。"""
    complete = read(args.input / "collection-complete.json")
    require(complete["series"] == args.series, "live_collection_series")
    dataset_path = ROOT / ("artifacts/jra_research/elizabeth_conditions_v1_20261108_export_v4/dataset.json"
                           if args.series == "elizabeth" else "artifacts/jra_research/graded_patterns_20261114_export_v2/dataset.json")
    dataset = read(dataset_path)
    require(dataset["input_sha256"] == digest({k: v for k, v in dataset.items() if k != "input_sha256"}), "live_dataset_sha")
    card = read(args.input / "normalized-card.json")
    history = history_statuses(read(args.input / "normalized-history.json"), read(args.input / "profile-history.json"))
    require(card["race_date"] == args.date, "live_date")
    config = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    definition = next(c for c in read(ROOT / "configs/research/graded_common_pattern_candidates_v1.json")["candidates"] if c["id"] == "frozen_v2")
    require(definition["group_weights"] == [1]*5 and definition["score_scale"] == 4
            and definition["shrinkage"] == 20 and definition["cap"] == .05
            and definition["cap_baseline"] == "balanced_scale1" and definition["quality_definition"] is True,
            "live_frozen_config_changed")
    forecast = score_live(dataset, card, history, config, args.series)
    course = "tokyo" if args.series == "musashino" else "kyoto"
    with httpx.Client(base_url=args.api_base, timeout=30) as client:
        response = client.get(f"/meetings/{args.date}/{course}/races/11/card", params={"refresh": "true"})
        response.raise_for_status()
        final = response.json()
        fields = ("horse_no", "horse_name", "sex_age", "status", "frame_no", "weight_carried", "official_recent_races")
        initial = read(args.input / "official-card.json")
        require([{k: r.get(k) for k in fields} for r in final["runners"]] ==
                [{k: r.get(k) for k in fields} for r in initial["runners"]]
                and all(final[k] == initial[k] for k in ("race_id", "distance", "surface", "start_time")), "live_card_changed")
        require(datetime.now(timezone.utc) < datetime.fromisoformat(card["start_at"]), "live_post_time")
        response = client.get(f"/jra/meetings/{args.date}/{course}/races/11/odds-summary",
                              params={"bet_types": "win,wide,trio", "refresh": "true"})
        response.raise_for_status()
        odds = response.json()
    require(odds["race_id"] == card["race_key"], "live_odds_identity")
    observed = datetime.fromisoformat(odds["fetched_at"].replace("Z", "+00:00"))
    require(0 <= (datetime.now(timezone.utc)-observed).total_seconds() <= 900, "live_odds_stale")
    top = [r["horse_no"] for r in forecast["runners"][:3]]
    tickets = []
    for bet, selections in (("wide", list(combinations(top, 2))), ("trio", [tuple(top)])):
        for selection in selections:
            chosen = sorted(selection, key=int)
            price = observed_price(odds, bet, chosen)
            shown = "未取得" if not price else ((str(price.get("odds_min"))+"〜"+str(price.get("odds_max"))+"倍") if bet == "wide" else str(price["odds"])+"倍")
            tickets.append({"bet_type": bet, "selection": chosen, "amount": 100, "observed_odds": price,
                            "observed_at": odds["fetched_at"] if price else None, "display_odds": shown})
    now = datetime.now(timezone.utc)
    require(now < datetime.fromisoformat(card["start_at"]), "live_post_before_save")
    args.output.mkdir(parents=True, exist_ok=False)
    artifact = "condition-parts-v2-"+card["race_key"]+"-"+str(uuid4())
    result = {"artifact_id": artifact, "created_at": now.astimezone(timezone(timedelta(hours=9))).isoformat(), "prediction_state": "発走前・研究ファイル保存",
              "generated_before_result": True, "outcome_reads": 0, "method_selection": {"method": "condition_parts", "model": "frozen_v2", "source": "explicit_method", "reason": "今回の明示指定"},
              "card": card, "forecast": forecast, "odds": odds, "final_card": final, "history_rows": len(history),
              "inactive_history_rows": sum(h["status"] == "excluded" for h in history),
              "excluded_rows": len(read(args.input / "excluded-non-jra-history.json")), "input_completed_at": complete["completed_at"],
              "config_sha256": digest(read(ROOT / "configs/research/graded_common_pattern_candidates_v1.json")),
              "condition_parts_plan": {"plan_id": artifact+"-main", "policy_id": "condition-parts-v2-w3t1-equal100-v1", "virtual_only": True,
                  "tickets": tickets, "status": "priced" if all(t["observed_odds"] is not None for t in tickets) else "pending_prices", "reference_stake_yen": 400},
              "sql_saved": False, "automatic_evaluation_connected": False, "purchase_yen": 0,
              "template_version": "condition-parts-output-v1"}
    result["presentation"] = render(result)
    save(args.output / "normalized-used-history.json", history)
    save(args.output / "prediction.json", result)
    (args.output / "presentation.md").write_text(result["presentation"], encoding="utf-8")
    require(read(args.output / "prediction.json") == result and
            (args.output / "presentation.md").read_text(encoding="utf-8") == result["presentation"], "live_file_readback")
    require(datetime.now(timezone.utc) < datetime.fromisoformat(card["start_at"]), "live_readback_after_post")
    sources = [dataset_path, Path(__file__), ROOT / "src/jra_srb/jra_graded_live.py",
               ROOT / "src/jra_srb/jra_graded_patterns.py", ROOT / "src/jra_srb/jra_conditions_refinement.py",
               ROOT / "src/jra_srb/jra_race_conditions.py", ROOT / "src/jra_srb/jra_conditions_stability.py",
               ROOT / "configs/research/race_conditions_elizabeth_v1.json",
               ROOT / "configs/research/graded_common_pattern_candidates_v1.json", *args.input.rglob("*.json"), *args.input.rglob("*.html")]
    save(args.output / "manifest.json", {"files": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
         "prediction_sha256": hashlib.sha256((args.output / "prediction.json").read_bytes()).hexdigest(), "file_readback_verified": True,
         "verified_at": datetime.now(timezone.utc).isoformat(), "sql_saved": False})
    print(json.dumps({"artifact_id": artifact, "top3": forecast["runners"][:3], "plan_status": result["condition_parts_plan"]["status"]}, ensure_ascii=False))


async def official(provider, url, path, cache=None):
    """公式JRADBのURLだけを取得し原文を保存する。成功原文は再利用する。"""
    parts = urlsplit(url)
    require(not parts.netloc or parts.hostname in ("www.jra.go.jp", "jra.go.jp"), "live_official_host")
    require(parts.path.startswith("/JRADB/access"), "live_official_path")
    if path.exists():
        return path.read_text(encoding="utf-8")
    if cache is not None and cache.is_file():
        html = cache.read_text(encoding="utf-8")
        path.write_text(html, encoding="utf-8")
        return html
    page = await provider.fetch_jradb(parts.path, parse_qs(parts.query)["CNAME"][0])
    path.write_text(page.content, encoding="utf-8")
    return page.content


def header_conditions(html):
    """JRA公式ヘッダーをSDK2006/2008/2009の確認済みコードへ変換する。"""
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one(".race_header")
    require(header is not None, "live_header_missing")
    name = header.select_one("h2 .race_name")
    require(name is not None, "live_header_name")
    image = header.select_one("h2 .grade_icon img")
    grade_text = unicodedata.normalize("NFKC", image.get("alt", "")) if image else ""
    for icon in name.select(".grade_icon"):
        icon.decompose()
    rule = unicodedata.normalize("NFKC", header.select_one(".type .rule").get_text("", strip=True)).replace(" ", "")
    weight = header.select_one(".type .weight").get_text("", strip=True)
    course = header.select_one(".type .course").get_text("", strip=True)
    grades = {"": "", "GI": "A", "GII": "B", "GIII": "C", "リステッド": "L"}
    require(grade_text in grades, "live_header_grade")
    prefix = "N" if "(国際)" in rule else "A" if "(混合)" in rule else "0"
    sex = "2" if "牝" in rule else "0"
    exchange = "4" if "(特指)" in rule else "1" if "(指定)" in rule else "3" if "[指定]" in rule else "0"
    remainder = rule
    for token in ("(国際)", "(混合)", "牝", "(指定)", "(特指)", "[指定]"):
        remainder = remainder.replace(token, "")
    require(not remainder and weight in ("ハンデ", "別定", "馬齢", "定量"), "live_header_rule")
    distance = re.search(r"([0-9,]+)\s*メートル", course)
    require(distance is not None, "live_header_distance")
    require("ダート" in course or "芝" in course, "live_header_surface")
    track = ("23" if "左" in course else "24") if "ダート" in course else ("11" if "左" in course else "18" if "外" in course else "17")
    return {"race_name": name.get_text("", strip=True), "grade": grades[grade_text],
            "symbol": prefix+sex+exchange, "weight_rule": {"ハンデ": "1", "別定": "2", "馬齢": "3", "定量": "4"}[weight],
            "distance_raw": distance[1].replace(",", ""), "track_code": track,
            "conditions_verified": True, "raw_rule": rule, "raw_course": course}


def recent_comparisons(runner, history):
    """未出走の完全な空欄だけを除外し、実出走の近走を照合する。"""
    rows = runner["official_recent_races"]
    require(all(r.get("source_date") or not any(r.get(k) is not None for k in
                ("source_course", "distance", "finish_rank", "field_size")) for r in rows), "live_partial_recent_date")
    return compare_recent({**runner, "official_recent_races": [r for r in rows if r.get("source_date")]}, history)


async def collect(args):
    """最大18頭の全掲載履歴を照合し、必要な過去競走条件だけを補完する。"""
    folder = args.output
    folder.mkdir(parents=True, exist_ok=False)
    provider = HttpProvider(retries=0, min_interval_seconds=1)
    rule = SERIES[args.series]
    course = "tokyo" if args.series == "musashino" else "kyoto"
    with httpx.Client(base_url=args.api_base, timeout=30) as client:
        response = client.get(f"/meetings/{args.date}/{course}/races/11/card", params={"refresh": "true"})
        response.raise_for_status()
        api = response.json()
    save(folder / "official-card.json", api)
    require(api["race_name"] == rule["name"] and api["data_status"]["runner_set"] == "complete"
            and api["data_status"]["source_kind"] == "pre_race_card", "live_card_quality")
    post = datetime.fromisoformat(args.date+"T"+api["start_time"].replace("時", ":").replace("分", "")+":00+09:00")
    require(datetime.now(timezone.utc) < post, "live_collect_after_post")
    raw = await official(provider, api["source"], folder / "card-source.html")
    soup = BeautifulSoup(raw, "html.parser")
    runners, profiles, audits = [], [], []
    (folder / "profiles").mkdir()
    for row in api["runners"]:
        if row["status"] != "active":
            continue
        links = {a["href"] for a in soup.find_all("a", href=True) if a.get_text("", strip=True) == row["horse_name"]
                 and re.search(r"pw01dud00\d{10}/", a["href"])}
        require(len(links) == 1, "live_profile_link_"+row["horse_no"])
        href = next(iter(links))
        hid = re.search(r"pw01dud00(\d{10})/", href)[1]
        cached = args.cache / "profiles" / (hid+".html") if args.cache else None
        html = await official(provider, href, folder / "profiles" / (hid+".html"), cached)
        require(row["horse_name"] in BeautifulSoup(html, "html.parser").get_text(), "live_profile_name")
        history = parse_history(html, hid, args.date)
        recent_rows = row["official_recent_races"]
        comparisons = recent_comparisons(row, history)
        save(folder / "profiles" / (hid+".json"), history)
        require(history and all(c["status"] == "matched" for c in comparisons), "live_recent_mismatch_"+row["horse_no"])
        age_sex = re.fullmatch(r"(牡|牝|せん|セ|騸)(\d+)/.+", row["sex_age"])
        require(age_sex is not None, "live_card_sex_age")
        domestic = [h for h in history if h["race_key"]]
        require(bool(domestic), "live_no_domestic_history")
        runners.append({"horse_no": horse_number(row["horse_no"]), "horse_id": hid, "horse_name": row["horse_name"],
                        "age": int(age_sex[2]), "sex": {"牡": "1", "牝": "2", "せん": "3", "セ": "3", "騸": "3"}[age_sex[1]],
                        "frame_no": int(row["frame_no"]), "weight_carried": float(row["weight_carried"].split()[0]),
                        "status": "active", "latest_race_date": max(h["race_date"] for h in domestic)})
        profiles.extend(history)
        audits.append({"horse_no": row["horse_no"], "horse_id": hid, "horse_name": row["horse_name"],
                       "recent_comparisons": comparisons, "empty_card_slots": len(recent_rows)-len(comparisons), "profile_rows": len(history),
                       "latest_profile_race": history[0]["race_date"], "latest_jra_race": runners[-1]["latest_race_date"]})
        print(json.dumps({"horse_no": row["horse_no"], "profiles": len(history), "recent_matched": len(comparisons)}), flush=True)
    save(folder / "profile-history.json", profiles)
    save(folder / "input-audit.json", audits)
    domestic = [h for h in profiles if h["race_key"]]
    require(not any(h["venue_name"] in {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}
                    and h["race_key"] is None for h in profiles), "live_unresolved_JRA_history")
    keys = sorted({h["race_key"] for h in domestic})
    require(len(keys) <= 400, "live_history_limit")
    config = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    definition = next(c for c in read(ROOT / "configs/research/graded_common_pattern_candidates_v1.json")["candidates"] if c["id"] == "frozen_v2")
    require(definition["group_weights"] == [1]*5 and definition["score_scale"] == 4
            and definition["shrinkage"] == 20 and definition["cap"] == .05
            and definition["cap_baseline"] == "balanced_scale1" and definition["quality_definition"] is True,
            "live_frozen_config_changed")
    metadata = {}
    with ConditionsReader(config) as reader:
        save(folder / "sql-preflight.json", reader.preflight())
        conditions, audit = reader.race_conditions(set(keys))
        for start in range(0, len(keys), 64):
            chunk = keys[start:start+64]
            values = ",".join("(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))" for _ in chunk)
            params = [v for key in chunk for v in (hashlib.sha256(key.encode("utf-16le")).digest(), key)]
            rows = reader.rows("graded_live:metadata", "SELECT r.race_key,r.retrospective_metadata_json metadata FROM history.races r "
                "JOIN (VALUES "+values+") k(h,key_value) ON r.__unified_race_sha256=k.h AND r.race_key=k.key_value "
                "WHERE r.__migration_source_snapshot_id=31", params, 64)
            metadata.update({r["race_key"]: json.loads(r["metadata"]) for r in rows})
    save(folder / "ra-audit.json", audit)
    save(folder / "ra-conditions.json", conditions)
    normalized = []
    for key in keys:
        example = next(h for h in domestic if h["race_key"] == key)
        if key not in metadata or key not in conditions:
            html = await official(provider, example["source_url"], folder / (key+"-source.html"))
            fields = header_conditions(html)
        else:
            fields = {**conditions[key], "race_name": metadata[key]["race_name"], "conditions_verified": True}
        for h in (r for r in domestic if r["race_key"] == key):
            require(h["distance"] == int(fields["distance_raw"]) and h["weight_carried"] is not None, "live_past_distance_weight")
            normalized.append({"race_key": key, "race_date": h["race_date"], "race_name": fields["race_name"],
                               "venue_code": key[8:10], "distance": h["distance"], "track_code": fields["track_code"],
                               "horse_id": h["horse_id"], "rank": h["rank"], "weight_carried": h["weight_carried"],
                               "status": "excluded" if h["rank_raw"] in ("取消", "除外") else "active",
                               "ra_verified": key in conditions, "conditions_verified": True,
                               **{k: fields[k] for k in ("grade", "symbol", "weight_rule")}})
    save(folder / "normalized-history.json", normalized)
    save(folder / "excluded-non-jra-history.json", [h for h in profiles if not h["race_key"]])
    current = header_conditions(raw)
    card = {"race_key": api["race_id"], "race_date": args.date, "race_name": rule["name"], "venue_code": rule["venue"],
            "distance": int(api["distance"].replace(",", "")), "track_code": current["track_code"], "runners": runners,
            "observed_at": api["fetched_at"], "start_at": args.date+"T"+api["start_time"].replace("時", ":").replace("分", "")+":00+09:00"}
    save(folder / "normalized-card.json", card)
    save(folder / "collection-complete.json", {"series": args.series, "runners": len(runners), "history_rows": len(normalized),
                                              "completed_at": datetime.now(timezone.utc).isoformat()})


def main():
    """取得と予想を分離し、失敗を証跡へ残して依存処理を停止する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "predict"))
    parser.add_argument("--series", choices=tuple(SERIES), required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--cache", type=Path, help="成功済み公式馬別原文だけを再利用する旧取得フォルダー")
    parser.add_argument("--research-env-file", type=Path, help="既存の読取専用研究接続設定。秘密値は表示・コピーしない")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if args.research_env_file:
        os.environ["JRA_SRB_RESEARCH_ENV_FILE"] = str(args.research_env_file.resolve())
    try:
        if args.command == "collect":
            asyncio.run(collect(args))
        else:
            require(args.input is not None, "live_input_required")
            predict(args)
    except Exception as error:
        if args.output.is_dir():
            save(args.output / "failure.json", {"stage": args.command, "type": type(error).__name__,
                "reason": getattr(error, "reason", str(error) if isinstance(error, (ValueError, NotImplementedError)) else "execution_failed")})
        raise


if __name__ == "__main__":
    main()
