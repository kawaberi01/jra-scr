"""概要: 東京10Rの最新公式入力から指定または既定モデルの予想本文を発走前保存する。
作成日: 2026-10-25
入力: 任意--model、公式カード/単勝/馬連、モデル設定、既存履歴準備、共通SQL設定。
出力: 新規セッション先へ原本・取消除外入力・表示本文・SQL/API読戻し証跡。
実行例: uv run --extra ml python .workstate/jra-srb/sqlserver-model-data-audit/predict_tokyo10_20261025.py --model J23
注意事項: 明示取消馬の行だけ除外。実価格/確率の補完・結果取得・実購入・再学習なし。
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import jra_selected_model as workflow
from jra_srb.jra_model_selection import resolve_model, read_json, sha256

BASE_RENDER = workflow.render


def render_readable(payload):
    """保存済み構造化値だけから、日本語テンプレートの読みやすい本文を作る。"""
    BASE_RENDER(payload)
    p, snapshot = payload["prediction_json"], payload["pre_race_snapshot"]
    model, forecast, state = p["selected_model"], p["forecast"], p["input_state"]
    card, conditions, names = snapshot["card"], p["race_conditions"], forecast["horse_names"]
    rows = p["predicted_ranking"]
    label = forecast.get("case", model["name"])
    selection = "明示指定" if model["selection_source"] == "explicit" else "設定の既定"
    start = model.get("training_start") or "開始日不明"
    weight = {"unpublished": "未発表", "available": "取得済み"}.get(state["horse_weight"], state["horse_weight"])
    lines = ["### レース情報", f"2026年10月25日 東京10R・{card['race_name']}／{card['surface']}{card['distance']}m／{card['start_time']}発走。",
        f"天候：{conditions['weather_label']}、馬場：{conditions['track_condition_label']}。有効{len(rows)}頭。3番ブラックルビーは取消。",
        "### 予想モード", "総合買い目型・研究参考予想。",
        "### 使用モデル", f"**{model['name']}／{model['version']}**（{selection}）。学習：{start}〜{model['trained_through']}。研究利用可・購入推奨不可。" + model.get("training_period_note", ""),
        "馬連確率と2着内周辺確率を予測します。以下は着順予想・単勝勝率ではありません。",
        "### 取得時点・データ状態", f"カード：{state['card']['observed_jst']}／オッズ：{state['odds']['observed_jst']}。馬体重：{weight}。",
        "### 使用データと欠損", "公式カード、取消除外後の実単勝・馬連オッズ、履歴特徴を使用。対象馬の直近走は照合済みですが、モデル用履歴の全場最終日は10/4で、全場最新性は未確認です。",
        "### 当日傾向", "今回の追加取得はなし。本体への反映もなし。",
        "### 熱さ判定", "購入の熱さは未判定。研究参考に限定します。",
        "### 予想順位", "**2着内周辺順位**（着順・勝率順位ではありません）。", "| 順位 | 印 | 馬番 | 馬名 | 2着内周辺確率 |",
        "|---|---|---:|---|---:|"]
    for index, row in enumerate(rows, 1):
        lines.append(f"| {index} | {row['mark'] or '—'} | {int(row['horse_no'])} | {names[row['horse_no']]} | {row['top2_probability']:.2%} |")
    axis = p["axis_horse_numbers"][0]
    opponents = "、".join(f"{int(h)} {names[h]}" for h in p["opponent_horse_numbers"])
    lines += ["### 予想の根拠", f"参考軸は**{int(axis)} {names[axis]}**。{label}の2着内周辺確率が最上位です。参考相手は{opponents}。頭候補は設定しません。",
        "各馬の能力要因別の寄与は未計算のため、時計・適性等の具体的な優劣は断定しません。",
        "馬連の参考上位（購入指示ではありません）：", "| 組合せ | 馬連予測確率 | 実オッズ |", "|---|---:|---:|"]
    for row in p["pair_references"]:
        lines.append(f"| {'－'.join(str(int(h)) for h in row['horses'])} | {row['probability']:.2%} | {row['odds']}倍 |")
    lines += ["### V系評価", "未取得。本体順位への適用なし。", "### 評価系統の比較",
        "追加モデルは未取得。同じ市場情報を使うモデル同士の一致を独立した根拠にはしません。",
        "### 買い方", f"**見送り・購入0円。** {label}の購入推奨は不採用または未承認です。参考ペアを買い目へ変換しません。",
        f"オッズ取得時点：{state['odds']['observed_jst']}。採用買い目なし。",
        "### 予算別の買い方", "1000円・2000円・3000円とも購入0円。",
        "### マークシート向け", "記入対象なし。", "### 注意点",
        "予測精度・安定利益の優位は未証明。今回の観測を発走直前の最新情報とは扱いません。",
        "### 断層競馬参考", "#### ■ 断層競馬", "本体とは独立した参考です。順位・印・買い目を上書きしません。",
        "#### ■ 取得時点", state["odds"]["observed_jst"], "#### ■ 上位1〜6人気"]
    d = p["dansou_reference"]
    lines += [f"{i}番人気：{int(h)} {names[h]}（{price}倍）" for i, (h, price) in enumerate(d.get("top6", []), 1)]
    lines += ["#### ■ 断層チェック", "隣接倍率：" + "／".join(f"{r:.2f}" for r in d.get("ratios", [])) + f"。パターン：{d.get('pattern') or '断層なし'}。",
        "#### ■ 総合判定", "見送り（独立参考）。", "#### ■ 単勝",
        f"参考候補：{int(d['reference_win_candidate'])} {names[d['reference_win_candidate']]}。購入提案には含めません。" if d.get("reference_win_candidate") else "配当フィルターを満たす参考候補なし。",
        "#### ■ 3連複", "見送り。組合せオッズ・購入根拠を確認していません。",
        "#### ■ 追加提案", "ワイド・馬連の追加提案なし。", "#### ■ 補助材料", "追加比較未取得。",
        "#### ■ 見送り条件", "変動未確認。補助材料・購入根拠不足。",
        "予想保存済み。", f"prediction_id：`{payload['prediction_id']}`"]
    # 表を分断せず、段落と見出しの間だけ空行を置く。
    return ("\n\n".join(lines) + "\n").replace("|\n\n|", "|\n|")


def run(requested=None):
    """最新入力の準備・明示取消の除外・選択モデル推論・表示保存と全文照合を実行する。"""
    now = datetime.now(timezone.utc)
    model = resolve_model(requested)
    out = ROOT / "artifacts/predictions" / ("20261025-tokyo10-" + model["id"] + "-session-" + now.strftime("%Y%m%dT%H%M%SZ"))
    out.mkdir(exist_ok=False)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=20) as client:
        source = workflow.acquire_snapshot(client, "2026-10-25", "tokyo", 10, model, out / "snapshot")
        card, odds = read_json(source / "official-card.json"), read_json(source / "official-odds.json")
        active = {str(r["horse_no"]).zfill(2) for r in card["runners"] if r["status"] == "active"}
        inactive = [r for r in card["runners"] if r["status"] != "active"]
        assert all(r["status"] in ("withdrawn", "excluded") and r["status_source"] == "explicit" for r in inactive)
        target = out / "active-snapshot"
        (target / "input").mkdir(parents=True, exist_ok=False)
        for name in ("official-card.json", "input/input.json", "input/quality.json"):
            shutil.copy2(source / name, target / name)
        if model["adapter"] == "j23_frozen":
            shutil.copy2(source / "input/j23_public_features.json", target / "input/j23_public_features.json")
        counts = {}
        for kind, rows in odds["odds"].items():
            keep = [r for r in rows if r["combination"] and all(str(h).zfill(2) in active for h in r["combination"])]
            odds["odds"][kind] = keep
            counts[kind] = {"original": len(rows), "active_only": len(keep)}
        odds["normalization"] = {"source_sha256": sha256(source / "official-odds.json"), "counts": counts,
            "rule": "公式の明示取消馬を含む行だけ除外。値の補完なし", "observation_time_unchanged": True}
        if odds.get("entries"):
            odds["entries"] = [r for r in odds["entries"] if r["combination"] and all(str(h).zfill(2) in active for h in r["combination"])]
        workflow.write_json(target / "official-odds.json", odds)
        payload = workflow.predict(model, target, out / "draft", course="tokyo")
        prices = {tuple(sorted(str(h).zfill(2) for h in row["combination"])): row["odds"] for row in odds["odds"]["quinella"]}
        p = payload["prediction_json"]
        p["pair_references"] = [{**row, "odds": prices[tuple(sorted(row["horses"]))], "observed_at": odds["fetched_at"]} for row in p["forecast"]["pair_ranking"][:3]]
        workflow.render = render_readable
        p["presentation_markdown"] = render_readable(payload)
        workflow.write_json(out / "prediction_payload.json", payload)
        with (out / "presentation.md").open("x", encoding="utf-8") as stream:
            stream.write(p["presentation_markdown"])
        receipt = workflow.save_prediction(payload, client)
        workflow.write_json(out / "save-verification.json", receipt)
        print(json.dumps({"output": str(out), **receipt}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    args = parser.parse_args()
    os.environ.setdefault("JRA_SRB_STORAGE_ENV_FILE", str(ROOT / "data/storage/runtime.env"))
    run(args.model)
