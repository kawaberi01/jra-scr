"""概要: R11の固定版SQL境界、同時点、ID、完全精算、二巡と成果物を検証する。
作成日: 2026-10-16
入力: 合成5表、SQL catalog/cursor stub、一時設定。
出力: pytest結果。一時run以外の保存・DB/HTTP接続なし。
実行例: uv run pytest -q tests/test_jra_research_cross_market_sql.py
注意事項: 実SQLは別の限定受入で行い、単体成功をデータ充足と混同しない。
"""

from contextlib import contextmanager
from copy import deepcopy
from itertools import combinations
import json

import pytest

from jra_srb import jra_research_artifacts as artifacts
from jra_srb import jra_research_cross_market_sql as sql
from jra_srb.jra_research_contracts import ResearchError, digest


def config_value():
    """R11の非秘密設定を返す。"""
    return {"schema_version": 1, "profile_id": "cross_market_disagreement_sql_v1",
            "source_policy": {"source_key": "analysis-current", "snapshot_id": 34}, "year": 2025,
            "timing_policy": "matching_captured_at", "limits": {"fetch_rows": 10000, "max_candidate_rows": 1000000,
                "query_timeout_seconds": 30, "memory_bytes": 2 * 1024 ** 3}}


def table_fixture():
    """3期間それぞれに正常4頭・完全wide市場と3的中払戻を作る。"""
    tables = {name: [] for name in sql.FIELDS}
    for suffix, day in (("a", "2025-03-01"), ("b", "2025-08-01"), ("c", "2025-11-01")):
        race_id, vendor_id = "api-opaque-" + suffix, "vendor-different-" + suffix
        tables["live.races"].append({"race_id": race_id, "race_date": day, "course": "tokyo", "race_no": 1})
        common = {"jra_race_id": race_id, "netkeiba_race_id": vendor_id}
        tables["live.netkeiba_race_results"].append({**common, "race_date": day, "course": "tokyo", "race_no": 1,
            "source": "https://race.netkeiba.com/race/result.html?race_id=" + vendor_id,
            "fetched_at": day + "T12:00:00.1234567+00:00"})
        for number in range(1, 5):
            tables["live.netkeiba_result_entries"].append({**common, "horse_no": str(number), "rank": number, "win_odds": float(2 ** number)})
        for index, pair in enumerate(combinations(("1", "2", "3", "4"), 2)):
            tables["live.netkeiba_odds_entries"].append({**common, "bet_type": "wide", "combination": "-".join(pair),
                "odds": None, "odds_min": 3.0 + index, "odds_max": 5.0 + index,
                "source": "https://race.netkeiba.com/odds/index.html?race_id=" + vendor_id,
                "fetched_at": day + "T21:00:00.1234567+09:00"})
            if "4" not in pair:
                tables["live.netkeiba_payouts"].append({**common, "bet_type": "wide", "combination": "-".join(pair), "payout": 300 + index * 100})
    for rows in tables.values():
        for index, row in enumerate(rows, 1):
            row["__migration_source_rowid"] = index
    return tables


def mapping_fixture(tables=None):
    """ID位置変換なしに、合成SQL対応表の明示登録行を作る。"""
    tables = tables or table_fixture()
    rows = []
    for index, race in enumerate(tables["live.races"], 1):
        # 合成登録表のfull IDは、opaque API IDとは独立した明示座標から作る。
        full = race["race_date"].replace("-", "") + "050101" + f'{race["race_no"]:02d}'
        evidence = {"source_relation": "live.races", "original_id": race["race_id"], "stored_full_id": full,
                    "stored_date": race["race_date"], "stored_venue": "tokyo", "stored_race_no": race["race_no"],
                    "rule": "stored_full16_and_coordinates; no 12-to-16 synthesis"}
        rows.append({"map_id": index, "source_snapshot_id": 34, "source_relation": "live.races",
                     "source_original_id": race["race_id"], "api_race_id": race["race_id"], "jv_race_key_full_16": full,
                     "race_date": race["race_date"], "race_no": race["race_no"], "venue_code": "05",
                     "unified_race_id": "JRA:" + full, "mapping_status": "verified", "evidence_json": json.dumps(evidence)})
    return rows


class SyntheticReader(sql.CrossMarketReader):
    """接続だけを置換して本番の二巡・採用・評価処理を実行する。"""

    def __init__(self, config=None, *, tables=None, changed=False):
        """合成表と第二巡の変更を指定する。"""
        super().__init__(config or sql.CrossMarketConfig(config_value()), "unused")
        self.tables = tables or table_fixture()
        self.pass_no, self.changed, self.closed = 0, changed, 0

    def __enter__(self):
        """実SQLに接続せず自身を返す。"""
        return self

    def close(self):
        """close呼出を記録する。"""
        self.closed += 1

    def preflight(self, *, score=False):
        """二巡で同じ合成版を返す。"""
        self.pass_no += 1
        self.identity_rows = {row["source_original_id"].encode("utf-16le"): row for row in mapping_fixture(self.tables)}
        self.report = {"source": {"source_key": "analysis-current", "source_snapshot_id": 34}, "synthetic": True,
                       "identity_map_sha256": digest(list(self.identity_rows.values()))}
        return self.report

    def table_rows(self, table, *, score=False):
        """選択された使用列だけを返し、scoreがrank/payoutを要求しないことを検査する。"""
        assert not (score and table == "live.netkeiba_payouts")
        fields = ["__migration_source_rowid", *(f for f in sql.FIELDS[table] if not score or f != "rank")]
        self.query_metrics.append({"query_id": "synthetic:" + table, "status": "passed"})
        for source in self.tables[table]:
            row = {name: source[name] for name in fields}
            if self.changed and self.pass_no == 2 and table == "live.netkeiba_odds_entries":
                row["odds_min"] += 0.1
            self.scan_rows[table] = self.scan_rows.get(table, 0) + 1
            yield row


def bundles_fixture():
    """二巡照合を通した合成bundleを返す。"""
    return sql.collect_cross_market(SyntheticReader())[0]


def test_complete_books_keep_outcome_separate_and_settle_only_proven_losers():
    """3期間・全6pairの価格と、完全3的中から構成した明示0円を確認する。"""
    rows, payouts, coverage = sql.build_cross_market(bundles_fixture())
    assert len(rows) == len(payouts) == 18
    assert coverage["candidate_races"] == coverage["accepted_races"] == 3
    assert coverage["excluded_races"] == 0 and len(coverage["period_races"]) == 3
    assert all("payout" not in row and "rank" not in row for row in rows)
    assert payouts[("api-opaque-a", ("1", "4"))] == 0
    assert payouts[("api-opaque-a", ("1", "2"))] == 300


def test_track_description_is_not_compared_to_venue_name():
    """走路説明と競馬場名を同じ列とみなさず、登録venueとの一致だけを使う。"""
    bundle = deepcopy(bundles_fixture()["api-opaque-a"])
    bundle["race"]["course"] = "コース：1,600メートル（芝・左）"
    bundle["parents"][0]["course"] = "東京"
    rows, payouts = sql.validate_race_bundle(bundle)
    assert len(rows) == len(payouts) == 6


@pytest.mark.parametrize("damage,reason", [("status", "unresolved_registered_identity"),
    ("venue", "unverified_mapping_evidence"), ("empty_evidence", "unverified_mapping_evidence"),
    ("api_space", "unverified_mapping_evidence"), ("date", "unverified_mapping_evidence")])
def test_registered_identity_is_verified_explicit_and_byte_exact(damage, reason):
    """未登録/未解決/証拠欠落・属性違い・IDの末尾空白同値を採用しない。"""
    bundle = deepcopy(bundles_fixture()["api-opaque-a"])
    mapped = bundle["identity"]
    if damage == "status": mapped["mapping_status"] = "unresolved"
    elif damage == "venue": mapped["venue_code"] = "08"
    elif damage == "empty_evidence": mapped["evidence_json"] = "{}"
    elif damage == "api_space": mapped["api_race_id"] += " "
    else: mapped["race_date"] = "2025-03-02"
    with pytest.raises(ResearchError, match=reason): sql.validate_race_bundle(bundle)


@pytest.mark.parametrize("damage,reason", [
    ("time", "capture_time_mismatch"), ("id", "identity_attribute_mismatch"),
    ("duplicate_price", "ambiguous_wide_price"), ("missing_price", "incomplete_wide_book"),
    ("missing_payout", "settlement_incomplete_wide"), ("duplicate_payout", "ambiguous_or_unknown_payout"),
    ("dead_heat", "settlement_unknown_rank"), ("withdrawal", "settlement_unknown_rank"),
    ("source", "source_mismatch"), ("parent", "missing_or_ambiguous_result_parent"),
])
def test_unproven_time_id_or_settlement_is_excluded_with_reason(damage, reason):
    """時点不明・曖昧版・未知精算を外れや旧全体互換へ変換しない。"""
    bundle = deepcopy(bundles_fixture()["api-opaque-a"])
    if damage == "time": bundle["odds"][0]["fetched_at"] = "2025-03-01T12:00:00.1234568+00:00"
    elif damage == "id": bundle["results"][0]["netkeiba_race_id"] = "different"
    elif damage == "duplicate_price": bundle["odds"].append(deepcopy(bundle["odds"][0]))
    elif damage == "missing_price": bundle["odds"].pop()
    elif damage == "missing_payout": bundle["payouts"].pop()
    elif damage == "duplicate_payout": bundle["payouts"].append(deepcopy(bundle["payouts"][0]))
    elif damage == "dead_heat": bundle["results"][1]["rank"] = 1
    elif damage == "withdrawal": bundle["results"][0]["rank"] = None
    elif damage == "source": bundle["odds"][0]["source"] = "https://example.invalid/odds"
    elif damage == "parent": bundle["parents"].append(deepcopy(bundle["parents"][0]))
    rows, payouts, coverage = sql.build_cross_market({"api-opaque-a": bundle})
    assert rows == [] and payouts == {}
    assert coverage["excluded_by_reason"] == {reason: 1}
    assert coverage["legacy_population_equivalence"] is False


def test_score_does_not_read_or_adopt_target_outcome_conditions():
    """対象順位/払戻を欠落・改変してもscoreの候補と採否が変わらない。"""
    original = table_fixture()
    changed = deepcopy(original)
    for row in changed["live.netkeiba_result_entries"]: row["rank"] = None
    changed["live.netkeiba_payouts"] = []
    first = sql.collect_cross_market(SyntheticReader(tables=original), race_id="api-opaque-a")
    second = sql.collect_cross_market(SyntheticReader(tables=changed), race_id="api-opaque-a")
    assert first == second
    before = sql.build_cross_market(first[0], score=True)
    after = sql.build_cross_market(second[0], score=True)
    assert before == after and before[2]["accepted_races"] == 1
    assert before[1] == {}


def test_changed_second_pass_is_rejected_without_extra_pass():
    """第二巡の未採用行を含む使用列変更を検出し、第三巡を開始しない。"""
    reader = SyntheticReader(changed=True)
    with pytest.raises(ResearchError, match="source_changed"):
        sql.collect_cross_market(reader)
    assert reader.pass_no == 2


def test_changed_registered_evidence_between_passes_is_rejected():
    """価格が同じでも登録対応の証拠変更を二巡照合で検出する。"""
    class Reader(SyntheticReader):
        """二巡目だけ対応表の証拠を変更する。"""

        def preflight(self, *, score=False):
            """map利用全列のdigestを本番同様にreportへ含める。"""
            report = super().preflight(score=score)
            if self.pass_no == 2:
                next(iter(self.identity_rows.values()))["evidence_json"] = '{"method":"changed"}'
                report["identity_map_sha256"] = digest(list(self.identity_rows.values()))
            return report

    reader = Reader()
    with pytest.raises(ResearchError, match="source_changed"): sql.collect_cross_market(reader)
    assert reader.pass_no == 2


class CatalogReader(sql.CrossMarketReader):
    """固定catalog/権限を返し、SELECT専用preflightの異常を再現する。"""

    def __init__(self, damage=None):
        """異常catalogまたは過剰権限を指定する。"""
        super().__init__(sql.CrossMarketConfig(config_value()), "unused")
        self.damage = damage

    def _small(self, query_id, statement, params=()):
        """queryの版とcatalog条件を監視して合成metadataを返す。"""
        if query_id == "cross:identity":
            return [{"database_name": "jra_unified", "sysadmin": int(self.damage == "admin"), "db_owner": 0, "db_ddladmin": 0, "db_datawriter": 0}]
        if query_id == "cross:permission": return [{"permitted": int(params[-1] == "SELECT")}]
        if query_id == "cross:source":
            assert params == (34,)
            return [{"source_key": "analysis-current", "source_snapshot_id": 34, "status": "verified", "schema_catalog_sha256": "a" * 64}]
        if query_id == "cross:map-columns":
            return [{"name": name, "type_name": kind, "max_length": length, "is_nullable": nullable, "is_computed": False}
                    for name, (kind, length, nullable) in sql.MAP_TYPES.items()]
        if query_id == "cross:map-indexes":
            return [{"name": "UX_map", "is_unique": self.damage != "map_nonunique", "is_disabled": False, "is_hypothetical": False, "has_filter": False,
                     "column_name": name, "key_ordinal": index}
                    for index, name in enumerate(("source_snapshot_id", "source_relation", "__unified_original_sha256"), 1)]
        if query_id == "cross:map-prefix":
            assert params == (9000, 34, "live.races")
            assert "ORDER BY CONVERT(varbinary(max),source_original_id),map_id" in statement
            assert "__unified_original_sha256" not in statement
            return mapping_fixture()
        if query_id == "cross:columns":
            table = params[0]
            rows = []
            for name in (*sql.FIELDS[table], "__migration_source_snapshot_id", "__migration_source_rowid"):
                kind, size = ("bigint", 8) if name in {"rank", "payout", "race_no", "__migration_source_snapshot_id", "__migration_source_rowid"} else (("float", 8) if name in {"win_odds", "odds", "odds_min", "odds_max"} else ("nvarchar", -1))
                rows.append({"name": name, "type_name": kind, "max_length": size, "is_nullable": name != "__migration_source_snapshot_id", "is_computed": False})
            if self.damage == "type" and table == "live.netkeiba_odds_entries":
                next(row for row in rows if row["name"] == "source")["is_computed"] = True
            return rows
        if query_id == "cross:indexes":
            return [{"name": "UX_snapshot_rowid", "column_name": name, "key_ordinal": ordinal,
                     "is_unique": self.damage != "nonunique", "is_disabled": False, "is_hypothetical": False,
                     "has_filter": self.damage == "filtered"}
                    for ordinal, name in enumerate(("__migration_source_snapshot_id", "__migration_source_rowid"), 1)]
        raise AssertionError(query_id)


@pytest.mark.parametrize("damage,reason", [(None, None), ("type", "cross_market_schema_failed"),
    ("filtered", "keyset_requires_unique_index"), ("nonunique", "keyset_requires_unique_index"), ("admin", "unexpected_database_or_privilege"),
    ("map_nonunique", "cross_market_map_route_missing")])
def test_preflight_checks_all_used_columns_and_unfiltered_unique_routes(damage, reason):
    """型・NULL/computedと非filtered unique索引・管理者拒否を検査する。"""
    if reason:
        with pytest.raises(ResearchError, match=reason): CatalogReader(damage).preflight()
    else:
        assert CatalogReader().preflight()["source"]["source_snapshot_id"] == 34


@pytest.mark.parametrize("damage,reason", [("unresolved", "cross_market_identity_coverage_empty"),
    ("duplicate", "cross_market_map_duplicate"), ("missing_column", "cross_market_map_schema_failed"),
    ("cap", "cross_market_map_row_limit")])
def test_map_gate_stops_before_market_rows_when_identity_is_unproven(damage, reason):
    """map未解決・schema/上限/正逆一意の不備を価格読取前に拒否する。"""
    reader = CatalogReader()
    original = reader._small
    calls = []

    def changed(query_id, statement, params=()):
        """指定map異常だけを注入し、hash計算を使わないprefix条件も確認する。"""
        calls.append(query_id)
        rows = original(query_id, statement, params)
        if query_id == "cross:map-columns" and damage == "missing_column":
            return [row for row in rows if row["name"] != "venue_code"]
        if query_id == "cross:map-prefix":
            if damage == "unresolved":
                for row in rows: row["mapping_status"] = "unresolved"
            elif damage == "duplicate": rows.append(deepcopy(rows[0]))
            elif damage == "cap": rows *= 3000
        return rows

    reader._small = changed
    with pytest.raises(ResearchError, match=reason): reader.preflight()
    assert "cross:columns" not in calls


@pytest.mark.parametrize("damage", ["method", "original", "number_bool", "unified", "full", "venue"])
def test_nonempty_mapping_evidence_must_bind_method_ids_and_coordinates(damage):
    """非空dictでも任意方式・別ID・座標不一致ならverified証拠として扱わない。"""
    row = mapping_fixture()[0]
    evidence = json.loads(row["evidence_json"])
    if damage == "method": evidence["rule"] = "arbitrary"
    elif damage == "original": evidence["original_id"] += " "
    elif damage == "number_bool": evidence["stored_race_no"] = True
    elif damage == "unified": row["unified_race_id"] = "JRA:different"
    elif damage == "full": evidence["stored_full_id"] = "0" * 16
    elif damage == "venue": evidence["stored_venue"] = "kyoto"
    row["evidence_json"] = json.dumps(evidence)
    with pytest.raises(ResearchError, match="unverified_mapping_evidence"): sql.validate_registered_identity(row)


def setup_execute(tmp_path, monkeypatch, reader):
    """本番出力rootを一時領域へ置換し、指定合成readerだけを使う。"""
    config = tmp_path / "config.json"
    config.write_text(json.dumps(config_value()), encoding="utf-8")
    monkeypatch.setattr(artifacts, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(artifacts, "code_identity", lambda: {})
    monkeypatch.setattr(sql, "CrossMarketReader", lambda config: reader)
    return config


def test_execute_writes_aggregates_and_replay_matches(tmp_path, monkeypatch):
    """評価/replayは新規runへ集計だけを保存し、旧全体互換を主張しない。"""
    first_reader = SyntheticReader()
    config = setup_execute(tmp_path, monkeypatch, first_reader)
    result = sql.execute_cross_market(config)
    assert first_reader.closed == 1 and result["accepted_races"] == 3
    assert result["legacy_population_equivalence"] is False
    replay_reader = SyntheticReader()
    monkeypatch.setattr(sql, "CrossMarketReader", lambda config: replay_reader)
    replay = sql.execute_cross_market(replay_run_id=result["run_id"])
    assert replay["status"] == "passed" and replay_reader.closed == 1
    files = {p.name for p in (artifacts.RUN_ROOT / replay["run_id"]).iterdir()}
    assert files == {"config.json", "manifest.json", "preflight.json", "coverage.json", "metrics.json"}
    metrics = json.loads((artifacts.RUN_ROOT / replay["run_id"] / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["candidate_count"] == 20


def test_empty_coverage_records_failure_and_reasons_without_retry(tmp_path, monkeypatch):
    """未証明市場だけなら失敗と除外理由を保存し、別sourceへ切り替えない。"""
    tables = table_fixture()
    tables["live.netkeiba_odds_entries"] = []
    reader = SyntheticReader(tables=tables)
    config = setup_execute(tmp_path, monkeypatch, reader)
    with pytest.raises(ResearchError, match="cross_market_coverage_empty") as raised:
        sql.execute_cross_market(config)
    assert reader.pass_no == 2 and reader.closed == 1
    root = artifacts.RUN_ROOT / raised.value.details["run_id"]
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["status"] == "failed"
    assert json.loads((root / "coverage.json").read_text(encoding="utf-8"))["excluded_by_reason"] == {"incomplete_wide_book": 3}


@pytest.mark.parametrize("field,value", [("year", 2024), ("year", True), ("timing_policy", "ignore_times"), ("schema_version", True)])
def test_config_does_not_weaken_semantic_gates(tmp_path, field, value):
    """設定で年・同時点条件や型を緩めることを拒否する。"""
    raw = config_value()
    raw[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ResearchError, match="invalid_cross_market_config"): sql.CrossMarketConfig.load(path)


def test_real_keyset_sql_is_fixed_bounded_and_omits_score_rank():
    """本番keyset生成が各版/キー上限を持ち、scoreのrank列を射影しない。"""
    config = config_value()
    config["limits"]["fetch_rows"] = 1
    config["limits"]["max_candidate_rows"] = 2

    class Reader(sql.CrossMarketReader):
        """1行を返した後、空chunkで走査を終了させる。"""

        @contextmanager
        def _cursor(self, query_id, statement, params):
            """型付きSQLの固定表・版・rowid条件を検査する。"""
            assert "__migration_source_snapshot_id=?" in statement and params[1] == 34
            assert "ORDER BY __migration_source_rowid" in statement
            assert "[rank]" not in statement and "payout" not in statement
            assert params[0] == 1
            row = table_fixture()["live.netkeiba_result_entries"][0]
            fields = ["__migration_source_rowid", *(f for f in sql.FIELDS["live.netkeiba_result_entries"] if f != "rank")]

            class Cursor:
                """DB cursorの有界fetchだけを模倣する。"""

                def fetchmany(self, size):
                    """次chunkでは明示rowid条件を必須とする。"""
                    if len(params) == 3:
                        assert "__migration_source_rowid>?" in statement
                        return []
                    return [tuple(row[f] for f in fields)]

            yield Cursor()

    reader = Reader(sql.CrossMarketConfig(config), "unused")
    rows = list(reader.table_rows("live.netkeiba_result_entries", score=True))
    assert len(rows) == 1 and "rank" not in rows[0]


@pytest.mark.parametrize("fault,reason,calls", [("overflow", "scan_row_limit", 1),
    ("duplicate", "invalid_keyset_rowid", 2), ("null", "invalid_keyset_rowid", 1)])
def test_keyset_rejects_overflow_duplicate_and_null_without_retry(fault, reason, calls):
    """行数上限とrowidの実異常で停止し、終端まで無根拠に読取らない。"""
    config = config_value()
    config["limits"].update(fetch_rows=1, max_candidate_rows=2 if fault == "duplicate" else 1)

    class Reader(sql.CrossMarketReader):
        """有界cursorから指定したrowid異常を返す。"""

        count = 0

        @contextmanager
        def _cursor(self, query_id, statement, params):
            """要求sizeを確認し、故障行1件だけを返す。"""
            self.count += 1
            assert params[0] == 1
            number = None if fault == "null" else self.count if fault == "overflow" else 1
            row = table_fixture()["live.races"][0]
            values = (number, *(row[field] for field in sql.FIELDS["live.races"]))

            class Cursor:
                """毎回1行を返し、親が正しく途中停止するか確認する。"""

                def fetchmany(self, size):
                    """単一故障行を返す。"""
                    return [values]

            yield Cursor()

    reader = Reader(sql.CrossMarketConfig(config), "unused")
    with pytest.raises(ResearchError, match=reason): list(reader.table_rows("live.races"))
    assert reader.count == calls


def test_preflight_failure_preserves_query_diagnostics_and_closes(tmp_path, monkeypatch):
    """schema段階で失敗しても新規runへ固定理由と部分診断を残す。"""
    class Reader(SyntheticReader):
        """前処理で安全な固定例外を出す。"""

        def preflight(self, *, score=False):
            """SQL失敗を再試行せず記録するための合成障害を返す。"""
            self.query_metrics.append({"query_id": "cross:columns", "status": "passed"})
            raise ResearchError("cross_market_schema_failed", 3, table="live.races", column="race_id")

    reader = Reader()
    config = setup_execute(tmp_path, monkeypatch, reader)
    with pytest.raises(ResearchError, match="cross_market_schema_failed") as raised:
        sql.execute_cross_market(config)
    output = artifacts.RUN_ROOT / raised.value.details["run_id"]
    assert reader.closed == 1
    report = json.loads((output / "preflight.json").read_text(encoding="utf-8"))
    assert report["last_query_id"] == "cross:columns"
    assert json.loads((output / "failure.json").read_text(encoding="utf-8"))["details"]["resume_condition"]
