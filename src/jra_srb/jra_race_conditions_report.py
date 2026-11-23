"""概要: 条件予想の比較表・説明・検証結果を再現可能な研究成果物へ保存する。
作成日: 2026-11-08。
入力: 条件設定、解析済みデータ、計算結果、未使用の明示出力先。
出力: JSON、UTF-8 BOM付きCSV、Markdown、SHA付きmanifest、失敗証跡。
実行例: uv run python scripts/run_jra_race_conditions.py analyze --help
注意事項: 既存フォルダーを上書きしない。原文本文と認証情報は出力しない。
"""

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .jra_race_conditions import FEATURE_LABELS, require
from .jra_research_contracts import digest


RACE_COLUMNS = ["race_distance", "track_code", "field_size", "race_grade", "race_type", "race_symbol",
                "race_weight_rule", "weather", "turf_going", "dirt_going"]


class Outputs:
    """未使用フォルダーの成果物と状態遷移を管理する。"""

    def __init__(self, path: str | Path, command: str, config: dict):
        """新規出力先を確保し、設定とrunning状態を先に保存する。"""
        self.path = Path(path).resolve()
        require(not self.path.exists(), "conditions_output_exists")
        self.path.mkdir(parents=True, exist_ok=False)
        self.manifest = {"status": "running", "command": command, "protocol": config["profile_id"],
                         "config_sha256": digest(config), "created_at_utc": datetime.now(timezone.utc).isoformat()}
        self.json("config.json", config)
        self._manifest()

    def _manifest(self) -> None:
        """自分が新規作成したmanifestだけを更新し、処理状態を記録する。"""
        (self.path / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                                 encoding="utf-8")

    def json(self, name: str, value) -> None:
        """単一の新規JSONをUTF-8と有限数値で保存する。"""
        require(Path(name).name == name and name.endswith(".json"), "conditions_output_name")
        with (self.path / name).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")

    def csv(self, name: str, rows: list[dict], fields: list[str]) -> None:
        """Excelでも日本語が判別しやすいUTF-8 BOM付きの固定列CSVを保存する。"""
        require(Path(name).name == name and name.endswith(".csv"), "conditions_output_name")
        with (self.path / name).open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)

    def markdown(self, text: str) -> None:
        """研究レポートをUTF-8の新規Markdownへ保存する。"""
        with (self.path / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)

    def finish(self, **details) -> None:
        """全成果物を読み直してSHAを計算し、成功状態にする。"""
        require(self.manifest["status"] == "running", "conditions_output_transition")
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.path.iterdir())
                 if p.is_file() and p.name != "manifest.json"}
        code = [Path(__file__).with_name(name) for name in (
            "jra_race_conditions.py", "jra_race_conditions_sql.py", "jra_race_conditions_report.py")]
        cli = Path(__file__).resolve().parents[2] / "scripts/run_jra_race_conditions.py"
        self.manifest.update(details, status="complete", files_sha256=files,
                             code_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [*code, cli]},
                             finished_at_utc=datetime.now(timezone.utc).isoformat())
        self._manifest()

    def fail(self, error) -> None:
        """例外本文を出さず、固定理由と型だけで失敗を記録する。"""
        failure = {"reason": getattr(error, "reason", "conditions_execution_failed"), "error_type": type(error).__name__}
        allowed = {"query_id", "sqlstate", "error_type", "phase", "elapsed_seconds", "parameter_count"}
        failure["diagnostic"] = {k: v for k, v in getattr(error, "details", {}).items() if k in allowed}
        self.json("failure.json", failure)
        self.manifest.update(status="failed", failure=failure)
        self._manifest()


def condition_rows(result: dict) -> list[dict]:
    """各年・各条件の該当と非該当を全カテゴリについて集計する。"""
    output = []
    for race in result["comparison_rows"]:
        total = len(race["rows"])
        successes = sum(r["outcome"]["top3"] for r in race["rows"])
        for name, label in FEATURE_LABELS.items():
            groups = defaultdict(list)
            for row in race["rows"]:
                groups[row["values"][name]].append(row)
            for value, matched in sorted(groups.items(), key=lambda x: str(x[0])):
                success = sum(r["outcome"]["top3"] for r in matched)
                output.append({"race_key": race["race_key"], "year": race["race_date"][:4], "venue_code": race["venue_code"],
                    "feature": name, "label": label, "value": value if value is not None else "未確認",
                    "n": len(matched), "top3": success, "rate": success / len(matched),
                    "nonmatched_n": total-len(matched), "nonmatched_top3": successes-success,
                    "evaluation_eligible": race["evaluation_eligible"]})
    return output


def comparison_rows(result: dict) -> list[dict]:
    """各年の全馬を条件と結果へ対応させ、取消等も除外理由付きで残す。"""
    output = []
    for race in result["comparison_rows"]:
        conditions = race.get("conditions", {})
        context = {"race_distance": race["distance"], "track_code": race["track_code"], "field_size": len(race["rows"]),
                   **{"race_" + name: conditions.get(name) for name in ("grade", "type", "symbol", "weight_rule")},
                   **{name: conditions.get(name) for name in ("weather", "turf_going", "dirt_going")}}
        context["race_type"] = conditions.get("race_type")
        for row in race["rows"]:
            output.append({"race_key": race["race_key"], "race_date": race["race_date"], "venue_code": race["venue_code"],
                "horse_no": row["horse_no"], "horse_id": row["horse_id"], "horse_name": row["horse_name"],
                "status": "active", "rank": row["outcome"]["rank"], "top3": row["outcome"]["top3"],
                "history_count": row["history_count"], "latest_stored_race": row["latest_stored_race"], **context, **row["values"]})
        for row in race["excluded"]:
            output.append({"race_key": race["race_key"], "race_date": race["race_date"], "venue_code": race["venue_code"],
                "horse_no": row["horse_no"], "horse_id": row["horse_id"], "horse_name": row["horse_name"],
                "status": "excluded:" + row["abnormal_code"], "rank": row.get("rank"), "top3": None,
                "history_count": None, "latest_stored_race": None, **context, **dict.fromkeys(FEATURE_LABELS)})
    return output


def _text(value) -> str:
    """表セルの区切り・改行をエスケープする。"""
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _prediction_section(prediction: dict) -> list[str]:
    """結論と実際の計算に対応した最大3根拠を短い表にする。"""
    lines = [f"## {prediction['race_date']} の評価", "", "推定3着内確率は未校正の研究値です。同確率は馬番順に表示します。", "",
             "| 表示順 | 馬 | 推定3着内確率 | 評価に影響した条件群 |", "|---:|---|---:|---|"]
    for row in prediction["runners"]:
        evidence = " / ".join(f"{e['group']} {e['probability_difference_pp']:+.2f}pt" for e in row["explanations"])
        lines.append(f"| {row['display_order']} | {_text(row['horse_no'])} {_text(row['horse_name'])} | "
                     f"{row['probability_top3']:.1%} | {_text(evidence)} |")
    lines.extend(["", "ptはその条件群を外して全馬を再計算した際の差です。因果効果ではなく、差の単純合算もできません。", ""])
    if prediction["runners"]:
        top = prediction["runners"][0]
        lines.extend([f"### 上位表示馬 {_text(top['horse_name'])} の根拠", ""])
        for impact in top["explanations"]:
            group = next(g for g in top["groups"] if g["group"] == impact["group"])
            conditions = "; ".join(f"{e['label']}={e['value']}：{e['top3']}/{e['n']}行・{e['years']}開催年"
                                    for e in group["evidence"])
            lines.append(f"- {_text(group['group'])}：{_text(conditions) if conditions else '過去の対応カテゴリなし'}。未確認{group['unknown_count']}項目。")
        lines.extend(["", f"DB内履歴は{top['history_count']}走、直近確認日は{top['latest_stored_race'] or '未確認'}。"
                      "前走が本当に最新か、海外・地方の欠損がないかは別確認が必要です。", ""])
    return lines


def render_report(result: dict, coverage: dict) -> str:
    """性能・母集団・制約と最新過去年の出力例を同じレポートにまとめる。"""
    lines = ["# エリザベス女王杯の既知条件による研究結果", "",
             f"保存済み{coverage['race_count']}開催、対象{coverage['target_rows']}行、対象馬の保存履歴{coverage['history_rows']}行を使用。",
             "各年より前の同名競走で集計し、過去5開催に満たない年は予想の評価対象から外しています。", "",
             "## 一律基準と条件予想の比較", "", "| 方式 | 評価開催 | 出走行 | Brier | logloss | 上位1頭の3着内率 | 上位3頭の捕捉数平均 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for variant, values in result["summary"].items():
        m = values["all"]
        if not m["races"]:
            lines.append(f"| {_text(variant)} | 0 | 0 | — | — | — | — |")
            continue
        lines.append(f"| {_text(variant)} | {m['races']} | {m['runners']} | {m['brier']:.6f} | {m['logloss']:.6f} | "
                     f"{m['top1_top3_hit']:.1%} | {m['top3_captured']:.3f} |")
    lines.extend(["", "Brier/loglossは小さいほど良い指標です。一律基準の順位指標は無作為選択の期待値です。"
                  "条件を外す比較は診断で、結果の良い方式へ自動で選び直しません。", "",
                  "## 年次と開催場の扱い", "", "京都と阪神は別集計をmetrics.jsonに保存しています。"
                  "同場の件数不足は全場の同名競走へ縮約しており、開催場の違いを無視した完全混合ではありません。", "",
                  "| 年 | 開催場 | 活動馬 | 重量コード | 種別コード | 記号コード | 天候コード | 芝馬場コード |",
                  "|---|---|---:|---|---|---|---|---|"])
    for race in result["comparison_rows"]:
        c = race.get("conditions", {})
        cells = [race["race_date"][:4], {"08": "京都", "09": "阪神"}[race["venue_code"]], len(race["rows"]),
                 *[c.get(k) or "未確認" for k in ("weight_rule", "race_type", "symbol", "weather", "turf_going")]]
        lines.append("| " + " | ".join(_text(v) for v in cells) + " |")
    lines.extend(["", "競走共通の条件は各馬への独立加点に使わず、年の比較と入力の確認に使用します。コードの定義を推測で補いません。", "",
                  "## 未確認と適用範囲", ""])
    lines.extend("- " + s for s in result["limitations"])
    lines.extend([f"- 保存RAの欠損競走は{coverage.get('ra_missing', 0)}件。欠損を推測したコードで埋めていません。",
                  "- 2026年の当日予想や購入判断をこの過去レポートから自動生成していません。", ""])
    if result["predictions"]:
        lines += _prediction_section(result["predictions"][-1])
    lines.extend(["## 保存ファイル", "", "- comparisons.csv：年ごとの馬・条件・結果。", "- conditions.csv：該当と非該当の年別件数。",
                  "- predictions.json：過去年の根拠と推定確率。", "- metrics.json：全方式・年別・開催場別の比較。",
                  "- manifest.json：設定・入力・出力・コードのSHA。", ""])
    return "\n".join(lines)


def save_analysis(outputs: Outputs, result: dict, dataset: dict) -> None:
    """全比較結果を保存し、予想だけを成功扱いせず出力を完了させる。"""
    comparisons, conditions = comparison_rows(result), condition_rows(result)
    outputs.csv("comparisons.csv", comparisons, ["race_key", "race_date", "venue_code", "horse_no", "horse_id", "horse_name",
        "status", "rank", "top3", "history_count", "latest_stored_race", *RACE_COLUMNS, *FEATURE_LABELS])
    outputs.csv("conditions.csv", conditions, ["race_key", "year", "venue_code", "feature", "label", "value", "n", "top3", "rate",
        "nonmatched_n", "nonmatched_top3", "evaluation_eligible"])
    outputs.json("predictions.json", result["predictions"])
    outputs.json("metrics.json", {k: v for k, v in result.items() if k not in ("comparison_rows", "predictions")})
    outputs.json("coverage.json", dataset["coverage"])
    outputs.markdown(render_report(result, dataset["coverage"]))
    outputs.finish(input_sha256=dataset["input_sha256"], availability="research_only",
                   evaluated_races=result["summary"]["full"]["all"]["races"])


def render_prediction(prediction: dict) -> str:
    """将来カードの参考出力に、最新性診断を明示して表示する。"""
    lines = ["# エリザベス女王杯の参考評価", "", "状態：reference_only。入力と履歴の充足を確認してから判断してください。", ""]
    lines += _prediction_section(prediction)
    lines += ["## 最新性の確認", ""]
    for row in prediction["freshness"]:
        lines.append(f"- {_text(row['horse_no'])}：{row['status']}。DB内直近日={row['latest_stored_race']}、申告直近日={row['declared_latest_race']}。")
    return "\n".join(lines) + "\n"
