"""概要: 検証済みマイル専用版から固定10節の前日予想とSQL保存用payloadを作る。
作成日: 2026-11-21
入力: --inputs 最新公式再確認フォルダー、--research 追加研究出力、--output 新規保存先。
出力: prediction.json、payload.json、presentation.md、入力出力SHA。
実行例: uv run python scripts/finalize_mile_forecast.py --help
注意事項: 外部通信・DB書込み・実購入なし。SQL保存と全文読戻しは既存補助で別実行する。
"""

from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from jra_srb.jra_race_conditions import require
from run_jra_graded_live import table,jst


def read(path: Path):
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path,value) -> None:
    """新規ファイルだけへ構造化値を保存する。"""
    with path.open("x",encoding="utf-8") as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)


def render(x: dict) -> str:
    """固定テンプレートの節・列を維持して新専用版の内容を描画する。"""
    rows,odds = x["forecast"]["runners"],x["odds"]
    win = {str(int(r["combination"][0])):r for r in odds["odds"]["win"]}
    popular = {h:i for i,h in enumerate(sorted(win,key=lambda h:(float(win[h]["odds"]),int(h))),1)}
    lookup = {str(int(r["horse_no"])):r for r in rows}
    c = x["confirmation"]
    lines = ["使用方式：重賞固有条件パーツ研究／選択理由：この会話で指定／モデル：mile-specific-hcw-v1:N+C+W", "",
        "現時点の最終案は **◎2エンブロイダリー、○1エルデナリ、▲12ワールズエンド**。前日版。明日の馬場・馬体重・取消・価格は未確認です。", "",
        "## 1. レースと使用方式", "",table(["項目","内容"],[
            ["対象","2026-11-22 京都11R 第43回マイルチャンピオンシップ／202611220811／15:40発走"],
            ["使用方式","重賞固有条件パーツ研究"],["選択理由","この会話で専用検証と予想を指定"],
            ["使用モデル",f"mile-specific-hcw-v1:N+C+W／同名2003〜2025年23開催／設定SHA {x['config_sha256'][:12]}"],
            ["予想作成時刻",jst(x["created_at"])],["予想の状態","発走前・前日情報による研究用最終案。当日15時までの更新確認が残る"],
            ["確率の意味","各馬の3着内参考確率。未校正。◎は1着指定ではない"]]), "",
        "## 2. 入力データの状態", "",table(["材料","観測時刻","確認結果・不足"],[
            ["出馬表・取消",jst(x["card"]["observed_at"]),"公式現在欄18頭。15は出走扱い。APIの過去欄由来withdrawnを訂正"],
            ["過去走・競走条件","11/20監査、11/21再照合","国内229走・非JRA10走。全18頭の直近72走は変更なし。海外前走は1=77日、4=98日"],
            ["馬場・馬体重",jst(x["card"]["observed_at"]),"翌日対象のため未発表。係数として未使用。取消・体調情報と併せ当日確認が必要"],
            ["単勝オッズ",jst(odds["fetched_at"]),"18頭。前日価格、締切価格ではない"],
            ["ワイド・3連複オッズ",jst(odds["fetched_at"]),"全153組・816組。主案4点を下記表示"],
            ["補助券種オッズ","未取得","補助案なし"]]), "",
        "## 3. 全頭評価", "",table(["評価順位","印","馬番・馬名","3着内参考確率","単勝オッズ・人気","市場人気との差"],[
            [r["rank"],r["mark"],f"{int(r['horse_no'])} {r['horse_name']}",f"{r['probability_top3']:.1%}",f"{win[str(int(r['horse_no']))]['odds']}倍・{popular[str(int(r['horse_no']))]}人気",popular[str(int(r["horse_no"]))]-r["rank"]] for r in rows]),
        "", "差は人気順位−評価順位。期待値ではありません。16と18は同確率で、表示順は馬番順です。", "",
        "## 4. 使用パーツと評価の根拠", "",table(["条件群","今回使った条件","過去の根拠","今回の評価への影響"],[
            ["基本属性","年齢・枠","比較Gで計算、主案では不使用","主案への寄与なし"],
            ["前哨戦経路","前走の格×着順C","前走GI1着は5/7頭が3着内。縮約20で過信を抑制","2と1へ正の寄与。7件と少なく海外の同等性は未検証"],
            ["直近成績と間隔","専用N：2=前走1着・189日、1=前走1着・77日、12=前走2着・56日","前走1着22/70、2〜3着等の全根拠をJSON保存","直近着順と間隔を合算。2の長期休養は評価を下げる側にも反映"],
            ["条件変更","再対戦相対斤量W","国内同時出走の相手別最新対戦。未対戦は欠測で差分0","2は先着相手との斤量差変化『概ね同じ』。1は未対戦でW=0"],
            ["過去実績","舞台・マイルGI実績","比較特徴として保存","選択N+C+Wには直接不使用。未使用の実績を印の理由に足さない"]]), "",
        "2は前走GI勝利が主な加点。ただし約半年ぶりで、馬体重・仕上がり確認が残ります。1は海外GI勝利と実前走間隔を接続した評価で、日本初戦の不確実性があります。国内履歴だけなら12位になり、海外接続で2位へ動くため、数値を確定的な能力差とは扱いません。",
        "12はスプリンターズS2着からの56日で上位。1600mへの延長適性をこの選択版が十分に評価したとはいえません。", "",
        f"検証：16固定方式・288予測。開発2008〜2020年だけでN+C+Wを選択。参照済み2021〜2025年のBrierは0.144300→0.135336（{c['brier_relative_improvement']:.2%}改善）、5/5年改善。上位3捕捉は合計5→6頭、上位6捕捉は7→11頭。一方、最上位3着内率は60%→40%。参考条件は満たしましたが、既知期間の追加研究なので独立な優位・収益性の実証ではありません。", "",
        "## 5. 市場比較と採否", "",table(["対象馬","モデル評価","市場評価","扱い","理由"],[
            [lookup[h]["horse_name"],f"{lookup[h]['rank']}位・{lookup[h]['probability_top3']:.1%}",f"{win[h]['odds']}倍・{popular[h]}人気","主案外" if h == "14" else "含める",
             "前走GI4着などで11位。人気だけで印を変更しない。能力否定ではない" if h == "14" else "固定版の上位3頭。市場順位との差を期待値としない"] for h in ("14","2","1","12")]), "",
        "## 6. 主案の検証用仮想買い目", "",f"主案ID：{x['plan']['plan_id']}／規則：mile-hcw-w3t1-equal100-v1／評価対象はこの主案のみ。", "",
        table(["券種","組合せ","実オッズ","仮想金額","採用理由"],[
            ["ワイド" if t["bet_type"] == "wide" else "3連複","−".join(t["selection"]),
             f"{t['observed_odds']['min']}〜{t['observed_odds']['max']}" if t["bet_type"] == "wide" else t["observed_odds"]["value"],
             "100円","評価上位3頭の固定比較"] for t in x["plan"]["tickets"]]), "",
        f"合計400円の仮想検証。価格観測 {jst(odds['fetched_at'])}。実購入0円。組の確率・期待値は未計算です。", "",
        "## 7. 補助案・追加仮説", "",table(["案ID","券種・組合せ","実オッズ","仮想金額","仮説・根拠","評価上の扱い"],[["なし","追加なし","非適用","0円","着順確率を推定していないため3連単固定を追加しない","主案のみ評価"]]), "",
        "## 8. 保存状況", "",table(["項目","状態"],[
            ["予想ID",x["prediction_id"]],["主案・入力・表示全文","SQL保存・全文読戻し後に公開。研究ファイルも保存"],
            ["事前保存の確認","発走前。明日の結果は未取得"],["自動評価の対応","ワイド・3連複の研究独自主案は共通評価器へ未接続。結果後は保存した4点を別精算"]]), "",
        "## 9. 結果検証", "",table(["評価項目","結果"],[
            ["公式結果・払戻","未確定・未取得"],["モデル評価と実際の3着内馬","未確定"],["主案：仮想購入額・払戻・回収率","仮想400円・払戻/回収率は未確定"],
            ["券種別的中・トリガミ","未確定"],["補助仮説","追加案なし"]]), "",
        "## 10. 断層競馬の独立参考", "", "未判定。本体へ混入していません。", ""]
    return "\n".join(lines)


def main() -> int:
    """全頭・主案・本文を一つの構造から凍結しSQL保存用payloadを作る。"""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs","research","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    require(not args.output.exists(),"mile_forecast_output_exists")
    card = read(args.inputs/"normalized-card.json")
    require(datetime.now(timezone.utc) < datetime.fromisoformat(card["start_at"]),"mile_forecast_after_start")
    live = read(args.research/"live-comparison.json")["international_connected"]
    summary = read(args.research/"summary.json")
    require(live["forecast"]["pattern"] == "N+C+W","mile_render_selected_changed")
    odds = read(args.inputs/"odds-summary.json")
    require(odds["race_id"] == card["race_key"],"mile_odds_identity")
    rows = live["forecast"]["runners"]
    require({r["horse_id"] for r in rows} == {r["horse_id"] for r in card["runners"] if r["status"] == "active"},"mile_forecast_roster")
    for i,r in enumerate(rows,1):
        r.update(rank=i,mark="◎" if i == 1 else "○" if i == 2 else "▲" if i == 3 else "△" if i <= 6 else "―")
    top = [str(int(r["horse_no"])) for r in rows[:3]]
    now = datetime.now(timezone.utc).isoformat()
    pid = "jra-mile-hcw-20261122-"+uuid.uuid4().hex
    tickets = []
    for bet,selections in (("wide",list(combinations(top,2))),("trio",[tuple(top)])):
        for selection in selections:
            row = next(r for r in odds["odds"][bet] if set(r["combination"]) == set(selection))
            price = {"min":row["odds_min"],"max":row["odds_max"]} if bet == "wide" else {"value":row["odds"]}
            require(all(v is not None and float(v)>0 for v in price.values()),"mile_ticket_price")
            tickets.append({"bet_type":bet,"selection":sorted(selection,key=int),"amount":100,"observed_odds":price,"observed_at":odds["fetched_at"]})
    plan = {"plan_id":pid+"-w3t1","policy_id":"mile-hcw-w3t1-equal100-v1","virtual_only":True,"status":"pre_day_research_plan",
            "budget":400,"tickets":tickets,"price_basis":"prior_day_observed_not_final"}
    config_path = ROOT/"configs/research/mile_extension_v1.json"
    x = {"prediction_id":pid,"created_at":now,"card":card,"odds":odds,"forecast":live["forecast"],"plan":plan,
         "confirmation":summary["confirmation"],"config_sha256":hashlib.sha256(config_path.read_bytes()).hexdigest()}
    presentation = render(x)
    x["presentation"] = presentation
    payload = {"prediction_id":pid,"race_id":card["race_key"],"theory_version":"condition_parts:mile-specific-hcw-v1:N+C+W",
        "mode":"condition_parts_mile_specific","budget":0,"created_at":now,"pre_race_snapshot":{"card":card,"odds":odds,"official_current_card":read(args.inputs/"official-parsed-card.json")},
        "prediction_json":{"method_selection":{"method":"condition_parts","source":"conversation","reason":"利用者が重賞固有検証と最終予想を指定","model":"mile-specific-hcw-v1:N+C+W"},
            "selected_model":{"id":"mile-specific-hcw-v1","pattern":"N+C+W","config_sha256":x["config_sha256"],"training_period":[2003,2025],"status":"exploratory_research_not_independently_validated","purchase_approved":False},
            "input_state":{"card_observed_at":card["observed_at"],"odds_observed_at":odds["fetched_at"],"body_weight":"not_announced","race_going":"not_announced","international_history_connected":True,"tomorrow_update_pending":True},
            "condition_parts_forecast":x["forecast"],"condition_parts_evidence":live["evidence"],"condition_parts_plan":plan,"condition_parts_alternatives":[],
            "condition_parts_sensitivity":{"file":str((args.research/"live-comparison.json").resolve()),"sha256":hashlib.sha256((args.research/"live-comparison.json").read_bytes()).hexdigest()},
            "presentation":{"text":presentation,"template_version":"condition-parts-output-v1"},"predicted_top3":top,"finish_order_prediction_available":False,
            "axis_horse_numbers":[top[0]],"opponent_horse_numbers":top[1:],"generated_before_result":True,"reconstruction_after_result":False},"prediction_tickets":[]}
    args.output.mkdir(parents=True)
    save(args.output/"prediction.json",x); save(args.output/"payload.json",payload)
    (args.output/"presentation.md").write_text(presentation,encoding="utf-8")
    paths = [Path(__file__),config_path,args.inputs/"normalized-card.json",args.inputs/"official-parsed-card.json",args.inputs/"odds-summary.json",args.research/"summary.json",args.research/"live-comparison.json"]
    save(args.output/"manifest.json",{"created_at":now,"inputs":{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "outputs":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
    print(json.dumps({"prediction_id":pid,"top3":top,"virtual_yen":400,"purchase_yen":0},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
