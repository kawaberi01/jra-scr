from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


COURSE_LABELS = {
    "sapporo": "札幌",
    "hakodate": "函館",
    "fukushima": "福島",
    "niigata": "新潟",
    "tokyo": "東京",
    "nakayama": "中山",
    "chukyo": "中京",
    "kyoto": "京都",
    "hanshin": "阪神",
    "kokura": "小倉",
}

REASON_LABELS = {
    "skipped_started": "発走済み",
    "time_budget_exceeded": "時間制限超過",
    "meeting_coordinates_unavailable": "開催情報不足",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JRA全レースの相対確度を固定Markdownで出力する"
    )
    parser.add_argument("--date", required=True, help="対象日 YYYY-MM-DD")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=65.0)
    parser.add_argument(
        "--graded-race",
        action="append",
        default=[],
        metavar="COURSE,RACE_NO,GRADE,NAME",
    )
    parser.add_argument(
        "--official-source", action="append", default=[], metavar="LABEL=URL"
    )
    parser.add_argument(
        "--from-db",
        type=Path,
        help="API応答を失った場合に同日の最新保存結果を読む調査用オプション",
    )
    return parser.parse_args()


def fetch_api(api_base: str, target_date: str, timeout: float) -> dict[str, Any]:
    query = urlencode(
        {
            "max_candidates": 10,
            "refresh": "false",
            "max_concurrency": 3,
            "mode": "quick",
            "time_budget_seconds": 45,
        }
    )
    url = f"{api_base.rstrip('/')}/jra/days/{target_date}/race-scout?{query}"
    request = Request(url, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"API接続失敗: {exc.reason}") from exc


def load_latest_db(db_path: Path, target_date: str) -> dict[str, Any]:
    if not db_path.is_file():
        raise RuntimeError(f"SQLiteが見つかりません: {db_path}")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            """
            select * from jra_scout_runs
            where race_date = ?
            order by observed_at desc
            limit 1
            """,
            (target_date,),
        ).fetchone()
        if run is None:
            raise RuntimeError(f"保存済みスカウト結果がありません: {target_date}")
        entry_rows = conn.execute(
            "select entry_json from jra_scout_entries where run_id = ?",
            (run["run_id"],),
        ).fetchall()
    return {
        "run_id": run["run_id"],
        "date": run["race_date"],
        "observed_at": run["observed_at"],
        "status": run["status"],
        "race_count": run["race_count"],
        "analyzed_count": run["analyzed_count"],
        "candidates": json.loads(run["candidates_json"]),
        "entries": [json.loads(row["entry_json"]) for row in entry_rows],
        "errors": json.loads(run["errors_json"]),
    }


def parse_graded_races(values: list[str]) -> list[dict[str, Any]]:
    result = []
    for value in values:
        parts = [part.strip() for part in value.split(",", 3)]
        if len(parts) != 4 or not parts[1].isdigit():
            raise RuntimeError(
                f"--graded-race は COURSE,RACE_NO,GRADE,NAME 形式です: {value}"
            )
        result.append(
            {
                "course": parts[0].lower(),
                "race_no": int(parts[1]),
                "race_grade": parts[2],
                "race_name": parts[3],
            }
        )
    return result


def parse_sources(values: list[str]) -> list[tuple[str, str]]:
    result = []
    for value in values:
        if "=" not in value:
            raise RuntimeError(f"--official-source は LABEL=URL 形式です: {value}")
        label, url = value.split("=", 1)
        if not label.strip() or not url.startswith(("https://", "http://")):
            raise RuntimeError(f"公式情報の指定が不正です: {value}")
        result.append((label.strip(), url.strip()))
    return result


def gap_value(entry: dict[str, Any]) -> float | None:
    signal = entry.get("confidence_signal") or {}
    value = signal.get("history_probability_gap")
    return float(value) if value is not None else None


def start_time_key(value: Any) -> tuple[int, int]:
    if not value:
        return (99, 99)
    try:
        normalized = str(value).replace("時", ":").replace("分", "")
        hour, minute = normalized.split(":", 1)
        return (int(hour), int(minute))
    except (TypeError, ValueError):
        return (99, 99)


def entry_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    gap = gap_value(entry)
    return (
        -(gap if gap is not None else float("-inf")),
        start_time_key(entry.get("start_time")),
        entry.get("race_id") or "",
    )


def md(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def race_label(entry: dict[str, Any]) -> str:
    course = COURSE_LABELS.get(entry.get("course"), entry.get("course") or "不明")
    race_no = entry.get("race_no")
    return f"{course}{race_no}R" if race_no else course


def reason_text(entry: dict[str, Any]) -> str:
    reasons = [
        REASON_LABELS.get(str(item), str(item))
        for item in entry.get("reasons") or []
        if item
    ]
    return " / ".join(reasons) if reasons else "理由なし"


def observed_at_text(value: Any) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return str(value)
        jst = timezone(timedelta(hours=9), name="JST")
        return parsed.astimezone(jst).strftime(
            "%Y-%m-%d %H:%M:%S JST"
        )
    except ValueError:
        return str(value)


def source_summary(entries: list[dict[str, Any]]) -> str:
    statuses = Counter()
    for entry in entries:
        component = entry.get("component_status") or {}
        statuses[(component.get("card"), component.get("odds"))] += 1
    if not statuses:
        return "判定不能"
    if all(card == "local_db" and odds == "local_db" for card, odds in statuses):
        return "ローカルDB（出馬表・単勝オッズ）"
    if all(odds == "card_odds" for _, odds in statuses):
        return "クイック取得（出馬表内単勝オッズ）"
    return "混在（各行のAPI component_statusに準拠）"


def render(
    payload: dict[str, Any],
    graded_races: list[dict[str, Any]],
    official_sources: list[tuple[str, str]],
) -> str:
    entries = list(payload.get("entries") or [])
    analyzed = sorted(
        (entry for entry in entries if entry.get("grade") != "X"),
        key=entry_sort_key,
    )
    excluded = sorted(
        (entry for entry in entries if entry.get("grade") == "X"),
        key=lambda entry: (
            start_time_key(entry.get("start_time")),
            entry.get("race_id") or "",
        ),
    )
    ranks = {
        (entry.get("course"), entry.get("race_no")): rank
        for rank, entry in enumerate(analyzed, 1)
    }
    by_race = {
        (entry.get("course"), entry.get("race_no")): entry for entry in entries
    }

    lines = [
        "# JRA全レース相対確度",
        "",
        "## 実行状況",
        "",
        f"- 対象日: {md(payload.get('date'))}",
        f"- 観測時刻: {md(observed_at_text(payload.get('observed_at')))}",
        f"- 状態: {md(payload.get('status'))}",
        f"- 分析済み: {len(analyzed)}/{md(payload.get('race_count'))}レース",
        f"- データ経路: {source_summary(analyzed)}",
        "",
        "## 相対確度ランキング",
        "",
        "| 順位 | 競馬場・R | レース名 | 発走 | 相対確度差 | 評価 | S/V | 再確認 |",
        "| ---: | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    if analyzed:
        for rank, entry in enumerate(analyzed, 1):
            gap = gap_value(entry)
            gap_text = f"{gap:.6f}" if gap is not None else "—"
            signals = ",".join(entry.get("signals") or []) or "—"
            recheck = "要" if entry.get("recheck_required", True) else "不要"
            lines.append(
                f"| {rank} | {md(race_label(entry))} | {md(entry.get('race_name'))} | "
                f"{md(entry.get('start_time'))} | {gap_text} | {md(entry.get('grade'))} | "
                f"{md(signals)} | {recheck} |"
            )
    else:
        lines.append("| — | — | 分析済みレースなし | — | — | — | — | — |")

    lines.extend(
        [
            "",
            "## 重賞",
            "",
            "| 競馬場・R | 重賞 | 発走 | 全体順位 | 相対確度差 | 状態 |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    if graded_races:
        for graded in graded_races:
            key = (graded["course"], graded["race_no"])
            entry = by_race.get(key)
            title = f"{graded['race_name']}（{graded['race_grade']}）"
            if entry is None:
                course = COURSE_LABELS.get(graded["course"], graded["course"])
                lines.append(
                    f"| {md(course)}{graded['race_no']}R | {md(title)} | — | — | — | "
                    "API entriesになし |"
                )
                continue
            if entry.get("grade") == "X":
                lines.append(
                    f"| {md(race_label(entry))} | {md(title)} | {md(entry.get('start_time'))} | — | — | "
                    f"未分析（{md(reason_text(entry))}） |"
                )
                continue
            gap = gap_value(entry)
            gap_text = f"{gap:.6f}" if gap is not None else "—"
            lines.append(
                f"| {md(race_label(entry))} | {md(title)} | {md(entry.get('start_time'))} | "
                f"{ranks.get(key, '—')} | {gap_text} | 分析済み・評価{md(entry.get('grade'))} |"
            )
    else:
        lines.append("| — | JRA公式日程で未確認 | — | — | — | 推測しない |")

    if official_sources:
        source_links = "、".join(f"[{md(label)}]({url})" for label, url in official_sources)
        lines.extend(["", f"公式確認: {source_links}"])

    lines.extend(
        [
            "",
            "## 未分析・除外",
            "",
            "| 競馬場・R | レース名 | 発走 | 理由 |",
            "| --- | --- | --- | --- |",
        ]
    )
    if excluded:
        for entry in excluded:
            lines.append(
                f"| {md(race_label(entry))} | {md(entry.get('race_name'))} | "
                f"{md(entry.get('start_time'))} | {md(reason_text(entry))} |"
            )
    else:
        lines.append("| — | なし | — | — |")

    errors = payload.get("errors") or []
    if errors:
        lines.extend(["", "APIエラー:"])
        for error in errors:
            scope = error.get("race_id") or error.get("component") or "不明"
            error_type = error.get("error_type") or "unknown"
            message = error.get("message") or ""
            lines.append(f"- {md(scope)}: {md(error_type)} {md(message)}")

    lines.extend(
        [
            "",
            "## 読み方",
            "",
            "- 相対確度差は履歴モデル1位と2位の推定勝率差であり、的中確率そのものではありません。",
            "- 順位は同一実行内の比較です。評価CやS/Vなしは、他材料との一致が確認できていない状態です。",
            "- この表は買う・見送るの判断や買い目を示しません。個別予想では直前オッズと不足材料を再確認します。",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    try:
        date.fromisoformat(args.date)
        graded_races = parse_graded_races(args.graded_race)
        official_sources = parse_sources(args.official_source)
        payload = (
            load_latest_db(args.from_db, args.date)
            if args.from_db
            else fetch_api(args.api_base, args.date, args.timeout)
        )
        print(render(payload, graded_races, official_sources))
        return 0
    except (RuntimeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print("# JRA全レース相対確度")
        print("\n## 実行状況\n")
        print(f"- 対象日: {args.date}")
        print("- 状態: unavailable")
        print(f"- 理由: {md(exc)}")
        print("\n## 相対確度ランキング\n\n取得できませんでした。")
        print("\n## 重賞\n\n確認できませんでした。")
        print("\n## 未分析・除外\n\n確認できませんでした。")
        print("\n## 読み方\n")
        print("- APIまたは保存済みデータが利用可能になってから再実行します。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
