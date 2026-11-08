"""概要: 30仮説の研究実行・再開・保存結果検証を起動する。
作成日: 2026-10-22
入力: --resume run ID、--verify run ID（いずれも任意）。
出力: artifacts/jra_research/runsのモデル・台帳・結果、理由コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera_thirty.py
注意事項: SQL読取のみ。接続情報・例外全文を標準出力へ表示しない。
"""
import argparse
import codecs
import json
import os
from pathlib import Path
import sys

# BLASの初期予約も抑えるため、数値ライブラリ/ODBCより先に固定する。
for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_variable] = '1'

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def main():
    """依存とcodecを先行初期化してから、保護された専用研究処理を実行する。"""
    import mssql_python  # noqa: F401
    import mssql_python_odbc  # noqa: F401
    for encoding in ('utf-16-le', 'cp932', 'utf-8-sig'):
        codecs.lookup(encoding)
    from jra_srb import jra_research_chimera_thirty as research
    from jra_srb.jra_research_contracts import ResearchError
    from jra_srb.jra_research_artifacts import existing_run
    from jra_srb.jra_research_tipster_smoke import install_input_guard
    parser = argparse.ArgumentParser(description='固定30仮説×30月研究')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--resume')
    group.add_argument('--verify')
    args = parser.parse_args()
    install_input_guard()
    try:
        result = research.verify(existing_run(args.verify)) if args.verify else research.run(args.resume)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'reason': error.reason if isinstance(error, ResearchError) else type(error).__name__}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
