"""概要: 保存済み女王杯カードを公式馬ID・全掲載成績と照合する。
作成日: 2026-11-13。
入力: --input API保存フォルダー、--dataset 既存研究JSON。
出力: 入力フォルダー内のprofiles原文、profile-history.json、input-audit.json。
実行例: uv run python scripts/audit_elizabeth_2026_inputs.py --input artifacts/jra_research/elizabeth_2026_api_audit --dataset artifacts/jra_research/elizabeth_conditions_v1_20261108_export_v4/dataset.json
注意事項: 公式馬別ページ最大18件に通信。保存原文は再利用。DB更新・結果取得・予想係数変更なし。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup
from jra_srb.provider import HttpProvider


def save_json(path: Path, value: object) -> None:
    """監査出力をUTF-8で保存する。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def integer(text: str) -> int | None:
    """純粋な整数のみ解釈し、中止等を未知として残す。"""
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


def parse_history(html: str, horse_id: str, cutoff_day: str) -> list[dict]:
    """公式馬別成績を見出しと日付で同定し、対象日以前の行を返す。

    Args:
        html: 公式馬別ページ原文。
        horse_id: 出馬表リンクから確認した恒久ID。
        cutoff_day: 当該競走日。同日以後の行があれば停止する。
    Returns:
        原表現・結果リンク・格の表現を保持した履歴。
    Raises:
        ValueError: 必須見出し・行構造・日付・キーが矛盾する場合。
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = [t for t in soup.find_all("table") if [h.get_text(" ", strip=True) for h in t.select("th")][:3] == ["年月日", "場", "レース名"]]
    if len(tables) != 1:
        raise ValueError("profile_history_table_not_unique")
    result = []
    for tr in tables[0].select("tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        texts = [c.get_text(" ", strip=True) for c in cells]
        if len(cells) != 14:
            raise ValueError("profile_history_column_count")
        match = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", texts[0])
        if not match:
            raise ValueError("profile_history_date_unknown")
        day = date(*map(int, match.groups())).isoformat()
        if day >= cutoff_day:
            raise ValueError("profile_history_future_or_target_result")
        link = cells[2].find("a", href=True)
        href = link["href"] if link else None
        race_key = None
        if href:
            identity = re.search(r"pw01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/", href)
            if identity:
                venue, year, _, _, race_no, compact_day = identity.groups()
                if compact_day != day.replace("-", "") or year != day[:4]:
                    raise ValueError("profile_result_link_date_mismatch")
                race_key = compact_day + venue + race_no
        grade_images = cells[2].select(".grade_icon img")
        grades = [image.get("alt", "") for image in grade_images]
        distance = re.fullmatch(r"(芝|ダート|ダ|障芝|障ダート|障)([0-9,]+)", texts[3])
        row = {"horse_id": horse_id, "race_date": day, "venue_name": texts[1],
               "race_name_raw": link.get_text(" ", strip=True) if link else texts[2],
               "race_key": race_key, "source_url": href, "grade_raw": grades,
               "surface_raw": distance[1] if distance else None,
               "distance": int(distance[2].replace(",", "")) if distance else None,
               "rank": integer(texts[7]), "rank_raw": texts[7], "field_size": integer(texts[5]),
               "weight_carried": float(texts[9]) if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", texts[9]) else None,
               "jockey": texts[8], "body_weight_raw": texts[10], "time_raw": texts[11],
               "rating_raw": texts[12], "raw_cells": texts}
        result.append(row)
    keys = [(r["race_date"], r["venue_name"], r["race_name_raw"]) for r in result]
    if len(set(keys)) != len(keys):
        raise ValueError("profile_duplicate_history")
    return sorted(result, key=lambda row: row["race_date"], reverse=True)


def compare_recent(runner: dict, history: list[dict]) -> list[dict]:
    """カード近走の日時・場・距離・着順・斤量を馬別ページへ照合する。"""
    comparisons = []
    for recent in runner["official_recent_races"]:
        matches = [h for h in history if h["race_date"] == recent["source_date"] and h["venue_name"] == recent["source_course"]]
        diffs = []
        if len(matches) == 1:
            for feature, key in (("distance", "distance"), ("finish_rank", "rank"), ("weight_carried", "weight_carried")):
                if recent.get(feature) != matches[0].get(key):
                    diffs.append({"field": feature, "card": recent.get(feature), "profile": matches[0].get(key)})
        comparisons.append({"date": recent["source_date"], "course": recent["source_course"],
                            "match_count": len(matches), "differences": diffs,
                            "status": "matched" if len(matches) == 1 and not diffs else "unresolved"})
    return comparisons


async def audit(folder: Path, dataset_path: Path) -> dict:
    """最大18頭の原文を有界取得し、カード・保存履歴との照合を保存する。

    Notes:
        既存原文は再利用する。取得・解析失敗は馬別に残し、同じURLを再試行しない。
    """
    response = json.loads((folder / "card-response.json").read_text(encoding="utf-8"))
    card = response["body"]
    assert response["http_status"] == 200 and card["race_id"] == "202611150811"
    assert len(card["runners"]) == 18 and len({r["horse_no"] for r in card["runners"]}) == 18
    links = json.loads((folder / "card-horse-links.json").read_text(encoding="utf-8"))
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    old = {(r["horse_id"], r["race_key"]): r for r in dataset["history"]}
    profile_folder = folder / "profiles"
    profile_folder.mkdir(exist_ok=True)
    provider = HttpProvider(retries=0, min_interval_seconds=1)
    history_all, audits = [], []
    for runner in card["runners"]:
        row = {"horse_no": runner["horse_no"], "horse_name": runner["horse_name"]}
        try:
            matching = [link for link in links if link["text"] == runner["horse_name"]]
            assert len(matching) == 1
            link = matching[0]
            identity = re.search(r"pw01dud00(\d{10})/", link["href"])
            assert identity
            horse_id = identity[1]
            row["horse_id"] = horse_id
            path = profile_folder / f"{horse_id}.html"
            if not path.exists():
                url = urlsplit(link["href"])
                page = await provider.fetch_jradb(url.path, parse_qs(url.query)["CNAME"][0])
                path.write_text(page.content, encoding="utf-8")
            html = path.read_text(encoding="utf-8")
            assert runner["horse_name"] in BeautifulSoup(html, "html.parser").get_text()
            history = parse_history(html, horse_id, "2026-11-15")
            assert all(h["race_date"] <= response["checked_at"][:10] for h in history)
            comparisons = compare_recent(runner, history)
            overlaps = [(h, old[(horse_id, h["race_key"])]) for h in history if (horse_id, h["race_key"]) in old]
            differences = [{"race_key": h["race_key"], "field": field, "profile": h[field], "stored": prior[field]}
                           for h, prior in overlaps for field in ("rank", "distance", "weight_carried") if h[field] != prior[field]]
            row.update(status="checked", profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                       profile_url="https://www.jra.go.jp" + link["href"], profile_rows=len(history),
                       latest_profile_race=history[0]["race_date"] if history else None,
                       latest_card_race=max((r["source_date"] for r in runner["official_recent_races"]), default=None),
                       recent_comparisons=comparisons, stored_overlap_count=len(overlaps),
                       stored_differences=differences, missing_race_key_count=sum(h["race_key"] is None for h in history),
                       missing_distance_count=sum(h["distance"] is None for h in history))
            history_all.extend(history)
        except Exception as error:
            row.update(status="failed", error_type=type(error).__name__, reason=str(error) if isinstance(error, ValueError) else "fetch_or_identity_failed")
        audits.append(row)
        print(json.dumps({k: row.get(k) for k in ("horse_no", "status", "profile_rows", "stored_overlap_count", "reason")}), flush=True)
    result = {"protocol": "elizabeth-2026-input-audit-v1", "checked_at": datetime.now(timezone.utc).isoformat(),
              "race_id": card["race_id"], "card_fetched_at": card["fetched_at"], "runners": audits,
              "summary": {"card_runners": len(audits), "checked_profiles": sum(a["status"] == "checked" for a in audits),
                          "profile_history_rows": len(history_all),
                          "recent_matched": sum(c["status"] == "matched" for a in audits for c in a.get("recent_comparisons", [])),
                          "recent_unresolved": sum(c["status"] != "matched" for a in audits for c in a.get("recent_comparisons", [])),
                          "stored_overlap_rows": sum(a.get("stored_overlap_count", 0) for a in audits),
                          "stored_difference_fields": sum(len(a.get("stored_differences", [])) for a in audits)},
              "limitations": ["当時の全履歴配信を証明せず、現在の公式掲載範囲の照合。", "近走とprofileは同じ公式系統で独立した別データ源ではない。",
                              "競走名は省略表記を含み、そのまま既存モデルへ入力しない。", "全履歴の競走条件とv2事前適用は別工程。"]}
    save_json(folder / "profile-history.json", history_all)
    save_json(folder / "input-audit.json", result)
    return result


def main() -> int:
    """指定された保存入力を監査し、馬別失敗があれば非0で終了する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(audit(args.input, args.dataset))
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0 if result["summary"]["checked_profiles"] == 18 else 4


if __name__ == "__main__":
    raise SystemExit(main())
