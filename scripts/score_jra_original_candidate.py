"""概要: 固定V110/J23を明示指定し、保存入力から研究参照を新規保存する。
作成日: 2026-10-23
入力: --candidate、--inputの来歴付きJSON、--outputの新規dir。
出力: 全馬連確率・原型最大1点と実購入0の参照JSON。成功0、入力不正2、失敗4。
実行例: uv run --frozen --extra ml python scripts/score_jra_original_candidate.py --candidate J23 --input input.json --output artifacts/reference/new-run
注意事項: SQL/HTTP/学習/実購入なし。既定方式なし、既存出力は上書きしない。
"""

import argparse
import json
from pathlib import Path

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_original_candidate import execute


def main(argv=None):
    """必須の候補と入出力を受け取り、非秘密の結果か理由コードを返す。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', choices=['V110', 'J23'], required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = execute(args.input, args.output, args.candidate)
        print(json.dumps({k: result[k] for k in ('candidate', 'race_id', 'status', 'chosen',
                                                'candidate_stake_yen', 'stake_yen', 'adopted')}, ensure_ascii=False))
        return 0
    except ResearchError as error:
        print(json.dumps({'status': 'failed', 'reason': error.reason}, ensure_ascii=False))
        return error.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
