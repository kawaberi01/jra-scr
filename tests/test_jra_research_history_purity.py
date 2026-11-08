"""概要: R01の学習・replay・scoreを通し、禁止入力と許可外の保存を動的に検査する。
作成日: 2026-10-16
入力: 合成SQL行。明示環境変数指定時だけ既存SQL Serverの固定34版。
出力: pytest結果。実SQL時は新規共通runへのモデル/評価と監査記録。
実行例: uv run pytest -q tests/test_jra_research_history_purity.py
注意事項: JRA_RESEARCH_HISTORY_PURITY_SQL=1で実SQL読取/学習を行う。DB変更なし。
"""

from contextlib import contextmanager, ExitStack
import builtins
import io
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sqlite3.dbapi2
import sys
from unittest.mock import patch
import urllib.request

import httpx
import pytest

from jra_srb import jra_research_artifacts as artifacts
from jra_srb import jra_research_history as history
from jra_srb.jra_research_history import HistoryReader
from jra_srb.jra_research_contracts import ResearchError
from test_jra_research_history import TableReader, tables_fixture


@contextmanager
def guarded_history_io(run_root, config_path):
    """R01の既知呼出閉包に旧DB/HTTP/業務ファイルが入ったら停止する。

    Notes:
        コード/設定/研究専用秘密と、新規runの許可artifactだけを許可する。
        本監視はPythonのopenと既知DB/HTTP入口の範囲。OS全体の監視ではない。
    """
    root = run_root.resolve()
    initial = {p.name for p in root.iterdir()} if root.exists() else set()
    inputs = {Path(config_path).resolve(), Path(os.environ.get("JRA_SRB_RESEARCH_ENV_FILE", "data/storage/research.env")).resolve()}
    attempts = []
    extra_targets = []
    for module_name, names in (("requests.sessions", ("Session.request", "Session.send")),
                               ("duckdb", ("connect", "sql", "query")), ("pyodbc", ("connect",))):
        if importlib.util.find_spec(module_name) is not None:
            module = importlib.import_module(module_name)
            for name in names:
                owner = module
                parts = name.split(".")
                for part in parts[:-1]:
                    owner = getattr(owner, part)
                if hasattr(owner, parts[-1]):
                    extra_targets.append((owner, parts[-1]))

    def forbidden(*args, **kwargs):
        """秘密値を残さずDB/HTTP試行の存在だけを記録する。"""
        attempts.append("non_sqlserver_db_or_http")
        raise ResearchError("forbidden_research_io", 4)

    def opened(original, file, mode="r", *args, **kwargs):
        """元データ入力と新規run以外への書込を拒否して通常openへ委譲する。"""
        if isinstance(file, (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(file)).resolve()
            parts = path.relative_to(root).parts if path.is_relative_to(root) else ()
            new_artifact = (len(parts) == 2 and parts[0] not in initial
                            and (parts[1] in artifacts.JSON_NAMES or
                                 parts[1].endswith(".json.tmp") and parts[1][:-4] in artifacts.JSON_NAMES))
            writing = any(flag in mode for flag in "wax+")
            business_file = (path.is_relative_to(Path("data").resolve())
                             or path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".gz", ".json", ".jsonl", ".csv", ".parquet", ".joblib", ".pkl", ".npy", ".npz"}
                             or str(path).startswith("\\\\"))
            # dependency内のpackage設定はデータ補完とは区別する。
            package_json = path.suffix.lower() == ".json" and path.is_relative_to(Path(sys.prefix).resolve())
            if (writing and not new_artifact) or (business_file and not new_artifact and path not in inputs and not package_json):
                attempts.append("forbidden_file_write" if writing else "forbidden_business_file_read")
                raise ResearchError("forbidden_research_io", 4)
        return original(file, mode, *args, **kwargs)

    real_open, real_io_open, real_import = builtins.open, io.open, builtins.__import__

    def guarded_import(name, *args, **kwargs):
        """未導入DBも実行途中のimport時点で拒否し、接続監視の空白を作らない。"""
        if name.split(".")[0] in {"duckdb", "pyodbc"}:
            return forbidden()
        return real_import(name, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch("builtins.open", lambda *a, **k: opened(real_open, *a, **k)))
        stack.enter_context(patch("io.open", lambda *a, **k: opened(real_io_open, *a, **k)))
        stack.enter_context(patch("builtins.__import__", guarded_import))
        for owner, name in ((sqlite3, "connect"), (sqlite3.dbapi2, "connect"),
                            (httpx.Client, "request"), (httpx.Client, "send"),
                            (httpx.AsyncClient, "request"), (httpx.AsyncClient, "send"),
                            (urllib.request, "urlopen"), *extra_targets):
            stack.enter_context(patch.object(owner, name, forbidden))
        yield attempts


def validate_artifact_content(value):
    """許可JSONに元行・市場明細・全特徴量の既知保存形状が紛れ込むことを拒否する。"""
    forbidden_keys = {"payload_json", "compressed_payload", "raw_records", "raw_rows", "features",
                      "runners", "result_entries", "entries_json", "sql_rows", "records", "dataset", "dataframe"}
    if isinstance(value, dict):
        assert not forbidden_keys.intersection(value), "forbidden business payload in allowed artifact"
        for child in value.values():
            validate_artifact_content(child)
    elif isinstance(value, list):
        for child in value:
            validate_artifact_content(child)


class SyntheticReader(TableReader):
    """SQL接続だけを合成表へ置換し、以後の本番関数をそのまま実行する。"""

    def __init__(self, config):
        """対象profileの設定と整合する合成表を作る。"""
        HistoryReader.__init__(self, config, "unused")
        self.tables = tables_fixture()

    def __enter__(self):
        """実接続せずreaderを返す。"""
        return self

    def __exit__(self, *args):
        """合成readerには外部資源がない。"""

    def preflight(self):
        """二巡とreplayで同じ合成版診断を返す。"""
        return {"source": {"status": "verified", "source_snapshot_id": 34}, "synthetic": True}


def run_guarded_history(config_path, race_id):
    """学習/replay/scoreを本番関数で通し、実行前後の許可artifactと数値一致を検査する。"""
    root = artifacts.RUN_ROOT
    initial = {p.name for p in root.iterdir()} if root.exists() else set()
    with guarded_history_io(root, config_path) as attempts:
        trained = history.execute_history(config_path)
        replayed = history.execute_history(replay_run_id=trained["run_id"])
        model = root / trained["run_id"] / "model_history.json"
        scored = history.execute_history_score(config_path, model, race_id)
    expected = {trained["run_id"], replayed["run_id"], scored["run_id"]}
    assert {p.name for p in root.iterdir()} - initial == expected
    files = {}
    for run_id in expected:
        files[run_id] = sorted(p.name for p in (root / run_id).iterdir())
        names = {"config.json", "manifest.json", "preflight.json", "metrics.json"}
        if run_id != scored["run_id"]:
            names |= {"model_history.json", "coverage.json"}
        assert set(files[run_id]) == names
        for name in names:
            validate_artifact_content(json.loads((root / run_id / name).read_text(encoding="utf-8")))
    def load(run_id, name):
        """今回作った許可artifactをUTF-8で再取得する。"""
        return json.loads((root / run_id / name).read_text(encoding="utf-8"))
    train_manifest, replay_manifest = (load(row["run_id"], "manifest.json") for row in (trained, replayed))
    assert train_manifest["input_content_sha256"] == replay_manifest["input_content_sha256"]
    assert train_manifest["numeric_outputs_sha256"] == replay_manifest["numeric_outputs_sha256"]
    metrics = load(trained["run_id"], "metrics.json")
    assert set(metrics["runner_metrics"]) == {"win", "top3"}
    assert scored["outcome_read"] is False and scored["predictions"]
    assert not attempts
    return {"profile_id": trained["profile_id"], "train_run_id": trained["run_id"],
            "replay_run_id": replayed["run_id"], "score_run_id": scored["run_id"],
            "forbidden_attempts": attempts, "files": files,
            "variant_metrics": metrics["runner_metrics"], "split": metrics["split"],
            "guard_scope": "Python open + sqlite3/dbapi2 + httpx sync/async + urllib + installed requests/duckdb/pyodbc; reject duckdb/pyodbc imports; R01 normal commands",
            "overall_complete": False}


@pytest.mark.parametrize("profile", ["history_sql_v1", "recent_form_sql_v2"])
def test_synthetic_history_training_replay_score_with_forbidden_io_guards(tmp_path, monkeypatch, profile):
    """合成入力でR01両profileの通常実行・数値再現・保存禁止を検証する。"""
    monkeypatch.setattr(artifacts, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(history, "HistoryReader", SyntheticReader)
    report = run_guarded_history(Path(f"configs/research/{profile}.json"), "202001120501")
    assert report["profile_id"] == profile


@pytest.mark.parametrize("kind", ["sqlite", "http", "input", "json_input", "output", "requests", "duckdb_import", "pyodbc_import"])
def test_guard_rejects_forbidden_calls_instead_of_reporting_zero(tmp_path, kind):
    """監視器自身が旧DB/HTTP/旧dataset/許可外出力の試行を検出する。"""
    config = tmp_path / "config.json"
    with guarded_history_io(tmp_path / "runs", config) as attempts:
        with pytest.raises(ResearchError, match="forbidden_research_io"):
            if kind == "sqlite":
                sqlite3.connect(":memory:")
            elif kind == "http":
                httpx.Client().get("http://invalid.invalid/")
            elif kind == "input":
                (tmp_path / "old.jsonl").read_text(encoding="utf-8")
            elif kind == "json_input":
                (tmp_path / "race.json").read_text(encoding="utf-8")
            elif kind == "requests":
                import requests
                requests.get("http://invalid.invalid/")
            elif kind.endswith("_import"):
                __import__(kind.removesuffix("_import"))
            else:
                (tmp_path / "raw.txt").write_text("not allowed", encoding="utf-8")
        assert len(attempts) == 1


def test_allowed_filename_does_not_allow_feature_vectors_in_payload():
    """許可名metrics.jsonでも特徴量ベクトルの保存形状を検出する。"""
    with pytest.raises(AssertionError, match="forbidden business payload"):
        validate_artifact_content({"metrics": {"records": [{"features": [1., 2.]}]}})


@pytest.mark.skipif(os.environ.get("JRA_RESEARCH_HISTORY_PURITY_SQL") != "1", reason="explicit SQL purity run only")
@pytest.mark.parametrize("profile", ["history_sql_v1", "recent_form_sql_v2"])
def test_actual_sql_history_training_replay_score_with_guards(profile):
    """固定34版の実SQLを使い、新規runだけへ監視付きR01の証拠を保存する。"""
    report = run_guarded_history(Path(f"configs/research/{profile}.json"), "202610120811")
    audit = artifacts.RunArtifacts({"profile_id": profile}, "history-purity-audit")
    audit.write_json("metrics.json", report)
    audit.finish(overall_complete=False, profile_id=profile, forbidden_attempts=0,
                 train_run_id=report["train_run_id"], replay_run_id=report["replay_run_id"],
                 score_run_id=report["score_run_id"])
    print(json.dumps({"purity_audit_run_id": audit.run_id, **report}, ensure_ascii=True))
