"""概要: 元候補CLIの明示指定と安全なエラー応答を検証する。
作成日: 2026-10-23
入力: 合成の引数とexecute代替。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_score_jra_original_candidate.py
注意事項: SQL/HTTP/学習/実購入/成果物更新なし。
"""

import importlib.util
from pathlib import Path

import pytest

from jra_srb.jra_research_contracts import ResearchError


@pytest.fixture
def cli():
    """新CLIを通常のmain関数として読む。"""
    path = Path(__file__).resolve().parents[1] / 'scripts/score_jra_original_candidate.py'
    spec = importlib.util.spec_from_file_location('original_candidate_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_must_be_explicit(cli):
    """候補の暗黙指定や任意モデル指定を受け付けない。"""
    with pytest.raises(SystemExit) as error:
        cli.main(['--input', 'input.json', '--output', 'new'])
    assert error.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(['--candidate', 'J23', '--input', 'input.json', '--output', 'new', '--model', 'other'])


def test_cli_returns_safe_error(cli, monkeypatch, capsys):
    """失敗時は固定理由コードと終了コードだけを返す。"""
    def fail(*args):
        """入力拒否を再現する。"""
        raise ResearchError('candidate_output_exists', 2)
    monkeypatch.setattr(cli, 'execute', fail)
    assert cli.main(['--candidate', 'J23', '--input', 'input.json', '--output', 'new']) == 2
    assert 'candidate_output_exists' in capsys.readouterr().out
