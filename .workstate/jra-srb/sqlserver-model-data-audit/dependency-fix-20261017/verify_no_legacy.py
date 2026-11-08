"""概要: 現用8入口を旧SQLite禁止条件と実SQLのrollback transactionで確認する。
作成日: 2026-10-17
入力: 共通runtime.env、修正済み現用コード8本。引数なし。
出力: 同じフォルダーのruntime-verification.jsonと標準出力の進捗。
実行例: uv run --frozen python .workstate/jra-srb/sqlserver-model-data-audit/dependency-fix-20261017/verify_no_legacy.py
注意事項: 実SQLへ専用IDを一時挿入し必ずrollbackする。旧DB読取・業務データ更新・HTTP取得は行わない。
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).with_name("runtime-verification.json")
SKILLS = Path("C:/Users/main/skills")
MISSING = ROOT / "data/__nonexistent_sql_dependency_probe__/analysis.sqlite"
REPORT = {"started_at": datetime.now(timezone.utc).isoformat(), "status": "running", "checks": [], "stage": "setup"}
FORBIDDEN = {"sqlite_connect": 0, "old_data_open": 0, "old_path_exists": 0}
ACTIVE_GUARD = False


def audit(event, args):
    """旧データのopenとSQLite接続を拒否し、試行数を記録する。"""
    if not ACTIVE_GUARD:
        return
    kind = None
    if event == "sqlite3.connect":
        kind = "sqlite_connect"
    elif event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0]).lower()
        if any(mark in name for mark in (".sqlite", ".jsonl", ".bak")):
            kind = "old_data_open"
    if kind:
        FORBIDDEN[kind] += 1
        raise RuntimeError("旧データアクセスは禁止されています")


def checked_exists(path):
    """旧SQLiteの存在確認も失敗させ、SQL分岐の短絡条件を確認する。"""
    if ".sqlite" in str(path).lower():
        FORBIDDEN["old_path_exists"] += 1
        raise RuntimeError("旧パスの存在判定は禁止されています")
    return ORIGINAL_EXISTS(path)


def check(name, condition=True, **details):
    """検証結果を即時保存し、失敗時は後続を停止する。"""
    REPORT["checks"].append({"name": name, "passed": bool(condition), **details})
    OUT.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(name, "OK" if condition else "FAILED", flush=True)
    if not condition:
        raise AssertionError(name)


def load(name, path):
    """現用スクリプトをmainを実行せず読み込み、コードSHAを記録する。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    REPORT.setdefault("code_sha256", {})[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return module


def run_main(module, payload):
    """CLIの標準入力・出力を使って予想保存/評価mainを実行する。"""
    output = io.StringIO()
    with patch.object(sys, "argv", [module.__file__, "--db", str(MISSING)]), patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
        module.main()
    return json.loads(output.getvalue())


class DriverLease:
    """本物のconnectionを借用し、操作単位のcommit/rollback/closeだけを保留する。"""

    def __init__(self, connection):
        """試験が所有する実connectionを保持する。"""
        self.connection = connection

    @property
    def timeout(self):
        """実connectionのtimeoutを返す。"""
        return self.connection.timeout

    @timeout.setter
    def timeout(self, value):
        """実connectionへtimeoutを適用する。"""
        self.connection.timeout = value

    def cursor(self):
        """本物のSQL cursorを返す。"""
        return self.connection.cursor()

    def commit(self):
        """本体Storeのcommit要求を数え、試験終了まで確定を保留する。"""
        REPORT["deferred_commits"] = REPORT.get("deferred_commits", 0) + 1

    def rollback(self):
        """reader終了時のrollbackを試験終了まで保留する。"""

    def close(self):
        """操作終了時に共有実connectionを閉じない。"""


def run():
    """旧データ禁止・実SQL検証・rollback後の残存確認を順番に行う。"""
    global ACTIVE_GUARD, ORIGINAL_EXISTS
    sys.stdout.reconfigure(encoding="utf-8")
    check("compat_path_absent", not MISSING.exists())
    sys.addaudithook(audit)
    ACTIVE_GUARD = True
    ORIGINAL_EXISTS = Path.exists
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.pop("JRA_SRB_STORAGE_ENV_FILE", None)
    paths = {
        "J1": SKILLS / "jra-race-session-complete/scripts/save_jra_prediction_to_analysis_sqlite.py",
        "J2": SKILLS / "jra-race-session-complete/scripts/evaluate_saved_prediction_to_analysis_sqlite.py",
        "N1": SKILLS / "nankan-race-session-complete/scripts/save_nankan_prediction_to_analysis_sqlite.py",
        "N2": SKILLS / "nankan-race-session-complete/scripts/evaluate_saved_prediction_to_analysis_sqlite.py",
        "N3": SKILLS / "nankan-result-save-to-analysis-sqlite/scripts/save_nankan_result_to_analysis_sqlite.py",
        "J3": SKILLS / "jra-day-confidence-ranking/scripts/rank_confidence.py",
        "J4": ROOT / "scripts/jra_live_prediction_day.py",
        "J5": ROOT / "scripts/jra_major_venue_shadow_day.py",
    }
    modules = {name: load(name, path) for name, path in paths.items()}
    from jra_srb.storage_config import SqlServerSettings
    from jra_srb.sqlserver_db import SqlServerConnection, SqlServerStorageError
    from jra_srb.sqlserver_schema import ANALYSIS_TABLES
    import mssql_python
    os.chdir(SKILLS)
    with patch.object(Path, "exists", checked_exists):
        for name in ("J1", "J2", "N1", "N2", "N3"):
            os.environ.pop("JRA_SRB_STORAGE_ENV_FILE", None)
            store = modules[name].bootstrap_store(MISSING)
            check(name + "_missing_path_other_cwd", type(store).__name__ == "SqlServerAnalysisStore" and store.settings.database == "jra_unified")
        settings = SqlServerSettings.from_env()
        with SqlServerConnection(settings, ANALYSIS_TABLES, read_only=True) as conn:
            check("real_reader_database", conn._raw("SELECT DB_NAME()").fetchone()[0] == "jra_unified")
            real_prediction = conn.execute("select race_id from predictions limit 1").fetchone()
            check("real_existing_prediction", real_prediction is not None and modules["J4"]._has_prediction(MISSING, real_prediction[0]))
        for name in ("J1", "J2", "N1", "N2", "N3", "J3"):
            call = (lambda: modules[name].load_latest_db(MISSING, "2099-12-31")) if name == "J3" else (lambda: modules[name].bootstrap_store(MISSING))
            for key, value, expected in (("JRA_SRB_STORAGE_BACKEND", "sqlite", RuntimeError), ("JRA_SRB_SQLSERVER_READER_CONNECTION_STRING", "", ValueError)):
                try:
                    with patch.dict(os.environ, {key: value}), patch.object(mssql_python, "connect", side_effect=AssertionError("接続前に拒否する必要があります")):
                        call()
                except expected:
                    check(name + "_reject_" + key)
                else:
                    check(name + "_reject_" + key, False)
        try:
            with patch.object(mssql_python, "connect", side_effect=RuntimeError("検証用接続障害")):
                modules["J4"]._has_prediction(MISSING, "dependency-probe")
        except SqlServerStorageError:
            check("sql_failure_no_fallback")
        else:
            check("sql_failure_no_fallback", False)
        token = "dependency-probe-" + uuid4().hex
        REPORT["test_id"] = token
        raw = mssql_python.connect(settings.writer_connection_string, autocommit=False)
        try:
            with patch.object(mssql_python, "connect", return_value=DriverLease(raw)):
                conn = SqlServerConnection(settings, ANALYSIS_TABLES)
                for table, column in (("predictions", "prediction_id"), ("race_results", "race_id"), ("jra_scout_runs", "run_id")):
                    check("reserved_id_absent_" + table, conn.execute(f"select count(*) from {table} where {column} = ?", (token,)).fetchone()[0] == 0)
                for name, course in (("J1", "tokyo"), ("N1", "kawasaki")):
                    race = token + "-" + name
                    payload = {"prediction_id": race, "race_id": race, "theory_version": modules["J5"].THEORY_VERSION,
                        "budget": 100, "pre_race_snapshot": {"date": "2099-12-31", "course": course, "race_no": 1},
                        "prediction_json": {"generated_before_result": True},
                        "prediction_tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}]}
                    check(name + "_not_saved", not modules["J4"]._has_prediction(MISSING, race) and not modules["J5"]._already_saved(MISSING, race))
                    saved = run_main(modules[name], payload)
                    record = modules[name].bootstrap_store(MISSING).get_prediction_record(race)
                    check(name + "_save_readback", saved.get("verified", True) and record.race_id == race and len(record.prediction_tickets) == 1 and saved["backend"] == "sqlserver" and saved["predictions"] == 1 and saved["prediction_tickets"] == 1)
                    check(name + "_saved", modules["J4"]._has_prediction(MISSING, race) and modules["J5"]._already_saved(MISSING, race))
                    result = {"race_id": race, "race_name": "検証専用", "fetched_at": "2099-12-31T00:00:00+00:00", "source": "dependency-verification",
                        "results": [{"rank": "1", "horse_no": "1", "horse_name": "検証馬"}],
                        "payouts": [{"bet_type": "単勝", "combination": "1", "payout": "250", "popularity": "1"}]}
                    counts = modules["N3"].save_result(MISSING, result)
                    check(name + "_result_save_readback", counts == {"race_results": 1, "result_entries": 1, "payouts": 1})
                    check(name + "_result_idempotent", modules["N3"].save_result(MISSING, result) == counts)
                    evaluated = run_main(modules["J2" if name == "J1" else "N2"], {"prediction_id": race, "evaluation_id": race})
                    evaluation = modules[name].bootstrap_store(MISSING).get_evaluation_record(race)
                    check(name + "_evaluation_readback", evaluated.get("verified", True) and evaluation.prediction_id == race and evaluated["total_bet"] == 100 and evaluated["total_payout"] == 250)
                check("scout_reserved_date_absent", conn.execute("select count(*) from jra_scout_runs where race_date = ?", ("2099-12-31",)).fetchone()[0] == 0)
                for index in (1, 2):
                    run_id = token + f"-scout-{index}"
                    conn.execute("insert into jra_scout_runs (run_id,race_date,observed_at,phase,status,race_count,analyzed_count,candidates_json,errors_json) values (?,?,?,?,?,?,?,?,?)",
                        (run_id, "2099-12-31", f"2099-12-31T0{index}:00:00+00:00", "quick", "complete", 1, 1, "[]", "[]"))
                    entry = {"race_id": token, "course": "tokyo", "race_no": 1, "grade": "B"}
                    conn.execute("insert into jra_scout_entries (run_id,race_id,course,race_no,grade,entry_json) values (?,?,?,?,?,?)", (run_id, token, "tokyo", 1, "B", json.dumps(entry)))
                os.environ.pop("JRA_SRB_STORAGE_ENV_FILE", None)
                latest = modules["J3"].load_latest_db(MISSING, "2099-12-31")
                check("J3_latest_same_day_other_cwd", latest["run_id"] == token + "-scout-2" and len(latest["entries"]) == 1 and "JRA全レース相対確度" in modules["J3"].render(latest, [], []))
                try:
                    modules["J3"].load_latest_db(MISSING, "2099-12-30")
                except RuntimeError:
                    check("J3_no_saved_result")
                else:
                    check("J3_no_saved_result", False)
        finally:
            raw.rollback()
            raw.close()
            REPORT["rolled_back"] = True
        with SqlServerConnection(settings, ANALYSIS_TABLES, read_only=True) as conn:
            for table, column in (("races", "race_id"), ("predictions", "race_id"), ("prediction_tickets", "race_id"), ("race_results", "race_id"), ("result_entries", "race_id"), ("payouts", "race_id"), ("evaluations", "race_id"), ("jra_scout_runs", "run_id"), ("jra_scout_entries", "run_id")):
                check("rollback_no_rows_" + table, conn.execute(f"select count(*) from {table} where {column} like ?", (token + "%",)).fetchone()[0] == 0)
            check("rollback_no_ticket_results", conn.execute("select count(*) from evaluation_ticket_results where evaluation_id like ?", (token + "%",)).fetchone()[0] == 0)
            check("rollback_no_receipts", conn._raw("SELECT COUNT(*) FROM api_runtime.write_receipts WHERE race_id LIKE ?", (token + "%",)).fetchone()[0] == 0)
    check("no_legacy_access_attempts", not any(FORBIDDEN.values()), counters=FORBIDDEN)
    check("compat_path_still_absent", not ORIGINAL_EXISTS(MISSING))
    REPORT["status"] = "passed"


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        REPORT["status"] = "failed"
        REPORT["exception_type"] = type(exc).__name__
        import traceback
        REPORT["failure_location"] = [{"file": item.filename, "line": item.lineno} for item in traceback.extract_tb(exc.__traceback__)]
        print("FAILED:", type(exc).__name__, flush=True)
    finally:
        REPORT["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT["forbidden_attempts"] = FORBIDDEN
        OUT.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if REPORT["status"] == "passed" else 1)
