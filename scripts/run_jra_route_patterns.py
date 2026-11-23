"""概要: マイルCSの経路42条件と消去6条件を固定して検証・根拠保存する。
作成日: 2026-11-22
入力: --dataset、--card、--history、--foreign、--output。
出力: 48条件の期間別/年別成績、全馬判定、今年該当馬、レポート、SHA。
実行例: uv run python scripts/run_jra_route_patterns.py --help
注意事項: オフライン。既存予想/主案/DBは変更せず、新規保存先だけへ出力する。
"""

from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from jra_srb.jra_route_patterns import examples,evaluate,live,summarize
from jra_srb.jra_race_conditions import require


def read(path: Path):
    """UTF-8 JSONを読み込む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path,value) -> None:
    """新規JSONへ根拠と丸め前指標を保存する。"""
    with path.open("x",encoding="utf-8") as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)


def fraction(value) -> str:
    """欠測の率を0%へ置き換えず表示する。"""
    return "不明" if value is None else f"{value:.1%}"


def report(result: dict,current: list[dict]) -> str:
    """全48条件の分母・例外・今年の該当を固定構成で比較表示する。"""
    lines=["# マイルCS 経路・消去パターン48条件", "", "## 読み方", "",
        "経路の参加・成績・順序を同一馬IDと対象日前の履歴だけで判定。直前は歴年DBでの最終収録国内走であり、海外欠落を含みうる。該当なしを完全な未出走証明にしない。年齢上限超過は現在属性の非該当。",
        "不明は消さず残す。勝率ゼロを将来勝率ゼロとしない。以下は結果との記述的関係であり、因果・未知性能・回収率の証明ではない。", "",
        "## 全期間2003〜2025年", "", "|条件|該当：出走/勝利/3着内|該当勝率|該当3着内率|非該当：出走/勝利/3着内|不明頭数|", "|---|---:|---:|---:|---:|---:|"]
    for p in result["patterns"]:
        s=p["periods"]["all"]; m,n,u=s["matched"],s["not_found"],s["unknown"]
        lines.append(f"|{p['label']}|{m['runners']}/{m['wins']}/{m['top3']}|{fraction(m['win_rate'])}|{fraction(m['top3_rate'])}|{n['runners']}/{n['wins']}/{n['top3']}|{u['runners']}|")
    lines += ["", "## 開発と参照済み確認を分離", "", "|条件|開発：該当出走/勝利/3着内|確認：該当出走/勝利/3着内|確認：消すと落ちる勝ち馬|", "|---|---:|---:|---|"]
    for p in result["patterns"]:
        d=p["periods"]["development"]["matched"]; c=p["periods"]["confirmation"]; m=c["matched"]
        exceptions="、".join(f"{r['race_date'][:4]} {r['horse_name']}" for r in c["excluded_winners"]) or "なし（必要条件の証明ではない）"
        lines.append(f"|{p['label']}|{d['runners']}/{d['wins']}/{d['top3']}|{m['runners']}/{m['wins']}/{m['top3']}|{exceptions}|")
    selected=result["selected_elimination_pattern"]
    lines += ["", "## 消去候補の判定", "", f"開発年だけで固定した消去候補: {selected['label'] if selected else 'なし'}。",
        "条件は開発13年の勝ち馬全保持、該当20頭以上・5開催以上、平均残存70%以下。確認5年で別候補へ差替えない。採用False。勝ち馬保持と2・3着保持を分ける。", "",
        "## 保存済み2026カードへの照合", "", "11/21公式確認版18頭。最新取消・当日馬場・馬体重・価格はこの研究では未更新。海外実前走は別参照レコードで接続。", "",
        "|馬番・馬名|直前経路の該当|同年好走/順序/前年の該当|属性/直前成績の該当|", "|---|---|---|---|"]
    for r in current:
        matched=[p for p in result["patterns"] if r["patterns"][p["id"]]["matched"] is True]
        labels=lambda kinds:"、".join(p["label"] for p in matched if p["kind"] in kinds) or "収録内該当なし/不明"
        lines.append(f"|{int(r['horse_no'])} {r['horse_name']}|{labels(('previous',))}|{labels(('same_year','sequence','previous_year'))}|{labels(('age_max','previous_result'))}|")
    lines += ["", "## 今回の扱い", "", "48条件は実行前に固定。全条件の支持数・反例を保存し、よい数字だけ選ばない。今年の確率・順位・仮想主案は上書きしていない。条件の組合せ探索、未知年の独立評価、回収率は未実施。", ""]
    return "\n".join(lines)


def main() -> int:
    """入力のSHAを確認し、固定条件の分析を未使用出力先へ保存する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("dataset","card","history","foreign","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    require(not args.output.exists(),"route_output_exists")
    args.output.mkdir(parents=True)
    try:
        sha=hashlib.sha256(args.dataset.read_bytes()).hexdigest()
        require(read(args.dataset.parent/"manifest.json")["files"][args.dataset.name]==sha,"route_dataset_sha")
        rows=examples(read(args.dataset)); result=evaluate(rows)
        require(len(rows)==402 and sum(r["rank"]==1 for r in rows)==23,"route_target_counts")
        current=live(read(args.card),read(args.history),read(args.foreign))
        annual=[{"pattern_id":p["id"],"year":year,**summarize([r for r in rows if r["race_date"][:4]==str(year)],p["id"])} for p in result["patterns"] for year in range(2003,2026)]
        for name,value in (("examples",rows),("summary",result),("current",current),("annual",annual)):
            save(args.output/(name+".json"),value)
        (args.output/"report.md").write_text(report(result,current),encoding="utf-8")
        inputs=[Path(__file__),args.dataset,args.card,args.history,args.foreign,ROOT/"src/jra_srb/jra_route_patterns.py",ROOT/"src/jra_srb/jra_specific_patterns.py",
            ROOT/".workstate/jra-srb/mile-championship-specific-research/spec/050-前哨戦経路パターン検証仕様.md"]
        save(args.output/"manifest.json",{"created_at":datetime.now(timezone.utc).isoformat(),"inputs":{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
            "outputs":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
        print(json.dumps({"patterns":len(result["patterns"]),"runner_editions":len(rows),"annual_summaries":len(annual),
            "selected_elimination":result["selected_elimination_pattern"]["label"] if result["selected_elimination_pattern"] else None},ensure_ascii=False))
        return 0
    except Exception as error:
        save(args.output/"failure.json",{"type":type(error).__name__,"reason":getattr(error,"reason",str(error))})
        raise


if __name__=="__main__":
    raise SystemExit(main())
