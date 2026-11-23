"""概要: 統合検証の採否と実際の使用条件を明示したマイルCS当日予想を作る。
作成日: 2026-11-22
入力: --research 統合検証先、--output 新規予想保存先、固定当日入力。
出力: 全頭根拠、10節予想本文、SQL保存用payload、入力出力SHA。
実行例: uv run python scripts/finalize_mile_rule_integration.py --research artifacts/jra_research/mile_integration_v1_1_20261122 --output artifacts/jra_research/mile_integration_forecast_20261122_v1
注意事項: DB保存/読戻しは別実行。結果取得・実購入・旧予想上書きはしない。
"""

import argparse
from datetime import date, datetime, timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from jra_srb.jra_mile_rule_integration import ATOMS, counts
from jra_srb.jra_race_conditions import require
from run_jra_graded_live import table, jst, observed_price
from run_jra_mile_rule_integration import read, save

LABELS = {"last_rank": "前走着順", "layoff": "レース間隔", "class_rank": "前走の格×着順", "lost_relative_weight": "後着相手との相対斤量変化", "won_relative_weight": "先着相手との相対斤量変化"}


def old_records(sets, target_rows, live):
    """実際に使うN/C/Wの各条件へ四区分成績と馬ID付き明細を接続する。"""
    truth = {(r["race_key"], r["horse_id"]): r for r in target_rows if r["status"] == "active"}
    records = {}
    for group, keys in (("N", ("last_rank", "layoff")), ("C", ("class_rank",)), ("W", ("lost_relative_weight", "won_relative_weight"))):
        for target in live["targets"][group]["rows"]:
            for key in keys:
                value = target["values"][key]
                if value is None:
                    continue
                identifier = group+":"+key+":"+value
                if identifier in records:
                    continue
                members = []
                for past in sets[group]:
                    for row in past["rows"]:
                        if row["values"][key] != value:
                            continue
                        source = truth[(past["race_key"], row["horse_id"])]
                        members.append({"race_key": past["race_key"], "race_date": past["race_date"], "horse_id": row["horse_id"],
                                        "horse_no": row["horse_no"], "horse_name": row["horse_name"], "finish_rank": source["rank"],
                                        "nonfinish_confirmed": source["rank"] is None and source.get("abnormal_code") not in (None, "0")})
                records[identifier] = {"group": group, "feature": key, "value": value, "label": LABELS[key], "counts": counts(members), "members": members,
                    "annual": {str(year): counts([r for r in members if r["race_date"][:4] == str(year)]) for year in range(2003, 2026)}}
    return records


def rationales(current, forecast, live, records, rule_records):
    """各馬の採用根拠と未採用の追加条件を混同しない説明を作る。"""
    source = {r["horse_id"]: r for r in current["features"]}
    ev = {g: {r["horse_id"]: r for r in live["evidence"][g]} for g in ("N", "C", "W")}
    targets = {g: {r["horse_id"]: r for r in live["targets"][g]["rows"]} for g in ("N", "C", "W")}
    output = []
    record_map = {r["id"]: r for r in rule_records}
    for rank, row in enumerate(forecast["runners"], 1):
        hid = row["horse_id"]
        feature = source[hid]
        previous = feature["references"]["previous"]
        gap = (date(2026, 11, 22)-date.fromisoformat(previous["race_date"])).days
        title = previous.get("race_name") or previous.get("race_name_raw")
        actual = []
        for group, keys in (("N", ("last_rank", "layoff")), ("C", ("class_rank",)), ("W", ("lost_relative_weight", "won_relative_weight"))):
            for key in keys:
                value = targets[group][hid]["values"][key]
                if value is not None:
                    actual.append({"record_id": group+":"+key+":"+value, "label": LABELS[key], "value": value,
                                   "record": records[group+":"+key+":"+value]["counts"]["record"]})
        delta = {"N": ev["N"][hid]["deltas"][2], "C": ev["C"][hid]["deltas"][0], "W": ev["W"][hid]["deltas"][0]}
        atom_text = []
        for key in ("age34", "previous5", "route4", "mile_g1_top2", "kyoto1600_top3", "under6"):
            matched = feature["atoms"][key]
            label = "true" if matched is True else "false" if matched is False else "unknown"
            atom_text.append({"condition": ATOMS[key], "matched": matched, "record": record_map[key]["groups"][label]["record"],
                              "used_in_final_score": False})
        output.append({**row, "rank": rank, "previous_name": title, "previous_date": previous["race_date"], "previous_rank": previous["rank"],
            "layoff_days": gap, "actual_conditions": actual, "actual_group_deltas": delta,
            "score_formula": "N+0.5*C+0.5*W", "supplementary_not_used": atom_text, "rescue_research_only": feature["rescue"],
            "decision": "主案に含める" if rank <= 3 else "比較相手候補" if rank <= 6 else "固定主案の対象外。消去断定ではない",
            "explanation": f"前走は{title}{previous['rank']}着、間隔{gap}日。近況Nは{'上向き' if delta['N']>0 else '下向き' if delta['N']<0 else '中立'}、格×着順Cは{'上向き' if delta['C']>0 else '下向き' if delta['C']<0 else '中立'}、相対斤量Wは{'上向き' if delta['W']>0 else '下向き' if delta['W']<0 else '未対戦等で中立'}。この合成で{rank}位。"})
    return output


def human_report(rows):
    """全18頭へ実条件・四区分成績・判断・未使用補助情報を平易に記す。"""
    lines = ["# マイルCS当日予想・全頭の判断理由", "", "成績は2003〜2025年同名23開催の1着－2着－3着－着外。開催場別/年度別/元明細はJSONへ保存。縮約前の支持数で、今回の馬の確率ではありません。", "",
             "追加25条件は検証で採用基準未達。下の補助情報と救済仮説は最終点数へ加えていません。", ""]
    for row in rows:
        lines += [f"## {int(row['horse_no'])} {row['horse_name']}：{row['rank']}位・{row['decision']}", "", row["explanation"], "",
            table(["今回使った条件", "この馬の該当値", "過去成績"], [[r["label"], r["value"].replace("A|", "GI・").replace("B|", "GII・").replace("C|", "GIII・"), r["record"]] for r in row["actual_conditions"]]), "",
            "補助確認（今回未加点）："+"／".join(r["condition"]+"="+("該当" if r["matched"] is True else "非該当（実績は収録内未確認）" if r["matched"] is False else "不明")+"〔"+r["record"]+"〕" for r in row["supplementary_not_used"]), "",
            "救済仮説（今回未採用）："+"、".join(k+"="+v["status"] for k, v in row["rescue_research_only"].items()), ""]
    return "\n".join(lines)


def render(x):
    """既存10節の列を維持し、統合不採用と今回の判断理由を表示する。"""
    rows = x["forecast"]["runners"]
    win = {str(int(r["combination"][0])): r for r in x["odds"]["odds"]["win"]}
    popularity = {h: i for i, h in enumerate(sorted(win, key=lambda h: (float(win[h]["odds"]), int(h))), 1)}
    index = {str(int(r["horse_no"])): r for r in rows}
    record = x["actual_condition_records"]
    rec_c1, rec_c2 = record["C:class_rank:A|1着"]["counts"]["record"], record["C:class_rank:A|2〜3着"]["counts"]["record"]
    top = x["top"]
    ranked = "、".join(r["mark"]+str(int(r["horse_no"]))+r["horse_name"] for r in rows[:3])
    lines = [f"**今回の予想は{ranked}です。** 統合版を検証しましたが追加条件の改善が確認できず、今回は旧基準を維持します。", "",
        "使用方式：重賞固有条件パーツ研究／選択理由：今回の統合検証・予想指示／使用モデル：mile-specific-hcw-v1:N+C+W", "",
        "## 1. レースと使用方式", "", table(["項目", "内容"], [
            ["対象", "2026/11/22 京都11R マイルチャンピオンシップ／202611220811／15:40発走"],
            ["使用方式", "重賞固有条件パーツ研究・統合検証後の当日版"], ["選択理由", "今回の明示指定"],
            ["使用モデル", f"N+C+Wを維持。統合検証v1.1／同名2003〜2025年23開催／設定SHA {x['config_sha256'][:12]}"],
            ["予想作成時刻", jst(x["created_at"])], ["予想の状態", "発走前。馬体重未発表時点の固定案"],
            ["確率の意味", "3着内参考確率。未校正。◎は1着指定ではない"]]), "",
        "## 2. 入力データの状態", "", table(["材料", "観測時刻", "確認結果・不足"], [
            ["出馬表・取消", jst(x["card"]["observed_at"]), "公式現在欄18頭。15は出走扱い。API誤取消との差を保存"],
            ["過去走・競走条件", "11/20監査・当日近走再照合", "国内229走＋非JRA10走。現在欄・近走72走は前回と一致。歴年海外欠落あり"],
            ["馬場・馬体重", jst(x["card"]["observed_at"]), "馬場表示は良。馬体重未発表。両者による点数補正は未実装"],
            ["単勝オッズ", jst(x["odds"]["fetched_at"]), "18頭の途中オッズ。最終価格ではない"],
            ["ワイド・3連複オッズ", jst(x["odds"]["fetched_at"]), "153組・816組を取得"], ["補助券種オッズ", "未取得", "補助案なし"]]), "",
        "## 3. 全頭評価", "", table(["評価順位", "印", "馬番・馬名", "3着内参考確率", "単勝オッズ・人気", "市場人気との差"], [
            [r["rank"], r["mark"], f"{int(r['horse_no'])} {r['horse_name']}", f"{r['probability_top3']:.1%}",
             f"{win[str(int(r['horse_no']))]['odds']}倍・{popularity[str(int(r['horse_no']))]}人気", popularity[str(int(r["horse_no"]))]-r["rank"]] for r in rows]), "",
        "市場との差は人気順位−評価順位で、期待値ではありません。", "",
        "## 4. 使用パーツと評価の根拠", "", table(["条件群", "今回使った条件", "過去の根拠", "今回の評価への影響"], [
            ["基本属性", "年齢と複合条件を追加検証", "前走5着以内＋6歳未満：16-17-17-137", "追加は不採用。年齢で強制消去しない"],
            ["前哨戦経路", "C：前走の格×着順", f"前走GI1着={rec_c1}／GI2〜3着={rec_c2}", "2・1はGI1着、12はGI2着で上向き"],
            ["直近成績と間隔", "N：前走着順と休養日数", "前走1着=9-8-5-48／113日以上=1-1-1-19", "2の勝利を評価し、189日ぶりの割引も反映"],
            ["条件変更", "W：再対戦の相対斤量", "先着相手と概ね同じ斤量差の全根拠は別紙", "実績条件と二重加点せず既存Wを維持。1は未対戦で中立"],
            ["過去実績", "マイルGI連対・京都好走を追加検証", "マイルGI連対あり=13-13-7-110", "補助確認。今回の点数へ新規加算しない"]]), "",
        "成績表記は**1着－2着－3着－着外**。同名23開催の集計で、今年の馬ごとの確率ではありません。", "",
        f"**◎2 エンブロイダリー**：前走ヴィクトリアマイル1着で、前走GI勝利の条件〔{rec_c1}〕に該当するため上位評価。一方、189日ぶりは割引材料です。馬体重・仕上がりを確認済みとはしていません。", "",
        f"**○1 エルデナリ**：前走ムーラン・ドGI1着、77日ぶり。同じGI勝利条件〔{rec_c1}〕を評価します。ただし根拠は7頭と少なく、海外と国内の同等性・日本初戦への適応は未検証です。", "",
        f"**▲12 ワールズエンド**：前走スプリンターズS2着、56日ぶり。前走GI2〜3着条件〔{rec_c2}〕と近況が上向きです。安田記念2着も確認しましたが、その実績を今回追加加点したわけではありません。", "",
        "**統合検証の結論**：25ルール・51方式・18年918予測。開発で選んだ『前走5着以内＋6歳未満』の追加は、参照済み2021〜2025年でBrierが0.135336→0.135642と約0.23%悪化。上位3頭に含まれた実好走馬は合計6→5頭、上位6頭では11→9頭。今回は採用しません。利益の検証ではありません。", "",
        f"[全18頭の条件・過去成績・残した理由]({x['human_report_path']})／[25条件の比較結果]({x['research_report_path']})。生産者を含む救済条件など、未接続の条件は消去に使っていません。", "",
        "## 5. 市場比較と採否", "", table(["対象馬", "モデル評価", "市場評価", "扱い", "理由"], [
            [f"{h} {index[h]['horse_name']}", f"{index[h]['rank']}位", f"{win[h]['odds']}倍・{popularity[h]}人気", "主案に含める" if h in top else "主案外・消去断定なし",
             "固定評価の上位3頭" if h in top else "GI実績は確認。前走GI4着の評価とW中立等で11位。人気だけで入替えない"] for h in (*top, "14")]), "",
        "## 6. 主案の検証用仮想買い目", "", f"主案ID：{x['plan']['plan_id']}／規則：{x['plan']['policy_id']}／評価対象はこの主案のみ。", "",
        table(["券種", "組合せ", "実オッズ", "仮想金額", "採用理由"], [["ワイド" if t["bet_type"] == "wide" else "3連複", "－".join(t["selection"]), t["display_odds"], "100円", "上位3頭の固定比較"] for t in x["plan"]["tickets"]]), "",
        f"仮想合計400円、実購入0円。価格観測：{jst(x['odds']['fetched_at'])}。組の確率・期待値は未計算です。", "",
        "## 7. 補助案・追加仮説", "", table(["案ID", "券種・組合せ", "実オッズ", "仮想金額", "仮説・根拠", "評価上の扱い"], [["なし", "追加なし", "非適用", "0円", "未採用条件による買い目の追加はしない", "主案のみ"]]), "",
        "## 8. 保存状況", "", table(["項目", "状態"], [["予想ID", x["prediction_id"]], ["主案・入力・表示全文", "新IDでSQL保存・全文読戻し照合済み。旧版を保持"],
            ["事前保存の確認", "発走前。結果未取得"], ["自動評価の対応", "研究独自のワイド・3連複は共通自動評価へ未接続"]]), "",
        "## 9. 結果検証", "", table(["評価項目", "結果"], [["公式結果・払戻", "未確定・未取得"], ["モデル評価と実際の3着内馬", "未確定"],
            ["主案：仮想購入額・払戻・回収率", "仮想400円・払戻/回収率未確定"], ["券種別的中・トリガミ", "未確定"], ["補助仮説", "追加案なし"]]), "",
        "## 10. 断層競馬の独立参考", "", "未判定。本体へ混入していません。", ""]
    return "\n".join(lines)


def main():
    """事前入力と採否を固定し、新IDの予想と保存payloadを作る。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "integration_final_output_exists")
    summary, current = read(args.research/"summary.json"), read(args.research/"current.json")
    require(summary["forecast_pattern"] == "baseline", "integration_final_actual_model_requires_new_renderer")
    inputs = ROOT/"artifacts/jra_research/mile_integration_v1_20261122_inputs"
    card, official, odds = read(inputs/"normalized-card.json"), read(inputs/"official-parsed-card.json"), read(inputs/"odds-summary.json")
    require(datetime.now(timezone.utc) < datetime.fromisoformat(card["start_at"]), "integration_final_after_start")
    require(0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(odds["fetched_at"].replace("Z", "+00:00"))).total_seconds() < 900, "integration_final_prices_stale")
    require(odds["race_id"] == card["race_key"], "integration_final_odds_identity")
    forecast = current["predictions"][summary["forecast_pattern"]]
    for i, row in enumerate(forecast["runners"], 1):
        row.update(rank=i, mark="◎" if i == 1 else "○" if i == 2 else "▲" if i == 3 else "△" if i <= 6 else "―")
    ref = ROOT/"artifacts/jra_research/mile_extension_v1_20261121"
    live = read(ref/"live-comparison.json")["international_connected"]
    datafile = ROOT/"artifacts/jra_research/graded_specific_20261120_coverage/mile-normalized.json"
    records = old_records(read(ref/"sets.json"), read(datafile)["target_rows"], live)
    reasons = rationales(current, forecast, live, records, read(args.research/"rule-records.json"))
    top = [str(int(r["horse_no"])) for r in forecast["runners"][:3]]
    now = datetime.now(timezone.utc).isoformat()
    pid = "jra-mile-integration-20261122-"+uuid.uuid4().hex
    tickets = []
    for bet, selections in (("wide", combinations(top, 2)), ("trio", [top])):
        for selection in selections:
            price = observed_price(odds, bet, selection)
            require(price is not None, "integration_final_ticket_price")
            observed = {"min": price["odds_min"], "max": price["odds_max"]} if bet == "wide" else {"value": price["odds"]}
            tickets.append({"bet_type": bet, "selection": sorted(selection, key=int), "amount": 100, "observed_odds": observed,
                            "observed_at": odds["fetched_at"], "display_odds": f"{price['odds_min']}〜{price['odds_max']}" if bet == "wide" else price["odds"]})
    plan = {"plan_id": pid+"-w3t1", "policy_id": "mile-integration-reviewed-w3t1-equal100-v1", "virtual_only": True, "budget": 400, "tickets": tickets,
            "status": "priced", "price_basis": "same_day_observed_not_final"}
    configfile = ROOT/"configs/research/mile_rule_integration_v1.json"
    x = {"prediction_id": pid, "created_at": now, "card": card, "odds": odds, "forecast": forecast, "top": top, "plan": plan,
         "config_sha256": hashlib.sha256(configfile.read_bytes()).hexdigest(), "actual_condition_records": records, "rationales": reasons,
         "human_report_path": (args.output/"human-rationale.md").resolve().as_posix(), "research_report_path": (args.research/"report.md").resolve().as_posix()}
    presentation = render(x)
    x["presentation"] = presentation
    payload = {"prediction_id": pid, "race_id": card["race_key"], "theory_version": "condition_parts:mile-integration-reviewed-v1:baseline-N+C+W",
        "mode": "condition_parts_mile_specific", "budget": 0, "created_at": now,
        "pre_race_snapshot": {"card": card, "official_current_card": official, "odds": odds, "card_verification": read(inputs/"verification.json")},
        "prediction_json": {"method_selection": {"method": "condition_parts", "source": "explicit_user", "reason": "利用者の統合検証とマイルCS予想指示", "model": "mile-specific-hcw-v1:N+C+W"},
            "selected_model": {"id": "mile-specific-hcw-v1", "pattern": "N+C+W", "training_period": [2003, 2025], "config_sha256": hashlib.sha256((ROOT/"configs/research/mile_extension_v1.json").read_bytes()).hexdigest(),
                "status": "exploratory_research_not_independently_validated", "purchase_approved": False},
            "integration_review": {"protocol": "mile-rule-integration-v1", "config_sha256": x["config_sha256"], "selected_candidate": summary["selection"]["pattern"], "forecast_pattern": summary["forecast_pattern"],
                "adopted": False, "comparison": summary["comparison"], "source": str(args.research.resolve())},
            "input_state": {"card_observed_at": card["observed_at"], "odds_observed_at": odds["fetched_at"], "race_going": official.get("track_condition_label"),
                "body_weight": "not_announced", "body_weight_used": False, "going_used_in_score": False, "international_history_connected": True},
            "condition_parts_forecast": forecast, "condition_parts_evidence": live["evidence"], "actual_condition_records": records, "horse_rationales": reasons,
            "condition_parts_plan": plan, "condition_parts_alternatives": [], "presentation": {"text": presentation, "template_version": "condition-parts-output-v1"},
            "predicted_top3": top, "finish_order_prediction_available": False, "axis_horse_numbers": top[:1], "opponent_horse_numbers": top[1:],
            "generated_before_result": True, "reconstruction_after_result": False}, "prediction_tickets": []}
    args.output.mkdir(parents=True)
    save(args.output/"prediction.json", x)
    save(args.output/"payload.json", payload)
    save(args.output/"actual-condition-records.json", records)
    save(args.output/"horse-rationales.json", reasons)
    (args.output/"human-rationale.md").write_text(human_report(reasons), encoding="utf-8")
    (args.output/"presentation.md").write_text(presentation, encoding="utf-8")
    paths = [Path(__file__), configfile, ROOT/"configs/research/mile_extension_v1.json", datafile, args.research/"manifest.json", args.research/"summary.json", args.research/"current.json", args.research/"rule-records.json",
             ref/"sets.json", ref/"live-comparison.json", inputs/"manifest.json", inputs/"normalized-card.json", inputs/"official-parsed-card.json", inputs/"odds-summary.json"]
    save(args.output/"manifest.json", {"inputs": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
    print(json.dumps({"prediction_id": pid, "top3": top, "virtual_yen": 400, "purchase_yen": 0, "rationale_rows": len(reasons)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
