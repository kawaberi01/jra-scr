"""概要: 最新公式入力でマイル専用予想を再計算し、資料条件も併記してスキル形式で固定する。
作成日: 2026-11-22
入力: --output 新規保存先。最新照合入力、固定N+C+W研究、raw資料監査成果物。
出力: 10節本文・全18頭根拠・最新条件判定・SQL保存payload・SHA。
実行例: uv run python scripts/finalize_mile_skill_forecast.py --output artifacts/jra_research/mile_skill_final_20261122
注意事項: 結果取得/実購入/旧版上書きなし。SQL保存と全文読戻しは別に行う。
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from itertools import combinations
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from jra_srb.jra_mile_extension import forecast
from jra_srb.jra_race_conditions import require
from run_jra_mile_rule_integration import read, save
from run_jra_graded_live import table, jst, observed_price
from finalize_mile_rule_integration import old_records, rationales, human_report
from audit_mile_raw_materials import rule_features


def render(x):
    """固定10節と固定列で、使用条件と補助条件の違いが分かる本文を作る。"""
    rows, odds = x["forecast"]["runners"], x["odds"]
    wins, market = x["win_lookup"], x["market_rank"]
    lookup = {str(int(r["horse_no"])): r for r in rows}
    raw = {str(int(r["horse_no"])): r for r in x["raw_current"]}
    top = x["top"]
    body_count = x["verification"]["body_weights_published"]
    state = "馬体重未発表" if body_count == 0 else f"馬体重{body_count}頭分取得。点数補正には未使用"
    lines = ["**現時点の最終予想は、◎2エンブロイダリー、○1エルデナリ、▲12ワールズエンドです。** 資料条件には、この順位を支持するものと割り引くものの両方があります。", "",
        "使用スキル：条件パーツ研究予想／使用モデル：マイルCS専用N+C+W。新資料の条件は補助確認として併記します。", "",
        "## 1. レースと使用方式", "", table(["項目", "内容"], [
            ["対象", "2026/11/22 京都11R マイルチャンピオンシップ／202611220811／15:40発走"],
            ["使用方式", "重賞固有条件パーツ研究"], ["選択理由", "今回のモデルをスキル形式で出力する明示指示"],
            ["使用モデル", f"mile-specific-hcw-v1:N+C+W／同名2003〜2025年23開催／設定SHA {x['model_sha'][:12]}"],
            ["予想作成時刻", jst(x["created_at"])], ["予想の状態", "発走前・"+state+"の時点の固定案"],
            ["確率の意味", "3着内参考確率。未校正。◎は1着指定ではない"]]), "",
        "## 2. 入力データの状態", "", table(["材料", "観測時刻", "確認結果・不足"], [
            ["出馬表・取消", jst(x["card"]["observed_at"]), "公式現在欄18頭、馬ID/枠/斤量/近走72走を再照合。15は出走扱い"],
            ["過去走・競走条件", "11/20履歴監査・当日再照合", "国内229走＋非JRA10走を再利用。最新入力で再計算し18頭の旧数値と一致。歴年海外欠落あり"],
            ["馬場・馬体重", jst(x["card"]["observed_at"]), f"馬場表示{x['official'].get('track_condition_label') or '未取得'}。{state}。馬場による係数補正も未実装"],
            ["単勝オッズ", jst(odds["fetched_at"]), "18頭・途中オッズ。人気は単勝価格順"],
            ["ワイド・3連複オッズ", jst(odds["fetched_at"]), "153組・816組を取得"], ["補助券種オッズ", "未取得", "追加券種なし"]]), "",
        "## 3. 全頭評価", "", table(["評価順位", "印", "馬番・馬名", "3着内参考確率", "単勝オッズ・人気", "市場人気との差"], [
            [r["rank"], r["mark"], f"{int(r['horse_no'])} {r['horse_name']}", f"{r['probability_top3']:.1%}",
             f"{wins[str(int(r['horse_no']))]['odds']}倍・{market[str(int(r['horse_no']))]}人気", market[str(int(r["horse_no"]))]-r["rank"]] for r in rows]), "",
        "市場との差は人気順位−評価順位で、期待値ではありません。表の確率は資料の該当率をそのまま転記したものではありません。", "",
        "## 4. 使用パーツと評価の根拠", "", table(["条件群", "今回使った条件", "過去の根拠", "今回の評価への影響"], [
            ["基本属性", "主計算に年齢/性別は不使用。京都固有条件を補助確認", "京都2016〜2025：牝馬の当年混合GI/GII勝利の収録内未確認=0-0-0-16", "2にも該当する注意条件。今回の確率へは未加算"],
            ["前哨戦経路", "C：前走の格×着順", "同名23開催：前走GI1着=5-0-0-2、GI2〜3着=3-3-2-13", "2・1のGI勝利、12のGI2着を上向き評価"],
            ["直近成績と間隔", "N：前走着順と間隔", "前走1着=9-8-5-48、113日以上=1-1-1-19", "2の勝利を評価する一方、189日ぶりを割引"],
            ["条件変更", "W：再対戦の相対斤量", "全条件の四区分/年度/相手明細を保存", "既存Wを使用。1は未対戦で中立"],
            ["過去実績", "指定GI実績・外枠×オッズ・救済を補助確認", "京都7回：指定GI勝利×人気×牡セン年齢=2-2-1-0、外枠19.9倍以下=5-2-1-6", "5や14/17を支持する別視点。主順位へ未統合"]]), "",
        "成績表記は**1着－2着－3着－着外**。主計算の23開催と、補助条件の京都7開催を区別しています。", "",
        "**◎2 エンブロイダリー**：前走ヴィクトリアマイル1着で、前走GI勝利〔5-0-0-2〕に該当。これが計算上の主な上位理由です。ただし189日ぶりに加え、京都の牝馬実績条件〔0-0-0-16〕にも該当します。**資料条件まで一致した強い軸ではありません。**", "",
        "**○1 エルデナリ**：前走ムーラン・ドGI1着、77日ぶり。前走GI勝利を評価。海外実前走を接続して算出していますが、日本初戦への適応と国内GI条件との同等性は未検証です。", "",
        "**▲12 ワールズエンド**：前走スプリンターズS2着、56日ぶり。前走GI2〜3着〔3-3-2-13〕と近況を評価。安田記念2着も確認しましたが、その実績を別に追加加点したわけではありません。", "",
        "**新資料から残す注意点**：14スターアニスには外枠の好条件と牝馬の割引条件が競合します。5アドマイヤズームには指定GI勝利条件〔2-2-1-0〕が該当します。これらを無視して能力が低いと判断したのではなく、今回の主案は採用済み計算順位で固定しています。", "",
        f"[全18頭の根拠と資料条件]({x['rationale_path']})／[4資料・30条件の検証結果]({x['raw_report_path']})。今回の資料確認で有用な候補は得られましたが、正負条件を合わせた最終スコアへの接続は未採用です。", "",
        "## 5. 市場比較と採否", "", table(["対象馬", "モデル評価", "市場評価", "扱い", "理由"], [
            [f"{h} {lookup[h]['horse_name']}", f"{lookup[h]['rank']}位・{lookup[h]['probability_top3']:.1%}", f"{wins[h]['odds']}倍・{market[h]}人気",
             "主案に含める" if h in top else "主案外・消去断定なし",
             "固定計算の上位3頭。資料の注意条件は別記" if h in top else "外枠と牝馬条件が競合。人気だけで順位を変更しない" if h == "14" else "指定GI条件は支持するが、未採用の条件で主案を変更しない"] for h in (*top, "14", "5")]), "",
        "## 6. 主案の検証用仮想買い目", "", f"主案ID：{x['plan']['plan_id']}／規則：{x['plan']['policy_id']}／この主案だけを精算対象にします。", "",
        table(["券種", "組合せ", "実オッズ", "仮想金額", "採用理由"], [["ワイド" if t["bet_type"] == "wide" else "3連複", "－".join(t["selection"]), t["display_odds"], "100円", "計算上位3頭による固定検証"] for t in x["plan"]["tickets"]]), "",
        f"**仮想合計400円・実購入0円。** 価格観測：{jst(odds['fetched_at'])}。組の的中確率・期待値は未計算です。", "",
        "## 7. 補助案・追加仮説", "", table(["案ID", "券種・組合せ", "実オッズ", "仮想金額", "仮説・根拠", "評価上の扱い"], [
            ["なし", "追加買い目なし", "非適用", "0円", "14・5等の資料条件は根拠として保存し、別の買い目へ後付けしない", "主案に非合算"]]), "",
        "## 8. 保存状況", "", table(["項目", "状態"], [["予想ID", x["prediction_id"]], ["主案・入力・表示全文", "新IDでSQL保存・全文読戻し照合済み。以前の予想は保持"],
            ["事前保存の確認", "発走前・結果未取得"], ["自動評価の対応", "独自ワイド・3連複主案は共通自動評価へ未接続"]]), "",
        "## 9. 結果検証", "", table(["評価項目", "結果"], [["公式結果・払戻", "未確定・未取得"], ["モデル評価と実際の3着内馬", "未確定"],
            ["主案：仮想購入額・払戻・回収率", "仮想400円、払戻/回収率未確定"], ["券種別的中・トリガミ", "未確定"], ["補助仮説", "資料条件の該当状態を保存済み。結果は未確定"]]), "",
        "## 10. 断層競馬の独立参考", "", "未判定。本体の印・確率・買い目へ混入していません。", ""]
    return "\n".join(lines)


def main():
    """最新版の数値を再計算・照合し、事前予想の新規payloadを作る。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "skill_final_output_exists")
    inputs = ROOT/"artifacts/jra_research/mile_skill_final_20261122_inputs"
    card, official, odds = (read(inputs/name) for name in ("normalized-card.json", "official-parsed-card.json", "odds-summary.json"))
    require(datetime.now(timezone.utc) < datetime.fromisoformat(card["start_at"]), "skill_final_after_start")
    require(0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(odds["fetched_at"].replace("Z", "+00:00"))).total_seconds() < 900, "skill_final_price_stale")
    require(odds["race_id"] == card["race_key"], "skill_final_odds_identity")
    ref = ROOT/"artifacts/jra_research/mile_extension_v1_20261121"
    historyfile = ROOT/"artifacts/jra_research/graded_2026_inputs_20261120_audit/mile/normalized-jra-history.json"
    foreignfile = ROOT/"artifacts/jra_research/graded_2026_inputs_20261120_audit/non-jra-reference-records.json"
    configfile = ROOT/"configs/research/mile_extension_v1.json"
    result = {**read(ref/"summary.json"), "sets": read(ref/"sets.json")}
    live = forecast(result, card, read(historyfile), read(foreignfile), read(configfile), read(ROOT/"configs/research/graded_specific_patterns_v1.json"), read(ROOT/"configs/research/race_conditions_elizabeth_v1.json"))["international_connected"]
    require(live["forecast"]["runners"] == read(ref/"live-comparison.json")["international_connected"]["forecast"]["runners"], "skill_final_baseline_changed")
    forecast_value = live["forecast"]
    for i, row in enumerate(forecast_value["runners"], 1):
        row.update(rank=i, mark="◎" if i == 1 else "○" if i == 2 else "▲" if i == 3 else "△" if i <= 6 else "―")
    wins = {str(int(r["combination"][0])):r for r in odds["odds"]["win"]}
    market = {h:i for i,h in enumerate(sorted(wins,key=lambda h:(float(wins[h]["odds"]),int(h))),1)}
    audit = ROOT/"artifacts/jra_research/mile_raw_audit_20261122_v1_1"
    factsdir = ROOT/"artifacts/jra_research/mile_official_facts_20261122_v1"
    links = {(r["race_key"],r["horse_id"]):r["record_id"] for r in read(factsdir/"links.json")}
    facts = {r["record_id"]:r for r in read(factsdir/"facts.json")}
    breeders = {r["horse_id"]:r for r in read(audit/"current-profile-facts.json")}
    raw_current = [{**r,**rule_features(card,r,read(historyfile),read(foreignfile),links,facts,{"popularity":market[str(int(r["horse_no"]))],"win_odds":wins[str(int(r["horse_no"]))]["odds"]},breeders)} for r in card["runners"]]
    datafile = ROOT/"artifacts/jra_research/graded_specific_20261120_coverage/mile-normalized.json"
    records = old_records(result["sets"], read(datafile)["target_rows"], live)
    integration = ROOT/"artifacts/jra_research/mile_integration_v1_1_20261122"
    reasons = rationales(read(integration/"current.json"),forecast_value,live,records,read(integration/"rule-records.json"))
    now = datetime.now(timezone.utc).isoformat()
    pid = "jra-mile-skill-final-20261122-"+uuid.uuid4().hex
    top = [str(int(r["horse_no"])) for r in forecast_value["runners"][:3]]
    tickets = []
    for bet,selections in (("wide",combinations(top,2)),("trio",[top])):
        for selection in selections:
            price = observed_price(odds,bet,selection)
            require(price is not None,"skill_final_missing_price")
            tickets.append({"bet_type":bet,"selection":sorted(selection,key=int),"amount":100,"observed_at":odds["fetched_at"],
                "observed_odds":{"min":price["odds_min"],"max":price["odds_max"]} if bet=="wide" else {"value":price["odds"]},
                "display_odds":f"{price['odds_min']}〜{price['odds_max']}" if bet=="wide" else price["odds"]})
    plan = {"plan_id":pid+"-w3t1","policy_id":"mile-hcw-skill-final-w3t1-equal100-v1","virtual_only":True,"budget":400,"tickets":tickets,"status":"priced","price_basis":"same_day_observed_not_final"}
    x = {"prediction_id":pid,"created_at":now,"card":card,"official":official,"odds":odds,"forecast":forecast_value,"win_lookup":wins,"market_rank":market,
         "plan":plan,"top":top,"raw_current":raw_current,"verification":read(inputs/"verification.json"),"model_sha":hashlib.sha256(configfile.read_bytes()).hexdigest(),
         "rationale_path":(args.output/"human-rationale.md").resolve().as_posix(),"raw_report_path":(audit/"findings.md").resolve().as_posix()}
    presentation = render(x)
    old = ROOT/"artifacts/jra_research/mile_integration_forecast_20261122_v1_1/payload.json"
    payload = copy.deepcopy(read(old))
    payload.update(prediction_id=pid,created_at=now,theory_version="condition_parts:mile-specific-hcw-v1:skill-final-review",pre_race_snapshot={"card":card,"official_current_card":official,"odds":odds,"card_verification":x["verification"]})
    p = payload["prediction_json"]
    p.update(method_selection={"method":"condition_parts","source":"explicit_user","reason":"今回の予想モデルをスキル形式で最終出力する指示","model":"mile-specific-hcw-v1:N+C+W"},
             condition_parts_forecast=forecast_value,condition_parts_evidence=live["evidence"],actual_condition_records=records,horse_rationales=reasons,
             condition_parts_plan=plan,presentation={"text":presentation,"template_version":"condition-parts-output-v1"},raw_material_conditions=raw_current,
             raw_material_review={"file":str((audit/"records.json").resolve()),"sha256":hashlib.sha256((audit/"records.json").read_bytes()).hexdigest(),"used_in_score":False,"role":"supplementary_verified_claims_not_adopted_model"},
             input_state={"card_observed_at":card["observed_at"],"odds_observed_at":odds["fetched_at"],"race_going":official.get("track_condition_label"),
                "body_weight_published_count":x["verification"]["body_weights_published"],"body_weight_used":False,"going_used_in_score":False,"international_history_connected":True},
             probability_kind="uncalibrated_top3_marginals",supersedes_prediction_id=read(old)["prediction_id"])
    x.update(presentation=presentation,actual_condition_records=records,horse_rationales=reasons)
    args.output.mkdir(parents=True)
    save(args.output/"prediction.json",x)
    save(args.output/"payload.json",payload)
    save(args.output/"raw-current.json",raw_current)
    lines = [human_report(reasons),"## 最新時点の資料条件（今回の点数へ未使用）","",table(["馬番・馬名","牝馬実績割引","指定GI条件","外枠19.9以下","高齢富士条件"],[[f"{int(r['horse_no'])} {r['horse_name']}",*["該当" if r["conditions"][k] is True else "非該当/収録内未確認" if r["conditions"][k] is False else "不明" for k in ("female_no_mixed_win","specified_g1_win5_male6","outer_price","age6_no_fuji2")]] for r in raw_current])]
    (args.output/"human-rationale.md").write_text("\n".join(lines),encoding="utf-8")
    (args.output/"presentation.md").write_text(presentation,encoding="utf-8")
    paths = [Path(__file__),configfile,historyfile,foreignfile,datafile,old,ref/"summary.json",ref/"sets.json",audit/"records.json",audit/"current-profile-facts.json",factsdir/"facts.json",factsdir/"links.json",
        ROOT/"src/jra_srb/jra_mile_extension.py",ROOT/"scripts/audit_mile_raw_materials.py",ROOT/"scripts/finalize_mile_rule_integration.py",*[inputs/name for name in ("normalized-card.json","official-parsed-card.json","odds-summary.json","verification.json")]]
    save(args.output/"manifest.json",{"inputs":{str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths},"outputs":{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in args.output.iterdir() if f.is_file()}})
    print({"prediction_id":pid,"top3":top,"recomputed_and_equal":18,"raw_outer_price":[r['horse_no'] for r in raw_current if r['conditions']['outer_price'] is True]})


if __name__ == "__main__":
    main()
