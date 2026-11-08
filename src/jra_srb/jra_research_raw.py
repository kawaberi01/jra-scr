"""概要: SQLに格納済みのO1/O2圧縮本文と解析明細の内容一致を検査する。
作成日: 2026-10-15
入力: 固定版から取得した圧縮本文・観測metadata・parsed明細。
出力: 検証済みのメモリ内解析結果。不一致時ResearchError。
実行例: uv run pytest -q tests/test_jra_research_jv_parser.py
注意事項: DB・NAS・HTTPを使用しない。圧縮展開は既知JVレコード長で制限する。
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import re
import zlib

from .jra_research_contracts import ResearchError, timestamp
from .jra_research_jv_parser import PARSER_VERSION, ParseError, parse_record


def verify_jv_content(content: dict, observation: dict):
    """本文SHA・長さ・headerと観測を照合して解析結果を返す。

    Args:
        content: sha256/codec/compressed_payload/raw_length/record_typeを持つSQL原本行。
        observation: 解析版・出典SHA/byte長・DataSpec・レースキー・発表時刻等のSQL観測行。

    Returns:
        元parser v2で再解析した不変の観測と明細。

    Raises:
        ResearchError: 未対応codec/版、本文破損、長さ・SHA・headerの不一致。

    Notes:
        内容一致は旧ファイルパス/原本IDの取込系譜一致や当時受領済みを証明しない。
    """
    try:
        if observation["parser_version"] != PARSER_VERSION:
            raise ValueError("parser")
        expected_length = {"0B41": 962, "0B42": 2042}[observation["source_data_spec"]]
        sha = observation["source_sha256"]
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) or content["sha256"] != sha:
            raise ValueError("sha")
        if content["codec"] != "zlib" or type(content["raw_length"]) is not int or content["raw_length"] != expected_length or observation["source_bytes"] != expected_length:
            raise ValueError("length_or_codec")
        compressed = bytes(content["compressed_payload"])
        if len(compressed) > 262144:
            raise ValueError("compressed_length")
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected_length + 1)
        if len(raw) != expected_length or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("compressed_stream")
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("body_sha")
        parsed = parse_record(raw, observation["source_data_spec"], observation["jv_race_key"])
        if (parsed.record_type != content["record_type"] or parsed.record_type != observation["record_type"]
                or parsed.data_division != observation["data_division"]
                or parsed.announced_at_status != "resolved" or observation["announced_at_status"] != "resolved"
                or timestamp(parsed.announced_at) != timestamp(observation["announced_at"])):
            raise ValueError("header")
        return parsed
    except (KeyError, ValueError, TypeError, zlib.error, ParseError):
        raise ResearchError("raw_content_contract_failed", 4) from None


def verify_jv_entries(parsed, rows: list[dict], market: str) -> None:
    """利用券種の全選択キー・raw欄・marker・数値・人気を再解析結果と比較する。"""
    expected = {entry.selection_key: asdict(entry) for entry in parsed.entries if entry.market == market}
    fields = ("market", "selection_key", "odds_raw_low", "odds_raw_high", "odds_status_low", "odds_status_high", "odds_low_x10", "odds_high_x10", "popularity")
    actual = {}
    try:
        for row in rows:
            if row["market"] != market:
                continue
            key = row["selection_key"]
            if key in actual:
                raise ValueError("duplicate")
            actual[key] = {name: row[name] for name in fields}
        if not expected or expected != actual:
            raise ValueError("mismatch")
    except (KeyError, TypeError, ValueError):
        raise ResearchError("parsed_content_mismatch", 4) from None
