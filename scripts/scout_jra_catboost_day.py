"""概要：保存済みCatBoost v3で当日利用可能な通常戦を相対比較する。
作成日：2026-10-04
入力：対象日、保存済みモデル、SQLite、任意で未収集カードを逐次補完。
出力：時刻付きスカウトJSON、標準出力の分析件数・順位・欠損。
実行例：rtk uv run --with catboost python scripts/scout_jra_catboost_day.py --date 2026-10-04 --ranker-model model.cbm --fill-missing --max-fetches 5
注意事項：買い目は作成しない。外部取得は逐次実行・件数制限付き。保存カードから再開できる。
"""

from datetime import date, datetime, timezone, timedelta
import argparse
import json
from pathlib import Path

import httpx
from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.jra_day_race_scout import _race_card_from_snapshot
from jra_srb.jra_history_dataset import build_history_dataset
from jra_srb.jra_history_model import build_artifact_live_records, load_model_artifact
from jra_srb.jra_lap_style_dataset import append_lap_style_features
from jra_srb.models import RaceCard


JST = timezone(timedelta(hours=9))


def load_ranker(path):
    """推論時にだけ任意依存CatBoostを読み込み、保存済みモデルを復元する。"""
    from catboost import CatBoostRanker

    model = CatBoostRanker()
    model.load_model(str(path))
    return model


def checkpoint_card(card, output_dir):
    """取得カードを時刻付き新規ファイルへ保存し、途中終了時の再開点にする。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    name = "day_card_" + card.race_id + "_" + stamp + ".json"
    with (output_dir / name).open("x", encoding="utf-8", newline="\r\n") as stream:
        stream.write(card.model_dump_json(indent=2) + "\n")


def cached_card(race_id, observed, output_dir, max_age):
    """指定秒数以内に取得した再開用カードだけを再利用する。"""
    matches = sorted(output_dir.glob("day_card_" + race_id + "_*.json"))
    if not matches:
        return None
    card = RaceCard.model_validate_json(matches[-1].read_text(encoding="utf-8"))
    age = (observed - card.fetched_at).total_seconds()
    return card if 0 <= age < max_age and card.race_id == race_id else None


def main():
    """指定件数までの未収集カードを逐次補完し、通常戦を推論する。

    Notes:
        1回の取得件数と1リクエストの待ち時間を制限する。
        失敗はレース別に記録し、成功カードを保存して次の実行で再利用する。
        対象当日の結果はモデル特徴に使わない。スコア差を確率と呼ばない。
    """
    parser = argparse.ArgumentParser(description="CatBoost v3の逐次補完スカウト")
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--ranker-model", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--history-model", type=Path, default=Path("data/models/jra_history_recent_form_v2/model.json"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--cache-max-age", type=float, default=300, help="再開カードの有効秒数（既定300秒）")
    parser.add_argument("--fill-missing", action="store_true")
    parser.add_argument("--max-fetches", type=int, default=5)
    parser.add_argument("--request-timeout", type=float, default=20)
    args = parser.parse_args()
    if not 1 <= args.max_fetches <= 10 or not 1 <= args.request_timeout <= 60:
        parser.error("取得件数は1～10、タイムアウトは1～60秒")
    if args.cache_max_age < 0:
        parser.error("キャッシュ有効秒数は0以上")
    target, db = args.date, args.db
    output_dir = args.output_dir or Path("data/live/catboost_scout") / target.isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(timezone.utc)
    artifact = load_model_artifact(args.history_model)
    model = load_ranker(args.ranker_model)
    store = AnalysisSQLiteStore(db)
    client = httpx.Client(base_url=args.api_base, timeout=args.request_timeout)
    schedule_response = client.get("/search/races", params={"date": target.isoformat(), "limit": 100})
    schedule_response.raise_for_status()
    schedule = schedule_response.json()["items"]
    available = set(store.list_pre_race_race_ids(target))
    live, excluded, cards = [], [], {}
    fetches = 0
    for race in schedule:
        time_text = race.get("start_time", "").replace("時", ":").replace("分", "")
        hour, minute = [int(value) for value in time_text.split(":")]
        start = datetime.combine(target, datetime.min.time(), tzinfo=JST).replace(hour=hour, minute=minute)
        if start <= datetime.now(timezone.utc):
            excluded.append({**race, "reason": "発走済み"})
            continue
        if "新馬" in race["race_name"] or "メイクデビュー" in race["race_name"]:
            excluded.append({**race, "reason": "新馬戦：履歴モデルによる推薦対象外"})
            continue
        if "障害" in race["race_name"]:
            excluded.append({**race, "reason": "障害戦：今回の平地スカウト対象外"})
            continue
        card = cached_card(race["race_id"], datetime.now(timezone.utc), output_dir, args.cache_max_age)
        if card is not None:
            pass
        elif race["race_id"] in available:
            card = _race_card_from_snapshot(store.get_pre_race_snapshot(race["race_id"]))
        elif args.fill_missing and fetches < args.max_fetches:
            fetches += 1
            try:
                response = client.get(f"/meetings/{target}/{race['course']}/races/{race['race_no']}/card")
                response.raise_for_status()
                card = RaceCard.model_validate(response.json())
                if card.race_id != race["race_id"]:
                    raise ValueError("出馬表のレースIDが不一致")
                checkpoint_card(card, output_dir)
                print("CARD_SAVED " + race["race_id"], flush=True)
            except (httpx.HTTPError, ValueError, AssertionError) as exc:
                excluded.append({**race, "reason": "取得失敗：" + type(exc).__name__})
                continue
        else:
            excluded.append({**race, "reason": "今回の取得範囲外：次バッチで補完"})
            continue
        if start <= datetime.now(timezone.utc):
            excluded.append({**race, "reason": "取得中に発走"})
            continue
        records = build_artifact_live_records(artifact, db, target_date=target, course=race["course"], card=card)
        if len(records) < 2 or any(len(r["features"]) != 49 for r in records):
            raise ValueError("直近成績特徴量49列・出走馬2頭以上が必要")
        cards[card.race_id] = {"race": race, "card": card.model_dump(mode="json")}
        live.extend(records)
    client.close()
    history, _ = build_history_dataset(db, through_date=target - timedelta(days=1)) if live else ([], {})
    history = [{**r, "features": [0.0]*49} for r in history]
    featured, _ = append_lap_style_features([*history, *live], db) if live else ([], {})
    today = [r for r in featured if r["race_date"] == target.isoformat()]
    if any(len(r["features"]) != 65 for r in today):
        raise ValueError("ラップ追加後の特徴量65列が必要")
    scores = model.predict([r["features"] for r in today]) if today else []
    grouped = {}
    for row, score in zip(today, scores, strict=True):
        grouped.setdefault(row["race_id"], []).append({"horse_no": row["horse_no"], "horse_name": row["horse_name"], "score": float(score)})
    entries = []
    for race_id, rows in grouped.items():
        rows.sort(key=lambda r: (-r["score"], int(r["horse_no"])))
        item = cards[race_id]
        prices = {r["horse_no"]: r.get("odds") for r in item["card"]["runners"]}
        entries.append({**item["race"], "ranking": rows, "ranker_score_gap": rows[0]["score"]-rows[1]["score"],
            "top_win_odds": prices.get(rows[0]["horse_no"]), "card_fetched_at": item["card"]["fetched_at"],
            "weather": item["card"].get("weather_label"), "track": item["card"].get("track_condition_label")})
    entries.sort(key=lambda r: -r["ranker_score_gap"])
    incomplete = [r for r in excluded if "取得範囲外" in r["reason"] or "取得失敗" in r["reason"]]
    output = {"date": target.isoformat(), "observed_at": observed.isoformat(), "model": "catboost_pairwise_ranker_recent_lap_v3",
        "ranker_model": str(args.ranker_model), "history_model": str(args.history_model),
        "schedule_count": len(schedule), "analyzed_count": len(entries), "status": "partial" if incomplete else "completed",
        "fetches": fetches, "remaining": len(incomplete),
        "entries": entries, "excluded": excluded, "cards": cards,
        "limitations": ["スコア差のレース間比較は未校正", "最新共同確率モデルS06/S08とV91Bは未使用"]}
    name = "day_scout_" + observed.strftime("%Y%m%dT%H%M%S%fZ") + ".json"
    with (output_dir / name).open("x", encoding="utf-8", newline="\r\n") as stream:
        stream.write(json.dumps(output, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({**{k:v for k,v in output.items() if k not in ["cards", "entries"]},
        "entries": [{**{k:v for k,v in r.items() if k != "ranking"}, "top3":r["ranking"][:3]} for r in entries]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
