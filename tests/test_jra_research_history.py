"""概要: SQL履歴adapterの旧計算互換・二巡変更検出・旧DB接続禁止を検証する。
作成日: 2026-10-15
入力: 合成の固定版races/runners/results/payouts。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_research_history.py
注意事項: 実DB・外部HTTPへ接続しない。
"""

from copy import deepcopy
from datetime import date, timedelta
import sqlite3
import json

import pytest

from jra_srb.jra_history_dataset import build_history_dataset_from_rows
from jra_srb.jra_history_model import train_history_models
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_history import (HistoryConfig, HistoryReader, collect_history,
    collect_history_score, history_score_records, load_history_score_artifact,
    legacy_row_order, numeric_output_digest)


def tables_fixture():
    """12開催日・4頭で履歴更新と時系列学習ができる行を作る。"""
    tables = {table: [] for table in ("live.races", "live.runners", "live.result_entries", "live.payouts")}
    for index in range(12):
        day = date(2020, 1, 1) + timedelta(days=index)
        key = day.strftime("%Y%m%d") + "0501"
        tables["live.races"].append({"race_id": key, "race_date": day.isoformat(), "race_name": "未勝利",
                                    "surface": "turf", "distance": 1600, "source": "https://www.jra.go.jp/test"})
        tables["live.payouts"].append({"race_id": key})
        for number in range(1, 5):
            tables["live.runners"].append({"race_id": key, "horse_no": str(number), "frame_no": str(number),
                "horse_name": f"horse{number}", "sex_age": "牡3", "weight_carried": "56", "jockey": "j", "trainer": "t"})
            tables["live.result_entries"].append({"race_id": key, "horse_no": str(number), "rank": (number + index) % 4 + 1})
    return tables


class TableReader(HistoryReader):
    """既存SQLと同じ4表の必要列だけを返す。"""

    def __init__(self, tables=None):
        """非秘密の実設定と合成表を用意する。"""
        super().__init__(HistoryConfig.load("configs/research/history_sql_v1.json"), "unused")
        self.tables = tables or tables_fixture()

    def _table_rows(self, table, fields):
        """列projectionを模倣する。"""
        for row in self.tables[table]:
            if table in {"live.payouts", "live.result_entries"} and row["race_id"] == getattr(self, "excluded_outcome_race_id", None):
                continue
            yield {key: row[key] for key in fields}


@pytest.mark.parametrize("recent", [False, True])
def test_history_sql_adapter_preserves_legacy_pure_training(monkeypatch, recent):
    """旧DB/HTTPなしに、同じSQL行の43/49特徴とwin/top3ラベル・学習を照合する。"""
    def forbidden(*args, **kwargs):
        """旧入力経路へ達したら失敗する。"""
        raise AssertionError("external source forbidden")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    import httpx
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    reader = TableReader()
    rows, content = collect_history(reader)
    assert len(content) == 64 and len(rows) == 48
    expected = []
    for race in reader.tables["live.races"]:
        for runner in reader.tables["live.runners"]:
            if race["race_id"] == runner["race_id"]:
                result = next(r for r in reader.tables["live.result_entries"] if (r["race_id"], r["horse_no"]) == (runner["race_id"], runner["horse_no"]))
                expected.append({**{k: v for k, v in race.items() if k != "source"}, **runner, "rank": result["rank"]})
    records, _ = build_history_dataset_from_rows(sorted(rows, key=legacy_row_order))
    reference, _ = build_history_dataset_from_rows(sorted(expected, key=legacy_row_order))
    from jra_srb.jra_history_dataset import FEATURE_NAMES
    from jra_srb.jra_history_model import MODEL_VERSION, RECENT_FORM_MODEL_VERSION
    from jra_srb.jra_recent_form_dataset import RECENT_FORM_SCHEMA, append_recent_form_features
    if recent:
        records = append_recent_form_features(records)
        reference = append_recent_form_features(reference)
    names = RECENT_FORM_SCHEMA if recent else FEATURE_NAMES
    assert records == reference
    assert all(len(row["features"]) == len(names) == (49 if recent else 43) for row in records)
    assert {row["label_win"] for row in records} == {0, 1}
    assert {row["label_top3"] for row in records} == {0, 1}
    model, metrics = train_history_models(records, feature_names=names,
        model_version=RECENT_FORM_MODEL_VERSION if recent else MODEL_VERSION)
    assert model["training_races"] == 12 and metrics["odds_used"] is False


def test_duplicate_result_is_rejected_before_paging_can_hide_it():
    """結果表の重複はメモリ結合前に停止する。"""
    tables = tables_fixture()
    tables["live.result_entries"].append(deepcopy(tables["live.result_entries"][0]))
    with pytest.raises(ResearchError, match="duplicate_key"):
        list(TableReader(tables).history_rows())


def test_changed_input_between_history_passes_is_rejected():
    """同じ結果キーでも特徴に使う値の変更を検出する。"""
    class ChangingReader:
        """呼出ごとに同じキーの距離を変える。"""

        def __init__(self):
            """巡数を初期化する。"""
            self.passes = 0

        def history_rows(self):
            """巡数で値が変わる行を返す。"""
            self.passes += 1
            yield {"race_id": "202001010501", "horse_no": "1", "distance": self.passes}

    with pytest.raises(ResearchError, match="source_changed"):
        collect_history(ChangingReader())


def test_replay_ignores_clock_but_detects_model_changes():
    """作成時刻だけを比較から除き係数の差は検知する。"""
    first = {"created_at": "a", "artifact_hash": "x", "models": {"win": [0.2]}}
    later = {**first, "created_at": "b", "artifact_hash": "y"}
    assert numeric_output_digest(first, {"released_artifact_hash": "x", "loss": .5}) == numeric_output_digest(later, {"released_artifact_hash": "y", "loss": .5})
    later["models"] = {"win": [.3]}
    assert numeric_output_digest(first, {}) != numeric_output_digest(later, {})


@pytest.mark.parametrize("recent", [False, True])
def test_score_input_is_independent_of_target_outcome_and_uses_before_day(recent):
    """対象結果・払戻の削除や変更はscore入力と特徴を変えない。"""
    tables = tables_fixture()
    key = tables["live.races"][-1]["race_id"]
    first = collect_history_score(TableReader(tables), key)
    changed = deepcopy(tables)
    changed["live.result_entries"] = [row for row in changed["live.result_entries"] if row["race_id"] != key]
    changed["live.payouts"] = [row for row in changed["live.payouts"] if row["race_id"] != key]
    second = collect_history_score(TableReader(changed), key)
    assert first == second
    records = history_score_records(*first[:3], recent=recent)
    assert len(records) == 4
    assert all(row["race_date"] < first[1]["race_date"] for row in first[0])
    assert not any(name.startswith("label_") or name == "actual_rank" for row in records for name in row)


@pytest.mark.parametrize("recent", [False, True])
def test_score_matches_legacy_live_pure_calculation_without_database(monkeypatch, recent):
    """同じSQLメモリ行を旧live関数へ供給し全特徴・予測を一致させる。"""
    from types import SimpleNamespace
    from jra_srb import jra_history_dataset as legacy
    from jra_srb import jra_recent_form_dataset as recent_legacy
    from jra_srb.jra_history_model import score_live_records

    tables = tables_fixture()
    key = tables["live.races"][-1]["race_id"]
    rows, card, sizes, _ = collect_history_score(TableReader(tables), key)

    class MemoryConnection:
        """旧SQLの返値だけを同一メモリ入力から作る。"""

        def execute(self, sql, params):
            """history列またはrecent列をSQLの旧projectionで返す。"""
            self.recent = "as field_size" in sql
            return self

        def fetchall(self):
            """旧SQL同様の順序と結果頭数で行を返す。"""
            ordered = sorted(rows, key=legacy_row_order)
            return [(row["horse_name"], row["rank"], sizes[row["race_id"]]) for row in ordered] if self.recent else [
                {**row, "history_field_size": sizes[row["race_id"]]} for row in ordered
            ]

        def close(self):
            """外部接続を持たない。"""

        def __enter__(self):
            """メモリ返値を使う。"""
            return self

        def __exit__(self, *args):
            """外部資源を持たない。"""

    monkeypatch.setattr(legacy, "open_analysis_read", lambda *args: MemoryConnection())
    monkeypatch.setattr(recent_legacy, "open_analysis_read", lambda *args: MemoryConnection())
    target = SimpleNamespace(**{key: value for key, value in card.items() if key != "runners"},
                             runners=[SimpleNamespace(**runner) for runner in card["runners"]])
    expected = legacy.build_live_feature_records("unused", target_date=date.fromisoformat(card["race_date"]), course="tokyo", card=target)
    if recent:
        expected = recent_legacy.append_recent_form_live_features(expected, "unused", target_date=date.fromisoformat(card["race_date"]))
    actual = history_score_records(rows, card, sizes, recent=recent)
    assert [row["features"] for row in actual] == [row["features"] for row in expected]
    records, _ = build_history_dataset_from_rows(sorted(collect_history(TableReader(tables))[0], key=legacy_row_order))
    if recent:
        records = recent_legacy.append_recent_form_features(records)
    model, _ = train_history_models(records, feature_names=recent_legacy.RECENT_FORM_SCHEMA if recent else legacy.FEATURE_NAMES)
    assert [[row[name] for name in ("horse_no", "win_probability", "top3_probability")] for row in score_live_records(model, actual)] == [
        [row[name] for name in ("horse_no", "win_probability", "top3_probability")] for row in score_live_records(model, expected)]


def test_score_result_sql_excludes_target_before_fetch():
    """対象OutcomeをSQLのWHERE条件で除外してからdriverへ渡す。"""
    from contextlib import contextmanager
    reader = TableReader()
    reader.excluded_outcome_race_id = "202001120501"
    reader.pass_streams = {}
    reader.scan_rows = {}
    captured = []

    @contextmanager
    def cursor(query_id, sql, params):
        """SQL文字列とbind値だけを観測する。"""
        captured.append((sql, params))
        yield type("Cursor", (), {"fetchmany": lambda self, size: []})()

    reader._cursor = cursor
    list(HistoryReader._table_rows(reader, "live.result_entries", ("race_id", "horse_no", "rank")))
    list(HistoryReader._table_rows(reader, "live.payouts", ("race_id",)))
    assert all("race_id<>?" in sql and reader.excluded_outcome_race_id in params for sql, params in captured)


def test_holdout_train_only_then_release_refits_all_rows(monkeypatch):
    """時系列holdoutのfit対象と最終全量refitを別々に観測する。"""
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    records, _ = build_history_dataset_from_rows(sorted(collect_history(TableReader())[0], key=legacy_row_order))
    scaler_fit, model_fit = [], []
    original_scaler, original_model = StandardScaler.fit, LogisticRegression.fit

    def scale(self, values, *args, **kwargs):
        """各scalerのfit件数を記録する。"""
        scaler_fit.append(len(values))
        return original_scaler(self, values, *args, **kwargs)

    def fit(self, values, *args, **kwargs):
        """各目的変数のfit件数を記録する。"""
        model_fit.append(len(values))
        return original_model(self, values, *args, **kwargs)

    monkeypatch.setattr(StandardScaler, "fit", scale)
    monkeypatch.setattr(LogisticRegression, "fit", fit)
    model, metrics = train_history_models(records)
    assert scaler_fit == [40, 48] and model_fit == [40, 40, 48, 48]
    assert metrics["split"]["cutoff_date"] == "2020-01-11"
    assert metrics["split"]["train_runner_rows"] == 40 and model["training_runner_rows"] == 48


def saved_model(tmp_path, monkeypatch):
    """合成学習から改変を検査できるcomplete runを保存する。"""
    from jra_srb import jra_research_artifacts as artifacts
    from jra_srb.jra_research_contracts import digest
    monkeypatch.setattr(artifacts, "RUN_ROOT", tmp_path)
    config = HistoryConfig.load("configs/research/history_sql_v1.json")
    records, _ = build_history_dataset_from_rows(sorted(collect_history(TableReader())[0], key=legacy_row_order))
    model, _ = train_history_models(records)
    contract = {"profile_id": "history_sql_v1", "feature_names": model["feature_names"],
        "history_identity": "horse_name_legacy", "update_policy": "after_each_race_legacy", "source_snapshot": 34,
        "source_input_sha256": "a" * 64, "availability": "retrospective_compatibility",
        "release_fit": "all_rows_after_holdout_evaluation"}
    run = artifacts.RunArtifacts(config.raw, "history")
    run.write_json("model_history.json", {"contract": contract, "contract_sha256": digest(contract), "model": model})
    run.finish(input_content_sha256="a" * 64, feature_contract_sha256=digest(contract), model_sha256=digest(model))
    return run, config


@pytest.mark.parametrize("corruption", ["legacy", "unfinished", "profile", "order", "shape", "bool", "scale", "coefficient"])
def test_history_score_rejects_unproven_or_corrupt_artifacts(tmp_path, monkeypatch, corruption):
    """旧無契約・未完了・列順・型・係数改変をscore前に拒否する。"""
    run, config = saved_model(tmp_path, monkeypatch)
    path = run.path / "model_history.json"
    assert load_history_score_artifact(path, config)[0]["training_runner_rows"] == 48
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "legacy":
        wrapper = wrapper["model"]
    elif corruption == "unfinished":
        manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
        manifest["status"] = "running"
        (run.path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    elif corruption == "profile":
        wrapper["contract"]["profile_id"] = "recent_form_sql_v2"
    elif corruption == "order":
        wrapper["model"]["feature_names"].reverse()
    elif corruption == "shape":
        wrapper["model"]["models"]["win"]["coefficients"].pop()
    elif corruption == "bool":
        wrapper["model"]["scaler"]["mean"][0] = True
    elif corruption == "scale":
        wrapper["model"]["scaler"]["scale"][0] = 0
    else:
        wrapper["model"]["models"]["win"]["coefficients"][0] += 1
    if corruption in {"shape", "bool", "scale"}:
        from jra_srb.jra_history_model import _artifact_hash
        from jra_srb.jra_research_contracts import digest
        model = wrapper["model"]
        model["artifact_hash"] = _artifact_hash({key: value for key, value in model.items() if key != "artifact_hash"})
        manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
        manifest["model_sha256"] = digest(model)
        (run.path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ResearchError, match="history_model_contract_mismatch"):
        load_history_score_artifact(path, config)


@pytest.mark.parametrize("fail_after_close", [False, True])
def test_score_closes_sql_before_compute_and_publishes_only_allowed_artifacts(tmp_path, monkeypatch, fail_after_close):
    """SQL close後のscoreだけを許し、失敗runをcompleteとして公開しない。"""
    from jra_srb import jra_research_history as history
    import httpx
    run, _ = saved_model(tmp_path, monkeypatch)
    closed = []

    class ScoreReader(TableReader):
        """SQL境界を観測する合成reader。"""

        def __init__(self, config):
            """fixtureのみで初期化する。"""
            super().__init__()

        def __enter__(self):
            """接続中であることを観測する。"""
            closed.append(False)
            return self

        def __exit__(self, *args):
            """計算開始前に接続を閉じる。"""
            closed[-1] = True

        def preflight(self):
            """非秘密の合成事前検査結果を返す。"""
            return {"source": {"source_snapshot_id": 34}}

    def forbidden(*args, **kwargs):
        """研究から旧DB・HTTPに到達したら失敗する。"""
        raise AssertionError("external source forbidden")

    original = history.history_score_records

    def compute(*args, **kwargs):
        """SQL close後だけ純計算し、任意の失敗も模擬する。"""
        assert closed == [True]
        if fail_after_close:
            raise ResearchError("synthetic_compute_failure", 4)
        return original(*args, **kwargs)

    monkeypatch.setattr(history, "HistoryReader", ScoreReader)
    monkeypatch.setattr(history, "history_score_records", compute)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    before = set(tmp_path.iterdir())
    if fail_after_close:
        with pytest.raises(ResearchError, match="synthetic_compute_failure"):
            history.execute_history_score("configs/research/history_sql_v1.json", run.path / "model_history.json", "202001120501")
    else:
        output = history.execute_history_score("configs/research/history_sql_v1.json", run.path / "model_history.json", "202001120501")
        assert output["outcome_read"] is False and len(output["predictions"]) == 4
    created, = set(tmp_path.iterdir()) - before
    manifest = json.loads((created / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == ("failed" if fail_after_close else "complete")
    assert {path.name for path in created.iterdir()} == {"config.json", "manifest.json", "preflight.json", "failure.json" if fail_after_close else "metrics.json"}


def schema_fixture(table):
    """移送済みlive表の必要列契約をsynthetic metadataとして返す。"""
    from jra_srb.jra_research_history import HISTORY_COLUMNS
    result = []
    for name in (*HISTORY_COLUMNS[table], "__migration_source_snapshot_id", "__migration_source_rowid"):
        bigint = name in {"rank", "__migration_source_snapshot_id", "__migration_source_rowid"}
        result.append({"column_name": name, "sql_type": "bigint" if bigint else "nvarchar",
                       "max_length": 8 if bigint else -1, "is_nullable": name != "__migration_source_snapshot_id",
                       "is_computed": False})
    return result


@pytest.mark.parametrize("table", ["live.races", "live.runners", "live.result_entries", "live.payouts"])
@pytest.mark.parametrize("corruption", [None, "missing", "type", "length", "nullable", "computed", "invisible"])
def test_history_preflight_validates_all_used_column_metadata(table, corruption):
    """欠列・SQL型・長さ・NULL・computed・非可視を学習前に拒否する。"""
    class MetadataReader(TableReader):
        """固定版・権限・索引は適正、指定列metadataだけを変える。"""

        def _small(self, query_id, sql, params=()):
            """事前検査の小さなmetadataを返す。"""
            if query_id == "history_identity":
                return [{"database_name": "jra_unified", "sysadmin": 0, "db_owner": 0, "db_ddladmin": 0, "db_datawriter": 0}]
            if query_id == "history_permission":
                return [{"permitted": int(params[-1] == "SELECT")}]
            if query_id == "history_source":
                return [{"source_key": "analysis-current", "source_snapshot_id": 34, "status": "verified", "schema_catalog_sha256": "a" * 64}]
            if query_id == "history_columns":
                rows = schema_fixture(params[0])
                if params[0] == table:
                    if corruption == "missing":
                        rows.pop()
                    elif corruption == "invisible":
                        return []
                    elif corruption:
                        row = next(row for row in rows if row["column_name"] == "__migration_source_snapshot_id")
                        field, value = {"type": ("sql_type", "int"), "length": ("max_length", 4),
                                        "nullable": ("is_nullable", True), "computed": ("is_computed", True)}[corruption]
                        row[field] = value
                return rows
            if query_id == "history_indexes":
                assert "i.has_filter=0" in sql
                return [{"name": "unique_rowid", "is_unique": True, "column_name": name, "key_ordinal": index}
                        for index, name in enumerate(("__migration_source_snapshot_id", "__migration_source_rowid"), 1)]
            raise AssertionError(query_id)

    if corruption:
        expected = "history_schema_metadata_unavailable" if corruption == "invisible" else "history_schema_contract_failed"
        with pytest.raises(ResearchError, match=expected):
            MetadataReader().preflight()
    else:
        assert MetadataReader().preflight()["source"]["source_snapshot_id"] == 34
