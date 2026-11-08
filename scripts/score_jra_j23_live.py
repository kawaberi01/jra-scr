"""概要: 固定J23・Q03/Q06の1競走参考保存と独立した発走後比較を実行する。
作成日: 2026-10-23
入力: scoreの開催属性/native API ID/任意--save、evaluateの元run ID。
出力: 新規研究run、標準出力、--save時だけ共通SQL参考予想。
実行例: uv run --frozen --extra ml python -X utf8 scripts/score_jra_j23_live.py score --help
注意事項: SQL receiptが事前収集済みであること。自動取得・再学習・実購入なし。
"""

import argparse
import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_j23_live import evaluate, execute
from jra_srb.jra_research_r1_live import COURSES


def main():
    """開催属性を明示した1競走を処理し、秘密を除いた結果または失敗理由を表示する。"""
    parser = argparse.ArgumentParser(description='J23・Q03/Q06のSQL受領入力による動作検証。公表時点未証明のため性能評価対象外。')
    commands = parser.add_subparsers(dest='command', required=True)
    score = commands.add_parser('score', help='当日のSQL保存済み公式カード/単勝/馬連から参考推論')
    score.add_argument('--date', required=True)
    score.add_argument('--course', required=True, choices=COURSES)
    score.add_argument('--race-no', required=True, type=int)
    score.add_argument('--race-id', required=True)
    score.add_argument('--save', action='store_true', help='実購入券を作らずSQL参考予想を保存し読み戻す')
    result = commands.add_parser('evaluate', help='元runを変更せずSQL保存済み公式結果で精算')
    result.add_argument('--run-id', required=True)
    args = parser.parse_args()
    try:
        output = (execute(args.date, args.course, args.race_no, args.race_id, save=args.save)
                  if args.command == 'score' else evaluate(args.run_id))
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError('j23_cli_failed', 4, error_type=type(error).__name__)
        print(json.dumps({'status': 'failed', 'reason': safe.reason, 'details': safe.details}, ensure_ascii=False))
        raise SystemExit(safe.exit_code) from None


if __name__ == '__main__':
    main()
