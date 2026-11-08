"""概要: runtime受領版選択・完全束・利用時点・再現契約を合成入力で検査する。
作成日: 2026-10-15
入力: 現API保存形式の合成payloadと固定SQL行。
出力: pytest結果。実DB・HTTP・ファイル本文出力なし。
実行例: uv run pytest -q tests/test_jra_research_runtime.py
注意事項: 単体成功は実SQLのM4受入証明と区別する。
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json

import pytest

from jra_srb.jra_research_contracts import ResearchError, canonical_json
from jra_srb.jra_research_runtime import (
    RuntimeIdentity, baseline_bundle, read_receipt_rows, select_runtime_bundle,
    select_whole_bundle, validate_identity_map, verify_runtime_replay,
)
from jra_srb.models import RaceCard, RaceOdds, RaceResult


RACE = "api-opaque-race-id"
CUTOFF = "2026-10-15T12:00:00+00:00"
FETCHED = "2026-10-14T10:00:00+09:00"


def identity_rows() -> list[dict]:
    """文字列形式による暗黙対応ができない登録済み合成ID行を返す。"""
    return [{"api_race_id": RACE, "unified_race_id": "unified:other-format", "race_date": "2026-10-14",
             "course": "tokyo", "race_no": 1, "source_snapshot_id": 31, "mapping_status": "verified"}]


def identity() -> RuntimeIdentity:
    """固定ID mapの検査を通した研究IDを返す。"""
    return validate_identity_map(identity_rows(), [RACE], expected_snapshot_id=31)[RACE]


def payload(operation: str = "race_result", source: str = "official") -> dict:
    """実APIモデルのmodel_dumpと同じwrapperを持つ合成payloadを作る。"""
    common = {"race_id": RACE, "source": source, "fetched_at": FETCHED}
    if operation == "race_card":
        body = RaceCard(**common, course="tokyo", runners=[{"horse_no": "1", "horse_name": "A"}, {"horse_no": "2", "horse_name": "B"}]).model_dump(mode="json")
        return {"date": "2026-10-14", "course": "tokyo", "race_no": 1, "card": body}
    if operation == "odds":
        body = RaceOdds(**common, bet_type="win", entries=[{"bet_type": "win", "combination": ["1"], "odds": "2.0"}]).model_dump(mode="json")
        return {"bet_type": "win", "odds_timing": "T30", "odds": body}
    return RaceResult(**common, race_name="original parent", results=[
        {"rank": "1", "horse_no": "1", "horse_name": "A"}, {"rank": "2", "horse_no": "2", "horse_name": "B"}],
        payouts=[{"bet_type": "win", "combination": "1", "payout": "230"}]).model_dump(mode="json")


def receipt(operation: str = "race_result", received: str = "2026-10-15T10:00:00+00:00", body: dict | None = None) -> dict:
    """実SqlServerStoreと同じcache除外hashを持つ合成receiptを作る。"""
    body = body if body is not None else payload(operation)
    business = deepcopy(body)
    observed = business["card"] if operation == "race_card" else business["odds"] if operation == "odds" else business
    observed.pop("cache_hit", None)
    observed.pop("meta", None)
    key = hashlib.sha256((operation + "\n" + RACE + "\n" + canonical_json(business)).encode()).hexdigest()
    return {"request_sha256": key, "operation": operation, "race_id": RACE,
            "received_at_utc": received, "payload_json": canonical_json(body)}


def select(rows: list[dict], operation: str = "race_result", **kwargs):
    """共通の固定cutoffとsourceで受領版を選択する。"""
    market = {"bet_type": "win", "odds_timing": "T30"} if operation == "odds" else {}
    return select_runtime_bundle(rows, identity(), operation=operation, source="official", knowledge_cutoff=CUTOFF, **market, **kwargs)


@pytest.mark.parametrize("operation", ["race_card", "odds", "race_result"])
def test_real_api_payload_contract_preserves_whole_bundle(operation):
    """3operationの実保存形式を壊さず完全束として復元する。"""
    row = receipt(operation)
    bundle = select([row], operation)
    assert bundle.payload == json.loads(row["payload_json"])
    assert bundle.known_at == "2026-10-15T10:00:00+00:00"
    assert bundle.provider_fetched_at == "2026-10-14T01:00:00+00:00"
    assert bundle.evidence()["announced_at"] is None
    assert bundle.evidence()["availability"] == "research_only"
    assert bundle.evidence()["strict_live_replay_eligible"] is False


def test_result_parent_entries_payout_are_selected_from_one_receipt():
    """結果訂正版の親・明細・払戻を旧版と混ぜない。"""
    revised = payload()
    revised["race_name"] = "corrected parent"
    revised["results"][0]["rank"] = "2"
    revised["results"][1]["rank"] = "1"
    revised["payouts"] = [{"bet_type": "win", "combination": "2", "payout": "880"}]
    bundle = select([receipt(), receipt(received="2026-10-15T11:00:00+00:00", body=revised)])
    assert bundle.payload == revised
    assert bundle.payload["payouts"][0]["payout"] == "880"


def test_after_knowledge_cutoff_correction_is_not_selected():
    """研究知識締切以降の訂正を遡及採用しない。"""
    revised = payload()
    revised["race_name"] = "too late"
    bundle = select([receipt(), receipt(received="2026-10-15T12:00:00.000001+00:00", body=revised)])
    assert bundle.payload["race_name"] == "original parent"


def test_equal_timestamp_different_body_is_ambiguous():
    """request SHA順を訂正順と見なさない。"""
    changed = payload()
    changed["payouts"][0]["payout"] = "999"
    with pytest.raises(ResearchError, match="ambiguous_revision"):
        select([receipt(), receipt(body=changed)])


def test_datetime2_seventh_fraction_orders_revisions_without_false_ambiguity():
    """100ns差を同時刻競合へ丸めず真の最新受領を選択する。"""
    changed = payload()
    changed["race_name"] = "100ns later"
    bundle = select([receipt(received="2026-10-15T10:00:00.1234561+00:00"),
                     receipt(received="2026-10-15T10:00:00.1234562+00:00", body=changed)])
    assert bundle.known_at == "2026-10-15T10:00:00.1234562+00:00"
    assert bundle.payload["race_name"] == "100ns later"


def test_datetime2_seventh_fraction_enforces_cutoff_instead_of_rounding():
    """cutoffを100ns超過した受領を同じmicrosecondとして採用しない。"""
    row = receipt(received="2026-10-15T10:00:00.1234562+00:00")
    with pytest.raises(ResearchError, match="replay_unavailable"):
        select_runtime_bundle([row], identity(), operation="race_result", source="official",
                              knowledge_cutoff="2026-10-15T10:00:00.1234561+00:00")


@pytest.mark.parametrize("decision", ["2026-10-14T12:00:00+00:00", "2026-10-15T09:59:59+00:00"])
def test_old_fetched_time_does_not_prove_live_availability(decision):
    """古い取得時刻でも受領が判断後なら予測入力へ採用しない。"""
    with pytest.raises(ResearchError, match="after_cutoff"):
        select([receipt()], decision_cutoff=decision)


def test_even_predecision_receipt_has_no_announced_time_proof():
    """受領が判断前でも公表時刻の欠落をstrictへ昇格しない。"""
    bundle = select([receipt()], decision_cutoff="2026-10-15T11:00:00+00:00")
    assert bundle.evidence()["strict_live_replay_eligible"] is False


def test_explicit_decision_time_selects_latest_available_even_when_knowledge_is_later():
    """研究知識締切が後でも、明示判断時点内の最新受領を選択する。"""
    changed = payload()
    changed["race_name"] = "known after decision"
    old = receipt(received="2026-10-15T09:00:00+00:00")
    later = receipt(received="2026-10-15T11:00:00+00:00", body=changed)
    bundle = select([old, later], decision_cutoff="2026-10-15T10:00:00+00:00")
    assert bundle.selection_key == old["request_sha256"]
    assert bundle.knowledge_cutoff == CUTOFF
    assert bundle.decision_cutoff == "2026-10-15T10:00:00+00:00"


def test_decision_filter_applies_to_provider_fetched_time_too():
    """受領は判断前でも本文取得時刻が判断後なら候補から除く。"""
    future = payload()
    future["fetched_at"] = "2026-10-15T11:00:00+00:00"
    future["race_name"] = "future fetched"
    bundle = select([receipt(received="2026-10-15T08:00:00+00:00"),
                     receipt(received="2026-10-15T09:00:00+00:00", body=future)],
                    decision_cutoff="2026-10-15T10:00:00+00:00")
    assert bundle.payload["race_name"] == "original parent"


def test_same_time_conflicting_revisions_before_decision_are_still_ambiguous():
    """判断時点内に競合本文があれば後続候補の除外で競合を隠さない。"""
    changed = payload()
    changed["payouts"][0]["payout"] = "880"
    after = payload()
    after["race_name"] = "later"
    with pytest.raises(ResearchError, match="ambiguous_revision"):
        select([receipt(received="2026-10-15T09:00:00+00:00"),
                receipt(received="2026-10-15T09:00:00+00:00", body=changed),
                receipt(received="2026-10-15T11:00:00+00:00", body=after)],
               decision_cutoff="2026-10-15T10:00:00+00:00")


def test_unknown_id_is_not_created_by_string_similarity():
    """未登録の新runtime IDを文字列から補完しない。"""
    with pytest.raises(ResearchError, match="unresolved_id"):
        validate_identity_map(identity_rows(), [RACE, "202610140101"], expected_snapshot_id=31)


@pytest.mark.parametrize("change,reason", [
    ({"source_snapshot_id": 34}, "unresolved_id"), ({"mapping_status": "candidate"}, "unresolved_id"),
    ({"race_no": 13}, "identity_attribute_mismatch"), ({"race_date": "2026-1-1"}, "unresolved_id"),
])
def test_id_map_contract_rejects_unverified_or_wrong_attributes(change, reason):
    """版・検証状態・開催属性の不一致を停止する。"""
    rows = identity_rows()
    rows[0].update(change)
    with pytest.raises(ResearchError, match=reason):
        validate_identity_map(rows, [RACE], expected_snapshot_id=31)


def test_id_map_forward_and_reverse_must_be_unique():
    """同一API IDの重複と二つのAPI IDの同一統合IDへの対応を拒否する。"""
    with pytest.raises(ResearchError, match="ambiguous_id"):
        validate_identity_map(identity_rows() * 2, [RACE], expected_snapshot_id=31)
    second = identity_rows()[0] | {"api_race_id": "other-api-id"}
    with pytest.raises(ResearchError, match="ambiguous_id"):
        validate_identity_map(identity_rows() + [second], [RACE, "other-api-id"], expected_snapshot_id=31)


def test_baseline_only_available_at_explicit_capture_time():
    """固定baselineの古いfetched_atを当時既知の根拠にしない。"""
    args = dict(operation="race_result", source="official", snapshot_id=34, source_key="analysis-current",
                captured_known_at="2026-10-15T11:00:00+00:00", knowledge_cutoff=CUTOFF)
    bundle = baseline_bundle(payload(), identity(), **args)
    assert bundle.known_at == "2026-10-15T11:00:00+00:00"
    assert bundle.evidence()["received_at_utc"] is None
    with pytest.raises(ResearchError, match="after_cutoff"):
        baseline_bundle(payload(), identity(), **(args | {"knowledge_cutoff": "2026-10-15T10:59:59+00:00"}))
    with pytest.raises(ResearchError, match="after_cutoff"):
        baseline_bundle(payload(), identity(), **args, decision_cutoff="2026-10-14T11:00:00+00:00")


@pytest.mark.parametrize("snapshot,source", [(31, "analysis-current"), (34, "another-source")])
def test_baseline_requires_explicit_adopted_version(snapshot, source):
    """baselineと同番号の別sourceを誤採用しない。"""
    with pytest.raises(ResearchError, match="unexpected_baseline"):
        baseline_bundle(payload(), identity(), operation="race_result", source="official", snapshot_id=snapshot,
                        source_key=source, captured_known_at=CUTOFF, knowledge_cutoff=CUTOFF)


def test_whole_bundle_priority_is_explicit_and_does_not_combine_payouts():
    """receiptの払戻をbaselineで置換せず選択束そのものを保持する。"""
    body = payload()
    body["payouts"][0]["payout"] = "770"
    runtime = select([receipt(body=body)])
    baseline = baseline_bundle(payload(), identity(), operation="race_result", source="official", snapshot_id=34,
                               source_key="analysis-current", captured_known_at="2026-10-15T09:00:00+00:00", knowledge_cutoff=CUTOFF)
    selected = select_whole_bundle([runtime, baseline], priority=("receipt", "baseline"))
    assert selected.payload["payouts"][0]["payout"] == "770"
    assert select_whole_bundle([runtime, baseline], priority=("baseline", "receipt")) is baseline
    with pytest.raises(ResearchError, match="explicit_source_priority_required"):
        select_whole_bundle([runtime, baseline], priority=())


def test_partial_receipt_is_not_all_losses_and_not_filled_from_baseline():
    """払戻欠落は停止し、手元にbaselineがあっても全外れや補完扱いにしない。"""
    body = payload()
    body["payouts"] = []
    baseline = baseline_bundle(payload(), identity(), operation="race_result", source="official", snapshot_id=34,
                               source_key="analysis-current", captured_known_at="2026-10-15T09:00:00+00:00", knowledge_cutoff=CUTOFF)
    assert baseline.payload["payouts"]
    with pytest.raises(ResearchError, match="missing_payout"):
        select([receipt(body=body)])


@pytest.mark.parametrize("field,value,reason", [
    ("rank", "取消", "settlement_unknown"), ("rank", "返還", "settlement_unknown"),
    ("payout", "返還", "settlement_unknown"), ("payout", "0", "settlement_unknown"),
    ("payout", "1,2,3", "settlement_unknown"), ("combination", "2", "winner_payout_mismatch"),
])
def test_unknown_or_inconsistent_settlement_is_rejected(field, value, reason):
    """返還/取消/不正金額/勝馬不一致を正常精算へ推定しない。"""
    body = payload()
    row = body["results"][0] if field == "rank" else body["payouts"][0]
    row[field] = value
    with pytest.raises(ResearchError, match=reason):
        select([receipt(body=body)])


def test_dead_heat_keeps_each_horse_actual_yen_and_japanese_win_label():
    """同着の異なる馬別払戻を維持し、日本語単勝も実保存形式として検査する。"""
    body = payload()
    body["results"][1]["rank"] = "1"
    body["payouts"] = [{"bet_type": "単勝", "combination": "1", "payout": "1,230"},
                       {"bet_type": "単勝", "combination": "2", "payout": "850"}]
    bundle = select([receipt(body=body)])
    assert [row["payout"] for row in bundle.payload["payouts"]] == ["1,230", "850"]
    assert bundle.evidence()["settlement_verified_market"] == "win"


def test_timezone_boundary_and_100ns_revision_order_are_utc_correct():
    """日付が跨ぐtimezoneでも100ns単位の最新受領を選択する。"""
    changed = payload()
    changed["race_name"] = "later across timezone"
    bundle = select([receipt(received="2026-10-15T01:00:00.1234561+09:00"),
                     receipt(received="2026-10-14T16:00:00.1234562+00:00", body=changed)])
    assert bundle.known_at == "2026-10-14T16:00:00.1234562+00:00"
    assert bundle.payload["race_name"] == "later across timezone"


def test_replay_digest_detects_whole_body_change_and_contains_no_body():
    """保存証跡へ本文を出さず、全本文の改変と選択版の変化を検出する。"""
    bundle = select([receipt()])
    expected = bundle.content_digest()
    verify_runtime_replay(select([receipt()]), expected)
    evidence = canonical_json(bundle.evidence())
    assert "original parent" not in evidence and "payouts" not in evidence and "payload_json" not in evidence
    bundle.payload["payouts"][0]["payout"] = "999"
    with pytest.raises(ResearchError, match="source_changed"):
        verify_runtime_replay(bundle, expected)
    with pytest.raises(ResearchError, match="source_changed"):
        verify_runtime_replay(select([receipt(received="2026-10-15T11:00:00+00:00")]), expected)


def test_missing_receipt_is_replay_unavailable_without_fallback():
    """該当受領版がなければ別DBや現在表で成功させない。"""
    with pytest.raises(ResearchError, match="replay_unavailable"):
        select([])


@pytest.mark.parametrize("operation", ["race_card", "odds", "race_result"])
def test_wrong_payload_race_is_rejected(operation):
    """receiptキーと本文のrace ID不一致を拒否する。"""
    body = payload(operation)
    observed = body["card"] if operation == "race_card" else body["odds"] if operation == "odds" else body
    observed["race_id"] = "not-registered"
    with pytest.raises(ResearchError, match="identity_attribute_mismatch"):
        select([receipt(operation, body=body)], operation)


def test_cache_metadata_digest_matches_real_store_exclusion():
    """cache hit情報を除く実writerのSHA契約と一致する。"""
    body = payload()
    original = receipt(body=body)
    body["cache_hit"] = True
    body["meta"] = {"data_source": "sql", "db_hit": True}
    cached = receipt(body=body)
    assert cached["request_sha256"] == original["request_sha256"]
    assert select([cached]).payload["cache_hit"] is True


def test_receipt_payload_integrity_and_schema_drift_are_rejected():
    """保存SHA不一致と未対応payload版を古い版で隠さない。"""
    row = receipt()
    row["request_sha256"] = "0" * 64
    with pytest.raises(ResearchError, match="receipt_digest_mismatch"):
        select([row])
    changed = payload()
    changed["new_schema_field"] = True
    with pytest.raises(ResearchError, match="unsupported_receipt_payload_version"):
        select([receipt(body=changed)])


def test_source_and_market_filters_never_mix_bundles():
    """source・券種・観測時点の異なる最新行を選ばない。"""
    other = payload("odds", source="other")
    late = payload("odds")
    late["odds_timing"] = "T10"
    chosen = select([receipt("odds"), receipt("odds", received="2026-10-15T11:00:00+00:00", body=other),
                     receipt("odds", received="2026-10-15T11:01:00+00:00", body=late)], "odds")
    assert chosen.odds_timing == "T30"
    with pytest.raises(ResearchError, match="explicit_market_required"):
        select_runtime_bundle([receipt("odds")], identity(), operation="odds", source="official", knowledge_cutoff=CUTOFF)


def test_multi_market_dict_obeys_actual_writer_instead_of_request_wrapper():
    """実writerはmulti-market dict全体を保存するためwrapper券種で切捨てない。"""
    body = payload("odds")
    body["odds"]["odds"] = {"quinella": [{"bet_type": "quinella", "combination": ["1", "2"], "odds": "4.0"}]}
    bundle = select_runtime_bundle([receipt("odds", body=body)], identity(), operation="odds", source="official",
                                   knowledge_cutoff=CUTOFF, bet_type="quinella", odds_timing="T30")
    assert bundle.bet_type == "quinella" and bundle.payload == body
    with pytest.raises(ResearchError, match="replay_unavailable"):
        select([receipt("odds", body=body)], "odds")


def test_missing_serialized_result_collection_is_invalid_not_partial_success():
    """実model_dumpにある明細キーが欠けた本文を復元済み扱いしない。"""
    body = payload()
    del body["payouts"]
    with pytest.raises(ResearchError, match="invalid_receipt_payload"):
        select([receipt(body=body)])


def test_unordered_pair_duplicate_is_rejected():
    """無向券種の逆順pair重複も検出する。"""
    body = payload("odds")
    body["bet_type"] = "quinella"
    body["odds"]["odds"] = {"quinella": [
        {"bet_type": "quinella", "combination": ["1", "2"], "odds": "4.0"},
        {"bet_type": "quinella", "combination": ["2", "1"], "odds": "4.0"}]}
    with pytest.raises(ResearchError, match="duplicate_key"):
        select_runtime_bundle([receipt("odds", body=body)], identity(), operation="odds", source="official",
                              knowledge_cutoff=CUTOFF, bet_type="quinella", odds_timing="T30")


def test_sql_route_is_bounded_parameterized_and_preserves_utc_column_semantics():
    """固定SELECTにhashと元ID完全一致・cutoff・operation条件がある。"""
    row = receipt()
    row["received_at_utc"] = datetime(2026, 10, 15, 10, 0)
    row["request_sha256"] = bytes.fromhex(row["request_sha256"])

    class Reader:
        """実接続をしない固定cursorと実行条件の監視器。"""

        @contextmanager
        def _cursor(self, query_id, sql, params):
            """SQL条件を検査して1行だけ返す。"""
            assert query_id == "runtime:receipt_by_race_cutoff"
            assert sql.startswith("SELECT TOP (?)") and "race_sha256=" in sql
            assert "CONVERT(varbinary(max),race_id)=" in sql and "received_at_utc<=CONVERT(datetime2(7),?)" in sql
            assert "CONVERT(varchar(33),received_at_utc,126)" in sql
            assert "operation IN" in sql and RACE not in sql
            assert params[0] == 2 and params[2] == RACE
            assert params[1] == hashlib.sha256(RACE.encode("utf-16le")).digest()

            class Cursor:
                """SQL DBAPIと同じ列名・行の形を提供する。"""

                description = [(name,) for name in row]

                def fetchmany(self, size):
                    """要求上限が限定されていることを検査する。"""
                    assert size == 2
                    return [tuple(row.values())]

            yield Cursor()

    rows = read_receipt_rows(Reader(), [identity()], knowledge_cutoff=CUTOFF, max_rows=1)
    assert rows[0]["received_at_utc"] == "2026-10-15T10:00:00+00:00"
    assert select(rows).operation == "race_result"


def test_sql_route_rejects_overflow_without_truncating_or_retry():
    """行上限超過を黙って打切り成功にしない。"""
    row = receipt()

    class Reader:
        """上限超過した結果だけを返す監視器。"""

        calls = 0

        @contextmanager
        def _cursor(self, query_id, sql, params):
            """cursor実行回数を記録する。"""
            self.calls += 1

            class Cursor:
                """列名と重複した2行を返すcursor。"""

                description = [(name,) for name in row]

                def fetchmany(self, size):
                    """上限1に対して2行を返す。"""
                    return [tuple(row.values())] * 2

            yield Cursor()

    reader = Reader()
    with pytest.raises(ResearchError, match="receipt_row_limit"):
        read_receipt_rows(reader, [identity()], knowledge_cutoff=CUTOFF, max_rows=1)
    assert reader.calls == 1


@pytest.mark.parametrize("budget,expected_remaining,should_fail", [(20, [20, 10], False), (19, [19, 9], True)])
def test_sql_payload_budget_is_total_across_races_before_body_transfer(budget, expected_remaining, should_fail):
    """SQL送信前のUTF16本文byte上限をID別ではなく全ID合計へ適用する。"""
    import sqlglot
    from dataclasses import replace

    class Reader:
        """SQL CASEと残容量を再現し、第二IDへの予算継承を監視する。"""

        def __init__(self):
            """IDごとの残byteを記録する。"""
            self.remaining = []

        @contextmanager
        def _cursor(self, query_id, sql, params):
            """bounded subqueryとwindow総量検査のSQLを解析する。"""
            assert sqlglot.parse_one(sql, read="tsql") is not None
            assert "FROM (SELECT TOP (?)" in sql
            assert "SUM(CONVERT(bigint,DATALENGTH(payload_json))) OVER ()<=?" in sql
            self.remaining.append(params[0])
            row = receipt()
            row["race_id"] = params[3]
            row["payload_json"] = "abcde" if params[0] >= 10 else None
            row["payload_byte_count"] = 10

            class Cursor:
                """SQLが許可しない本文はNULLだけをクライアントへ返す。"""

                description = [(name,) for name in row]

                def fetchmany(self, size):
                    """有界な1行を返す。"""
                    return [tuple(row.values())]

            yield Cursor()

    reader = Reader()
    identities = [identity(), replace(identity(), api_race_id="other-race", unified_race_id="unified:other")]
    if should_fail:
        with pytest.raises(ResearchError, match="receipt_payload_limit"):
            read_receipt_rows(reader, identities, knowledge_cutoff=CUTOFF, max_payload_bytes=budget)
    else:
        rows = read_receipt_rows(reader, identities, knowledge_cutoff=CUTOFF, max_payload_bytes=budget)
        assert len(rows) == 2 and all("payload_byte_count" not in row for row in rows)
    assert reader.remaining == expected_remaining


@pytest.mark.parametrize("budget", [0, True, "64"])
def test_invalid_payload_budget_is_rejected_before_sql(budget):
    """不正なbyte予算をreaderに触れる前に拒否する。"""
    with pytest.raises(ResearchError, match="invalid_receipt_query"):
        read_receipt_rows(None, [identity()], knowledge_cutoff=CUTOFF, max_payload_bytes=budget)
