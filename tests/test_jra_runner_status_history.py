"""概要: 過去走の取消表示を現走の出走状態へ混入させないことを検証する。
作成日: 2026-11-07
入力: 現在/過去走の取消表示を含むJRA形式HTML。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_runner_status_history.py
注意事項: 外部通信なし。現在の明示取消は引き続き検出する。
"""

import pytest
from pathlib import Path
from bs4 import BeautifulSoup
from jra_srb.config import load_parser_config
from jra_srb.extractors import _runner_status, parse_race_card


@pytest.mark.parametrize('past', ['出走取消', '競走除外', '取消', '除外'])
def test_past_status_does_not_withdraw_current_runner(past):
    """過去走セルだけの取消/除外を現在の出走取消へ読み替えない。"""
    soup = BeautifulSoup(f'<table><tr><td class="horse">出走馬</td><td class="past"><div>{past}</div></td></tr></table>', 'html.parser')
    before = str(soup)
    assert _runner_status(soup.tr) == ('active', None)
    assert str(soup) == before


@pytest.mark.parametrize('past', ['', '取消'])
def test_current_withdrawal_is_preserved(past):
    """現走の明示取消は過去表示にかかわらず維持する。"""
    soup = BeautifulSoup(f'<table><tr><td class="horse">出走取消</td><td class="past">{past}</td></tr></table>', 'html.parser')
    assert _runner_status(soup.tr) == ('withdrawn', 'explicit')


def test_real_card_structure_preserves_recent_races_and_current_runner():
    """実ページ構造の過去セルだけを変え、現走状態と直近走抽出を同時確認する。"""
    html = Path('tests/fixtures/jradb_accessD_race_202603220611.html').read_text(encoding='shift_jis', errors='ignore')
    soup = BeautifulSoup(html, 'html.parser')
    row = soup.select_one('table.basic.narrow-xy.mt20 tbody tr')
    past = row.select_one('td.past')
    assert past is not None
    marker = soup.new_tag('span'); marker.string = '取消'
    past.append(marker)
    parsed = parse_race_card(str(soup), load_parser_config('race_card'))
    horse = next(r for r in parsed['runners'] if r.horse_no == row.select_one('td.num').get_text(strip=True))
    assert horse.status == 'active'
    assert len(horse.official_recent_races) == 4
