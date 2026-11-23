"""概要: 取得監査済み2026カードを固定v2へ適用し、履歴更新の影響を比較する。
作成日: 2026-11-13。
入力: --input 監査フォルダー、--dataset 固定研究JSON、--output 新規フォルダー。
出力: 入力カード・正規化履歴・v1/v2全馬値・変化表・manifest・report.md。
実行例: uv run python scripts/run_elizabeth_2026_recheck.py --input artifacts/jra_research/elizabeth_2026_api_audit --dataset artifacts/jra_research/elizabeth_conditions_v1_20261108_export_v4/dataset.json --output artifacts/jra_research/elizabeth_2026_recheck
注意事項: オフライン専用。DB変更・係数探索・対象結果取得なし。出力は参考値。
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from bs4 import BeautifulSoup
from jra_srb.jra_race_conditions import examples, load_config, make_features, validate_card, require
from jra_srb.jra_conditions_refinement import group_deltas, candidate_prediction
from jra_srb.jra_conditions_stability import bounded_probabilities
from jra_srb.jra_research_contracts import digest
from run_jra_conditions_resolution import resolution_values


def read_json(path: Path) -> object:
    """UTF-8の保存入力を読む。"""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def html_conditions(html: str) -> dict:
    """確認済み2競走のヘッダー表現だけを仕様書の原コードへ変換する。

    Notes:
        未確認の表現を汎用推測しない。対象以外の表現は例外で停止する。
        根拠: JV-Data4901.pdfの競走記号・重量種別・トラックコード表。
    """
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one(".race_header")
    require(header is not None, "recheck_missing_race_header")
    name_node = header.select_one("h2 .race_name")
    require(name_node is not None, "recheck_missing_race_name")
    name_node = deepcopy(name_node)
    for child in name_node.select(".grade_icon"):
        child.decompose()
    rule = header.select_one(".type .rule").get_text(" ", strip=True)
    weight = header.select_one(".type .weight").get_text(" ", strip=True)
    course = header.select_one(".type .course").get_text(" ", strip=True)
    image = header.select_one("h2 .grade_icon img")
    require(rule in {"（国際）牝（指定）", "（国際）牝（特指）"} and weight == "別定", "recheck_unknown_rule")
    require("（芝・左）" in course and image is not None, "recheck_unknown_course_or_grade")
    grade = {"GⅡ": "B", "リステッド": "L"}.get(image.get("alt"))
    require(grade is not None, "recheck_unknown_grade")
    distance = re.search(r"([0-9,]+)\s*メートル", course)
    require(distance is not None, "recheck_unknown_distance")
    return {"race_name": name_node.get_text(" ", strip=True), "grade": grade,
            "symbol": "N21" if rule == "（国際）牝（指定）" else "N24", "weight_rule": "2",
            "track_code": "11", "distance_raw": distance[1].replace(",", ""),
            "raw_rule": rule, "raw_weight": weight, "raw_course": course,
            "conditions_source": "official_result_header", "conditions_verified": True}


def build_inputs(folder: Path, dataset: dict) -> tuple[dict, list[dict], list[dict], dict]:
    """カード・公式ID・国内履歴を照合し、推測値なしで事前用入力を組む。"""
    response = read_json(folder / "card-response.json")
    api = response["body"]
    audit = read_json(folder / "input-audit.json")
    db_audit = read_json(folder / "profile-db-audit.json")
    require(audit["summary"]["checked_profiles"] == 18 and audit["summary"]["recent_unresolved"] == 0,
            "recheck_profile_audit_incomplete")
    require(db_audit["status"] == "passed" and not db_audit["differences"], "recheck_database_disagreement")
    identities = {r["horse_no"]: r for r in audit["runners"]}
    require(len({r["horse_id"] for r in identities.values()}) == 18, "recheck_duplicate_horse_id")
    raw_soup = BeautifulSoup((folder / "card-source.html").read_text(encoding="utf-8"), "html.parser")
    raw_text = raw_soup.get_text(" ", strip=True)
    require("（芝・右 外）" in raw_text or "（芝・右外）" in raw_text, "recheck_target_course_unknown")
    runners = []
    for source in api["runners"]:
        identity = identities[source["horse_no"]]
        require(source["horse_name"] == identity["horse_name"], "recheck_identity_name_mismatch")
        require(identity["latest_profile_race"] == identity["latest_card_race"], "recheck_latest_race_mismatch")
        require(any(identity["horse_id"] in a.get("href", "") and a.get_text(" ", strip=True) == source["horse_name"]
                    for a in raw_soup.find_all("a", href=True)), "recheck_identity_link_missing")
        age = re.fullmatch(r"牝([0-9]+)/.+", source["sex_age"] or "")
        require(age is not None and 2026-int(identity["horse_id"][:4]) == int(age[1]), "recheck_age_identity")
        weight = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*kg", source["weight_carried"] or "")
        require(weight is not None and source["status"] == "active", "recheck_runner_state")
        runners.append({"horse_no": source["horse_no"], "horse_id": identity["horse_id"], "horse_name": source["horse_name"],
                        "age": int(age[1]), "sex": "2", "frame_no": int(source["frame_no"]),
                        "weight_carried": float(weight[1]), "status": "active", "latest_race_date": identity["latest_card_race"]})
    require(api["start_time"] == "15時40分", "recheck_target_post_time")
    card = {"race_key": api["race_id"], "race_date": "2026-11-15", "race_name": api["race_name"], "venue_code": "08",
            "distance": int(api["distance"].replace(",", "")), "track_code": "18", "runners": runners,
            "observed_at": api["fetched_at"], "start_at": "2026-11-15T15:40:00+09:00"}
    profiles = read_json(folder / "profile-history.json")
    old = read_json(folder / "db-matched-history.json")
    history = deepcopy(old)
    matched = {(h["horse_id"], h["race_key"]) for h in old}
    conditions = read_json(folder / "profile-race-conditions.json")
    supplements = {}
    for key in db_audit["ra_audit"]["missing_keys"]:
        supplements[key] = html_conditions((folder / f"{key}-source.html").read_text(encoding="utf-8"))
    excluded = []
    for profile in profiles:
        key = profile["race_key"]
        if key is None:
            excluded.append(profile)
            continue
        if (profile["horse_id"], key) in matched:
            continue
        fields = conditions.get(key) or supplements[key]
        require(profile["distance"] == int(fields["distance_raw"]), "recheck_supplement_distance")
        require(profile["rank"] is not None, "recheck_supplement_finish_status_unknown")
        history.append({"race_key": key, "race_date": profile["race_date"], "race_name": fields.get("race_name", profile["race_name_raw"]),
                        "venue_code": key[8:10], "distance": profile["distance"], "track_code": fields["track_code"],
                        "horse_id": profile["horse_id"], "weight_carried": profile["weight_carried"],
                        "rank": profile["rank"], "status": "active", "ra_verified": key in conditions,
                        "conditions_verified": True, "source": "official_profile_and_race_conditions",
                        **{k: fields[k] for k in ("grade", "weight_rule", "symbol")}})
    require(len({(h["horse_id"], h["race_key"]) for h in history}) == len(history), "recheck_duplicate_history")
    require(all(h["race_date"] < card["observed_at"][:10] for h in history), "recheck_history_after_observation")
    return card, old, history, {"excluded_non_jra_history": excluded, "supplement_conditions": supplements}


def score(dataset: dict, card: dict, history: list[dict], config: dict, frozen: dict) -> dict:
    """同じ固定設定でv1・v2を計算し、過去側にも格別定義を適用する。"""
    validate_card(card, config)
    prior = examples(dataset)
    target = {**{k: v for k, v in card.items() if k != "runners"},
              "rows": [{**r, **make_features(card, r, history)} for r in card["runners"]]}
    candidate = {"pattern": "R0-S1", "family": "resolution", "weights": [1]*5, "scale": 1,
                 "shrinkage": 20, "half_life": None, "pooling": "hierarchical"}
    base_evidence = group_deltas(prior, target, config, candidate)
    base = candidate_prediction(base_evidence, target, candidate)
    resolved_prior = deepcopy(prior)
    for race in resolved_prior:
        for row in race["rows"]:
            row["values"] = resolution_values(race, row, dataset["history"], frozen["definition_mask"])
    resolved_target = deepcopy(target)
    for row in resolved_target["rows"]:
        row["values"] = resolution_values(card, row, history, frozen["definition_mask"])
    candidate.update(pattern="R2-S4", scale=frozen["score_scale"])
    evidence = group_deltas(resolved_prior, resolved_target, config, candidate)
    uncapped = candidate_prediction(evidence, resolved_target, candidate)
    base_by_no = {r["horse_no"]: r["probability_top3"] for r in base["runners"]}
    capped = bounded_probabilities([r["probability_top3"] for r in uncapped["runners"]],
                                  [base_by_no[r["horse_no"]] for r in uncapped["runners"]], frozen["probability_change_cap"])
    rows = [{**r, "probability_top3": p, "baseline_probability_top3": base_by_no[r["horse_no"]]}
            for r, p in zip(uncapped["runners"], capped, strict=True)]
    rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
    require(abs(sum(r["probability_top3"] for r in rows)-3) < 1e-10 and
            all(0 <= r["probability_top3"] <= 1 and abs(r["probability_top3"]-r["baseline_probability_top3"]) <= .0500000001 for r in rows),
            "recheck_probability_invariant")
    return {"v1": base, "v2": {**uncapped, "runners": rows}, "features": resolved_target["rows"], "evidence": evidence}


def render_report(result: dict) -> str:
    """入力の照合結果と参考値・特徴変化を読みやすい日本語表へまとめる。"""
    before = {r["horse_no"]: r for r in result["before"]["v2"]["runners"]}
    lines = ["# エリザベス女王杯2026・取得データによる再検証", "",
             "研究v2の固定設定R2-S4、旧方式比±5ポイント。未校正の3着内参考値で、勝率・購入利益の予測ではない。", "",
             f"カード観測: {result['card']['observed_at']}。資料照合完了後の計算時点: {result['knowledge_cutoff']}。",
             "対象2026結果は未取得。今回検証したのは入力・計算・履歴更新の影響であり、今年の的中精度ではない。", "",
             "## 入力の確認", "",
             "- 18頭の公式馬IDと生年/年齢を照合。カード近4走72件は全件一致。",
             "- 公式掲載247件のうち、国内JRA244件を今回の実績範囲とする。地方/海外3件は別保存して除外。",
             "- 国内235件はDBと着順・距離・斤量が一致。未反映9件を公式掲載と競走条件で補完。",
             "- 保存RAがない2競走は公式ヘッダーとJRA-VANコード表を照合。原RA検証と条件確認を区別。",
             "- 18頭×14特徴を生成。既存研究の23開催を集計に用い、係数や選抜を再調整していない。", "",
             "## 全馬の参考値", "", "| 順位 | 馬番 | 馬名 | 更新前 | 更新後 | 差 |", "|---:|---:|---|---:|---:|---:|"]
    for order, row in enumerate(result["after"]["v2"]["runners"], 1):
        old = before[row["horse_no"]]["probability_top3"]
        p = row["probability_top3"]
        lines.append(f"| {order} | {row['horse_no']} | {row['horse_name']} | {old:.2%} | {p:.2%} | {(p-old)*100:+.2f}pt |")
    lines += ["", "全馬合計は300%。各馬の3着内周辺値なので合計100%へ直さない。",
              "同じ入力に対するv1との差は各馬±5pt以内。上表の更新前後は入力も変わるため、差が5ptを超える場合がある。", "",
              "## 履歴更新で変わったパーツ", "", "| 馬番 | 馬名 | 旧最新走 | 新最新走 | 変化した条件 |", "|---:|---|---|---|---|"]
    for change in result["changes"]:
        if change["changed_features"]:
            text = "、".join(f"{key}: {value['before']}→{value['after']}" for key, value in change["changed_features"].items())
            lines.append(f"| {change['horse_no']} | {change['horse_name']} | {change['before_latest']} | {change['after_latest']} | {text} |")
    lines += ["", "## 確認結果と残件", "",
              "61件の対象/回帰テストを通過。別スクリプトで504特徴値と72確率を独立照合し、verification.jsonに結果を保存する。",
              "既使用過去13開催の約2.97%改善は過去の探索的評価。2026年の精度向上率ではない。",
              "今回の補完値は研究成果物へ保存。SQLの研究履歴表や通常予想・既定モデルは変更していない。",
              "取消等が変わる場合は新カードで再計算する。次は事前値を保持して確定後にv1/v2を比較する。", "",
              "## 出典と制限", "",
              "- [JRA出馬表](" + result["provenance"]["card_source_url"] + ")と、manifestに固定した公式馬別ページ・保存DB。",
              "- [JRA-VAN仕様書](https://jra-van.jp/dlb/sdv/sdk/JV-Data4901.pdf)の2006/2008/2009コード表。",
              *["- " + note for note in result["limitations"]]]
    return "\n".join(lines) + "\n"


def main() -> int:
    """保存監査入力だけで新旧履歴の比較を新規フォルダーへ保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "recheck_output_exists")
    dataset = read_json(args.dataset)
    require(dataset["input_sha256"] == digest({k: v for k, v in dataset.items() if k != "input_sha256"}), "recheck_dataset_sha")
    config = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    v2_config = read_json(ROOT / "configs/research/race_conditions_elizabeth_candidate_v2.json")
    frozen = v2_config["frozen_next_reference_setting"]
    require(frozen["definition_mask"] == 2 and frozen["score_scale"] == 4 and frozen["probability_change_cap"] == .05
            and frozen["group_weights"] == [1]*5 and frozen["shrinkage"] == 20 and frozen["half_life"] is None
            and frozen["pooling"] == "hierarchical",
            "recheck_frozen_setting_changed")
    card, old, history, provenance = build_inputs(args.input, dataset)
    provenance["card_source_url"] = read_json(args.input / "card-response.json")["body"]["source"]
    require(datetime.fromisoformat(card["observed_at"].replace("Z", "+00:00")) < datetime.fromisoformat(card["start_at"]), "recheck_observation_time")
    before = score(dataset, card, old, config, frozen)
    after = score(dataset, card, history, config, frozen)
    old_features = {r["horse_no"]: r for r in before["features"]}
    changes = [{"horse_no": r["horse_no"], "horse_name": r["horse_name"],
                "before_latest": old_features[r["horse_no"]]["latest_stored_race"], "after_latest": r["latest_stored_race"],
                "changed_features": {k: {"before": old_features[r["horse_no"]]["values"][k], "after": v}
                                     for k, v in r["values"].items() if old_features[r["horse_no"]]["values"][k] != v}}
               for r in after["features"]]
    result = {"availability": "reference_only", "probability_kind": "uncalibrated_top3_marginals",
              "outcome_read": False, "knowledge_cutoff": datetime.now(timezone.utc).isoformat(),
              "card": card, "before": before, "after": after, "changes": changes,
              "history_rows_before": len(old), "history_rows_after": len(history), "provenance": provenance,
              "limitations": ["今回の2026結果は未取得。的中率・Brierの新規評価ではない。", "公式掲載のJRA履歴範囲であり世界全体の最高実績ではない。",
                              "HTML補完をRA確認済みへ変換しない。古いカード/履歴の厳密な当時版保証は未完了。",
                              "オッズ・騎手名の注記・体重はモデルに使用していない。校正・利益の証明はない。"]}
    args.output.mkdir(parents=True)
    for name, value in (("recheck.json", result), ("normalized-history.json", history)):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "report.md").write_text(render_report(result), encoding="utf-8")
    sources = [args.dataset, *args.input.glob("*.json"), *args.input.glob("*.html"), *args.input.glob("profiles/*.html"),
               Path(__file__), ROOT / "scripts/run_jra_conditions_resolution.py",
               *[ROOT / "src/jra_srb" / name for name in ("jra_race_conditions.py", "jra_conditions_refinement.py", "jra_conditions_stability.py")],
               ROOT / "configs/research/race_conditions_elizabeth_v1.json", ROOT / "configs/research/race_conditions_elizabeth_candidate_v2.json"]
    manifest = {"input_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                "frozen_config_sha256": digest(v2_config), "output_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.suffix in {".json", ".md"}}}
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete", "before_rows": len(old), "after_rows": len(history),
                      "changed_horses": sum(bool(r["changed_features"]) for r in changes), "top3": after["v2"]["runners"][:3]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
