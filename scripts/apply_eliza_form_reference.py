"""概要: 女王杯の固定事前予想に、非採用の追加条件比較と公式資料の参照を添付する。
作成日: 2026-11-15
入力: --prediction、照合済み公式資料export、既存dataset・4候補検証成果物。
出力: --outputの新規フォルダーへ比較JSON・公式参照JSON・manifest。
実行例: uv run python scripts/apply_eliza_form_reference.py --prediction artifacts/jra_research/elizabeth_live_20261115_reference_v1 --output artifacts/jra_research/elizabeth_live_20261115_supplement_v1
注意事項: 通信・DB更新・実購入なし。元予想を変更せず、新条件の成績優位も主張しない。
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from run_jra_form_parts import ROOT, BASE, add_parts, part_config, read
from run_jra_miss_refinement import predict
from jra_srb.jra_graded_patterns import build_examples
from jra_srb.jra_race_conditions import load_config
from run_jra_graded_live import table, jst


def save(path, value):
    """新規UTF-8 JSONへ保存し、読み戻した値を照合する。"""
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text + "\n")
    assert read(path) == value


def official_reference(card, dataset):
    """開催と馬番で既存IDを特定し、属性・結果を照合した資料だけを参照へ返す。

    Args:
        card: 馬IDが照合済みの当日カード。
        dataset: 既存の同名重賞と過去走。
    Returns:
        全33頭の照合と当日ID一致馬の根拠・ラップを保持した参照データ。
    Raises:
        AssertionError: 属性不一致、欠測状態不一致、照合数不一致。
    Notes:
        馬名だけでは結合しない。未公表値はNULLのまま保持する。
    """
    links, current, laps = [], [], []
    today = {r["horse_id"]: r for r in card["runners"]}
    count = 0
    for day in ("2024-11-10", "2025-11-16"):
        document = read(BASE / "eliza_official_20261115_export" / (day + ".json"))
        edition = document["edition"]
        key = day.replace("-", "") + edition["venue_code"] + str(edition["race_no"]).zfill(2)
        race = next(r for r in dataset["races"] if r["race_key"] == key)
        records = document["records"]
        count += len(records)
        for record in records:
            values = json.loads(record["values_json"])
            fields = json.loads(record["fields_json"])
            for field in fields:
                assert field["review_state"] == "accepted"
                assert (field["value_state"] == "present") == (values[field["field_name"]] is not None)
            if record["record_kind"] != "runner_results":
                continue
            candidate = [h for h in race["runners"] if int(h["horse_no"]) == values["horse_no"]]
            assert len(candidate) == 1
            horse = candidate[0]
            assert horse["horse_name"] == record["horse_name_raw"]
            assert horse["sex"] == "2" and values["sex"] == "牝"
            assert horse["age"] == values["age"]
            assert horse["weight_carried"] == values["carried_weight_kg"]
            assert horse["rank"] == values["finish_rank"]
            link = dict(horse_id=horse["horse_id"], race_key=key, horse_no=values["horse_no"],
                        participant_id=record["participant_id"], record_id=record["record_id"])
            links.append(link)
            if horse["horse_id"] in today:
                relevant = [r for r in records if r["participant_id"] == record["participant_id"]]
                current.append(dict(current_horse_no=today[horse["horse_id"]]["horse_no"],
                                    horse_name=horse["horse_name"], source_race_date=day,
                                    observed_at=document["observed_at"], identity=link, records=relevant))
        intervals = sorted([r for r in records if r["record_kind"] == "race_sectionals"],
                           key=lambda r: json.loads(r["values_json"])["sequence_no"])
        values = [json.loads(r["values_json"]) for r in intervals]
        assert len(values) == 11 and all(v["timing_kind"] == "interval" for v in values)
        assert [(v["start_distance_m"], v["end_distance_m"]) for v in values] == [(i*200, (i+1)*200) for i in range(11)]
        laps.append(dict(race_date=day, intervals_seconds=[v["time_seconds"] for v in values],
                         first_1000_seconds=round(sum(v["time_seconds"] for v in values[:5]), 1),
                         last_1000_seconds=round(sum(v["time_seconds"] for v in values[-5:]), 1), records=intervals))
    assert len(links) == 33 and count == 258
    return dict(race_key=card["race_key"], records_count=count, verified_runner_links=links,
                matched_current_runners=current, race_laps=laps, used_in_probability=False,
                historical_availability="unknown", historical_prediction_snapshot_available=False,
                reason="2年分の参照資料。前年結果の機械的減点・係数学習・過去年の事前入力には使用しない")


def report(saved, reference, policy, comparisons, prediction_folder):
    """予想の採否理由と資料の利用範囲を、保存値から調査報告へまとめる。"""
    rows = []
    for horse in reference["matched_current_runners"]:
        facts = [(r, json.loads(r["values_json"])) for r in horse["records"]]
        result = next(v for r, v in facts if r["record_kind"] == "runner_results")
        ratings = {v["rating_kind"]: v["rating_value"] for r, v in facts if r["record_kind"] == "ratings"}
        corners = sorted([v for r, v in facts if r["record_kind"] == "runner_positions"], key=lambda v: v["corner_no"])
        rows.append([f"{int(horse['current_horse_no'])} {horse['horse_name']}", horse["source_race_date"],
                     result["finish_rank"], result["finish_time_seconds"], result["final_3f_seconds"],
                     "→".join(str(v["position_rank"]) for v in corners),
                     "欠測" if ratings.get("pre_rating") is None else ratings["pre_rating"],
                     ratings.get("race_performance", "欠測")])
    a, b = policy["selected"], policy["baseline"]
    return "\n\n".join([
        "# 2026-11-15 女王杯：追加部品と公式資料の検証",
        "結論：新DBは参照資料として利用可能。追加4条件案は採用基準未達のため、当日主案はfrozen_v2を維持した。精度改善や利益を確認できたとは扱わない。",
        "## 追加4パターン",
        table(["案", "追加部品", "本日上位3頭", "扱い"], [
            [c["mask"], ["追加なし", "直近3JRA走の3着内割合", "前年同名レースの着順", "両方"][c["mask"]],
             "・".join(str(int(r["horse_no"])) for r in c["prediction"]["runners"][:3]),
             "主案維持" if c["mask"] == 0 else "非採用の比較"] for c in comparisons]),
        f"3系列54開催×4案＝216予測。各年は以前の検証5開催以上だけで選抜。女王杯の時系列13開催ではBrier {b['brier']:.8f}→{a['brier']:.8f}、相対{policy['relative_improvement']:.3%}改善。8/13年改善だが1%基準に届かず、差の95%参考区間は{policy['interval']['interval95']}で0をまたぐ。最上位馬3着内は両方4/13。採用しない。繰り返し同期間で比較しているため探索的な検証である。",
        "## DB参照の範囲",
        "通常readerでjra_unified.official_materialsをSELECT。2年258件を保存し型付き値SHA一致を確認。全1751項目の確認状態と欠測整合を照合。開催・馬番・馬名・性別・年齢・斤量・着順から33頭の既存馬IDを照合し、当日18頭のうち下記3頭へ恒久IDで接続した。馬名だけの自動結合はしていない。",
        table(["当日馬", "資料年度", "着順", "時計秒", "上り3F秒", "通過順位", "事前評価", "結果評価"], rows),
        "上記の前年着順だけで今年の惨敗・好走は決めない。ケリフレッドアスクはv2で4位だが前年14着であり、市場との乖離も大きい。これは参照上の留保で、自動減点の係数は作っていない。ステレンボッシュの欠測評価も0にしない。",
        table(["年", "前半1000m秒", "後半1000m秒"], [[r["race_date"], r["first_1000_seconds"], r["last_1000_seconds"]] for r in reference["race_laps"]]),
        "ラップはレース全体の値であり、個々の馬の区間速度ではない。2年分から固有の展開適性や係数を確立しない。公開時点不明・歴史時点snapshot未作成のため、2024/25を予想し直す事前入力へは使わない。今年は取得確認済みの過去資料として参照する。",
        "## 本日の適用・保存",
        f"カード/取消：{jst(saved['final_card']['fetched_at'])}、オッズ：{jst(saved['odds']['fetched_at'])}。18頭・72近走一致、JRA履歴244件（非出走4件を集計外）、海外地方3走を別保存。馬場・馬体重・調教・仕上がりは係数へ未反映。11番175日間隔への懸念は残る。",
        f"予想artifact：{saved['artifact_id']}。主案はワイド3点＋3連複1点、各100円の仮想400円、実購入0円。SQL予想未保存、共通wide/trio自動評価未接続。固定10節の全頭評価・実価格・全買い目は [{prediction_folder.as_posix()}/presentation.md]({(prediction_folder/'presentation.md').resolve().as_posix()})。2026女王杯の結果は取得・参照していない。",
        "## 次の検証",
        "保存した主案を変更せず公式結果・払戻で精算する。新資料は同じ採用版・取得時刻で蓄積し、公開時点とID対応を揃えてから、事前評価・位置取り・ラップを一種類ずつ比較する。同じ過去への再調整とは別に未使用重賞での検証を優先する。",
    ]) + "\n"


def main():
    """基準予想と4部品案を別保存し、入力と出力のハッシュを固定する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    saved = read(args.prediction / "prediction.json")
    assert saved["generated_before_result"] and saved["outcome_reads"] == 0
    assert saved["card"]["race_name"] == "エリザベス女王杯"
    data = read(BASE / "elizabeth_conditions_v1_20261108_export_v4/dataset.json")
    history = read(args.prediction / "normalized-used-history.json")
    assert all(h["race_date"] < saved["card"]["race_date"] for h in history)
    original = build_examples(data, True)
    assert all(r["race_date"] < saved["card"]["race_date"] for r in original)
    target = {**{k: v for k, v in saved["card"].items() if k != "runners"}, "rows": saved["forecast"]["features"]}
    config = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    baseline = dict(runners=[{**r, "probability_top3": r["baseline_probability_top3"]} for r in saved["forecast"]["runners"]])
    comparisons = []
    for mask in range(4):
        prediction = predict(add_parts(original, data["history"], mask), add_parts([target], history, mask)[0],
                             baseline, part_config(config, mask), 0)
        comparisons.append(dict(mask=mask, adopted=mask == 0, prediction=prediction))
    expected = {r["horse_no"]: r["probability_top3"] for r in saved["forecast"]["runners"]}
    assert max(abs(r["probability_top3"]-expected[r["horse_no"]]) for r in comparisons[0]["prediction"]["runners"]) < 1e-12
    for comparison in comparisons:
        assert abs(sum(r["probability_top3"] for r in comparison["prediction"]["runners"])-3) < 1e-9
    summary = read(BASE / "form_parts_20261115_analysis/summary.json")
    assert not summary["policies"]["elizabeth"]["qualifies"]
    reference = official_reference(saved["card"], data)
    args.output.mkdir(parents=True)
    save(args.output / "official-reference.json", reference)
    save(args.output / "form-comparison.json", dict(reference_artifact_id=saved["artifact_id"],
         adopted_mask=0, adopted_new_features=False, historical_policy=summary["policies"]["elizabeth"], comparisons=comparisons))
    with (args.output / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(report(saved, reference, summary["policies"]["elizabeth"], comparisons, args.prediction))
    sources = [args.prediction / "prediction.json", args.prediction / "normalized-used-history.json",
               BASE / "form_parts_20261115_analysis/summary.json", Path(__file__), ROOT / "scripts/run_jra_form_parts.py",
               BASE / "elizabeth_conditions_v1_20261108_export_v4/dataset.json",
               *sorted((BASE / "eliza_official_20261115_export").glob("*.json")),
               ROOT / "scripts/run_jra_miss_refinement.py", ROOT / "configs/research/race_conditions_elizabeth_v1.json",
               args.output / "official-reference.json", args.output / "form-comparison.json", args.output / "report.md"]
    save(args.output / "manifest.json", dict(created_at=datetime.now(timezone.utc).isoformat(),
         reference_artifact_id=saved["artifact_id"], outcome_reads=0, database_writes=0,
         files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}))
    print(json.dumps(dict(official_records=reference["records_count"], safe_links=len(reference["verified_runner_links"]),
                         current_matches=[r["current_horse_no"] for r in reference["matched_current_runners"]],
                         retained="frozen_v2", comparison_count=len(comparisons)), ensure_ascii=False))


if __name__ == "__main__":
    main()
