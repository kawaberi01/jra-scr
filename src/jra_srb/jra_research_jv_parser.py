"""概要: 既存jv-o1o2-v2の純解析部分を研究内で再利用し、SQL本文とparsed明細を照合する。
作成日: 2026-10-15
入力: O1/O2本文bytes、DataSpec、期待12桁レースキー。
出力: 解析済みheader・市場明細、形式不一致時ParseError。
実行例: uv run pytest -q tests/test_jra_research_jv_parser.py
注意事項: DB・HTTP・ファイル読取なし。元import_jvlink_odds.pyから純計算のみ移植。
移植元SHA256: 6826f3606a37511ddd301972ecb15b50f25a1b2c32b3b3afe0f3a48b3e5c33b1"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time
PARSER_VERSION = 'jv-o1o2-v2'
JST = '+09:00'

@dataclass(frozen=True)
class Entry:
    """解析済みの券種・選択キー・整数10倍オッズ・状態を保持する。"""
    market: str
    selection_key: str
    odds_raw_low: str
    odds_raw_high: str | None
    odds_status_low: str
    odds_status_high: str | None
    odds_low_x10: int | None
    odds_high_x10: int | None
    popularity: int | None

@dataclass(frozen=True)
class ParsedObservation:
    """原本headerと解析明細を保持する。"""
    record_type: str
    data_division: str
    make_date: str
    race_key_full: str
    race_date: str
    race_course: str
    race_number: str
    announced_month_day_minute: str
    announced_at: str | None
    announced_at_status: str
    registered_count: int | None
    starter_count: int | None
    sale_flags: dict[str, str]
    vote_totals: dict[str, str]
    entries: tuple[Entry, ...]

class ParseError(ValueError):
    """JV原本の形式・意味に矛盾がある場合の例外。"""
    pass

def _ascii(raw: bytes, start: int, length: int, label: str) -> str:
    """固定位置をASCIIとして読む。非ASCII時はParseError。"""
    try:
        return raw[start:start + length].decode('ascii')
    except UnicodeDecodeError as exc:
        raise ParseError(f'{label}: ASCII以外のバイトがあります') from exc

def _digits(raw: str, label: str, *, allow_blank: bool=True) -> int | None:
    """数字欄を整数へ変換する。許可された空欄はNone。"""
    value = raw.strip()
    if not value and allow_blank:
        return None
    if not value.isdigit():
        raise ParseError(f'{label}: 数字ではありません ({raw!r})')
    return int(value)

def _odds(raw: str) -> tuple[str, int | None]:
    """数字とmarkerを区別する。全9桁は未確定上限markerとして数値にしない。"""
    value = raw.strip()
    if not value:
        return ('blank', None)
    if set(value) == {'-'}:
        return ('hyphen_marker', None)
    if set(value) == {'*'}:
        return ('asterisk_marker', None)
    if not value.isdigit():
        return ('other_marker', None)
    number = int(value)
    if number == 0:
        return ('zero_marker', None)
    if value and set(value) == {'9'}:
        return ('all_nines_marker', None)
    return ('numeric', number)

def _announcement_time(raw_mdhm: str, make_date: date | None, race_date: date) -> tuple[str | None, str]:
    """原本の年月日時分から年を一意に解決する。曖昧な年は未解決とする。"""
    if len(raw_mdhm) != 8 or not raw_mdhm.isdigit():
        return (None, 'invalid_mdhm')
    month, day, hour, minute = (int(raw_mdhm[0:2]), int(raw_mdhm[2:4]), int(raw_mdhm[4:6]), int(raw_mdhm[6:8]))
    anchor = make_date or race_date
    candidates: list[datetime] = []
    for year in range(race_date.year - 1, race_date.year + 2):
        try:
            candidates.append(datetime.combine(date(year, month, day), time(hour, minute)))
        except ValueError:
            continue
    plausible = [candidate for candidate in candidates if abs((candidate.date() - race_date).days) <= 40 and abs((candidate.date() - anchor).days) <= 40]
    if len(plausible) != 1:
        return (None, 'unresolved_year')
    return (plausible[0].isoformat(timespec='minutes') + JST, 'resolved')

def parse_record(raw: bytes, data_spec: str, expected_race_key: str) -> ParsedObservation:
    """O1/O2本文を元parser v2と同じ定義で解析する。長さ・種別・CRLF・期待レースキー・重複選択を検証し、不一致はParseError。副作用なし。"""
    expected = {'0B41': (b'O1', 962), '0B42': (b'O2', 2042)}.get(data_spec)
    if expected is None:
        raise ParseError(f'未対応DataSpec: {data_spec}')
    record_tag, expected_size = expected
    if len(raw) != expected_size:
        raise ParseError(f'レコード長が不正です: expected={expected_size}, actual={len(raw)}')
    if raw[:2] != record_tag:
        raise ParseError(f'DataSpecとレコード識別子が一致しません: {data_spec}/{raw[:2]!r}')
    if raw[-2:] != b'\r\n':
        raise ParseError('レコード終端がCRLFではありません')
    division = _ascii(raw, 2, 1, 'データ区分')
    make_raw = _ascii(raw, 3, 8, 'データ作成年月日')
    try:
        make_day = date.fromisoformat(f'{make_raw[0:4]}-{make_raw[4:6]}-{make_raw[6:8]}')
    except ValueError:
        make_day = None
    full_key = _ascii(raw, 11, 16, '完全レースキー')
    if not full_key.isdigit():
        raise ParseError('完全レースキーが数字16桁ではありません')
    race_date_raw = full_key[:8]
    try:
        race_day = date.fromisoformat(f'{race_date_raw[:4]}-{race_date_raw[4:6]}-{race_date_raw[6:8]}')
    except ValueError as exc:
        raise ParseError('完全レースキーの日付が不正です') from exc
    race_course, race_number = (full_key[8:10], full_key[14:16])
    derived_key = race_date_raw + race_course + race_number
    if derived_key != expected_race_key:
        raise ParseError(f'管理DBレースキーと原本が不一致です: {expected_race_key}/{derived_key}')
    mdhm = _ascii(raw, 27, 8, '発表月日時分')
    announced_at, announced_status = _announcement_time(mdhm, make_day, race_day)
    registered = _digits(_ascii(raw, 35, 2, '登録頭数'), '登録頭数')
    starter = _digits(_ascii(raw, 37, 2, '出走頭数'), '出走頭数')
    entries: list[Entry] = []
    flags: dict[str, str] = {}
    totals: dict[str, str] = {}
    if data_spec == '0B41':
        flags = {'win': _ascii(raw, 39, 1, '単勝発売フラグ'), 'place': _ascii(raw, 40, 1, '複勝発売フラグ'), 'bracket_quinella': _ascii(raw, 41, 1, '枠連発売フラグ'), 'place_payout_key': _ascii(raw, 42, 1, '複勝着払キー')}
        for i in range(28):
            start = 43 + 8 * i
            key = _ascii(raw, start, 2, '単勝馬番')
            if key.isdigit() and key != '00':
                raw_odds = _ascii(raw, start + 2, 4, '単勝オッズ')
                status, scaled = _odds(raw_odds)
                popularity = _digits(_ascii(raw, start + 6, 2, '単勝人気'), '単勝人気')
                entries.append(Entry('win', key, raw_odds, None, status, None, scaled, None, popularity))
        for i in range(28):
            start = 267 + 12 * i
            key = _ascii(raw, start, 2, '複勝馬番')
            if key.isdigit() and key != '00':
                low_raw = _ascii(raw, start + 2, 4, '複勝最低オッズ')
                high_raw = _ascii(raw, start + 6, 4, '複勝最高オッズ')
                low_status, low_scaled = _odds(low_raw)
                high_status, high_scaled = _odds(high_raw)
                popularity = _digits(_ascii(raw, start + 10, 2, '複勝人気'), '複勝人気')
                entries.append(Entry('place', key, low_raw, high_raw, low_status, high_status, low_scaled, high_scaled, popularity))
        for i in range(36):
            start = 603 + 9 * i
            key = _ascii(raw, start, 2, '枠連組番')
            if key.isdigit() and key != '00':
                raw_odds = _ascii(raw, start + 2, 5, '枠連オッズ')
                status, scaled = _odds(raw_odds)
                popularity = _digits(_ascii(raw, start + 7, 2, '枠連人気'), '枠連人気')
                entries.append(Entry('bracket_quinella', key, raw_odds, None, status, None, scaled, None, popularity))
        totals = {'win': _ascii(raw, 927, 11, '単勝票数合計').strip(), 'place': _ascii(raw, 938, 11, '複勝票数合計').strip(), 'bracket_quinella': _ascii(raw, 949, 11, '枠連票数合計').strip()}
    else:
        flags = {'quinella': _ascii(raw, 39, 1, '馬連発売フラグ')}
        for i in range(153):
            start = 40 + 13 * i
            key = _ascii(raw, start, 4, '馬連組番')
            if key.isdigit() and key != '0000':
                raw_odds = _ascii(raw, start + 4, 6, '馬連オッズ')
                status, scaled = _odds(raw_odds)
                popularity = _digits(_ascii(raw, start + 10, 3, '馬連人気'), '馬連人気')
                entries.append(Entry('quinella', key, raw_odds, None, status, None, scaled, None, popularity))
        totals = {'quinella': _ascii(raw, 2029, 11, '馬連票数合計').strip()}
    identities = [(entry.market, entry.selection_key) for entry in entries]
    if len(identities) != len(set(identities)):
        raise ParseError('同じ券種・選択キーがレコード内で重複しています')
    return ParsedObservation('O1' if data_spec == '0B41' else 'O2', division, make_raw, full_key, race_date_raw, race_course, race_number, mdhm, announced_at, announced_status, registered, starter, flags, totals, tuple(entries))
