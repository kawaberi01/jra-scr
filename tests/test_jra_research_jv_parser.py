"""概要: 再利用JV parserとSQL本文検証の数値・marker・破損拒否を確認する。
作成日: 2026-10-15
入力: 合成O1/O2本文とSQL相当metadata。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_research_jv_parser.py
注意事項: 実DB・原本ファイルへ接続しない。
"""

from dataclasses import asdict
import hashlib
import zlib

import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_jv_parser import PARSER_VERSION, ParseError, parse_record
from jra_srb.jra_research_raw import verify_jv_content, verify_jv_entries


def body_fixture(spec="0B41"):
    """固定レコード長と公式欄位置に沿う少数オッズ本文を作る。"""
    raw = bytearray(b" " * (962 if spec == "0B41" else 2042))
    raw[:2] = b"O1" if spec == "0B41" else b"O2"
    raw[2:3] = b"1"
    raw[3:11] = b"20250105"
    raw[11:27] = b"2025010506010101"
    raw[27:35] = b"01050930"
    raw[35:39] = b"1818"
    if spec == "0B41":
        raw[39:43] = b"1111"
        raw[43:51] = b"01002501"
        raw[51:59] = b"02999902"
    else:
        raw[39:40] = b"1"
        raw[40:53] = b"0102000450001"
    raw[-2:] = b"\r\n"
    return bytes(raw)


def content_fixture(spec="0B41"):
    """本文と解析metadataの正しい組を返す。"""
    raw = body_fixture(spec)
    sha = hashlib.sha256(raw).hexdigest()
    kind = "O1" if spec == "0B41" else "O2"
    content = {"sha256": sha, "codec": "zlib", "compressed_payload": zlib.compress(raw), "raw_length": len(raw), "record_type": kind}
    observation = {"parser_version": PARSER_VERSION, "source_data_spec": spec, "source_sha256": sha,
        "source_bytes": len(raw), "jv_race_key": "202501050601", "record_type": kind,
        "data_division": "1", "announced_at_status": "resolved", "announced_at": "2025-01-05T09:30:00+09:00"}
    return content, observation


@pytest.mark.parametrize("spec", ["0B41", "0B42"])
def test_parser_and_content_match_numeric_entries(spec):
    """headerと整数10倍値を照合し、parsed明細の改変を検知する。"""
    content, observation = content_fixture(spec)
    parsed = verify_jv_content(content, observation)
    market = "win" if spec == "0B41" else "quinella"
    rows = [asdict(entry) for entry in parsed.entries]
    verify_jv_entries(parsed, rows, market)
    assert rows[0]["odds_low_x10"] == (25 if spec == "0B41" else 450)
    rows[0]["odds_low_x10"] += 1
    with pytest.raises(ResearchError, match="parsed_content_mismatch"):
        verify_jv_entries(parsed, rows, market)


def test_all_nines_remains_marker():
    """全9値を極端に高い数値オッズへ誤変換しない。"""
    parsed = parse_record(body_fixture(), "0B41", "202501050601")
    assert parsed.entries[1].odds_status_low == "all_nines_marker"
    assert parsed.entries[1].odds_low_x10 is None


@pytest.mark.parametrize("damage", ["sha", "length", "tail", "race", "announcement", "bomb"])
def test_content_damage_is_rejected(damage):
    """本文・metadata・圧縮末尾の不正を本文出力なしに拒否する。"""
    content, observation = content_fixture()
    if damage == "sha":
        content["sha256"] = "0" * 64
    elif damage == "length":
        content["raw_length"] += 1
    elif damage == "tail":
        content["compressed_payload"] += b"unexpected"
    elif damage == "race":
        observation["jv_race_key"] = "202501050602"
    elif damage == "announcement":
        observation["announced_at"] = "2025-01-05T10:00:00+09:00"
    else:
        content["compressed_payload"] = zlib.compress(b"x" * 1000000)
    with pytest.raises(ResearchError):
        verify_jv_content(content, observation)
