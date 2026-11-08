"""概要: API・CLI・履歴特徴量の永続化経路を明示backendへ統一する。
作成日: 2026-10-15
入力: backend環境設定、旧SQLiteパスまたはSQL Server設定。
出力: 単一backendのStore・cache・job・結果保存。
実行例: uv run jra-srb verify-analysis-joins --help
注意事項: SQL選択時は旧SQLiteへ接続しない。明示JSONL exportの意味を維持する。
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

from .analysis_store import AnalysisSQLiteStore
from .cache import SQLiteTTLCache, TTLCache
from .storage_config import SqlServerSettings, storage_backend


def build_analysis_store(path: str | Path = "data/db/analysis.sqlite") -> AnalysisSQLiteStore:
    """API/CLIで選択した唯一の業務Storeを返す。"""
    if storage_backend() == "sqlserver":
        from .sqlserver_store import SqlServerAnalysisStore
        return SqlServerAnalysisStore(SqlServerSettings.from_env())
    return AnalysisSQLiteStore(path)


def open_analysis_read(path: str | Path):
    """履歴特徴量の読取りも選択backendへ接続し、SQLiteはread-onlyで開く。"""
    if storage_backend() == "sqlserver":
        return build_analysis_store()._connect(read_only=True)
    resolved = Path(path).resolve()
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def build_cache(path: str | Path | None = None):
    """TTLとstale動作を保つcacheを返す。SQL選択時はSQL cacheへ統一する。"""
    if storage_backend() == "sqlserver":
        from .sqlserver_auxiliary import SqlServerTTLCache
        return SqlServerTTLCache(SqlServerSettings.from_env())
    return SQLiteTTLCache(path) if path else TTLCache()


def build_job_registry(path: str | Path | None = None):
    """jobの保存・復旧に使う永続backendを返す。"""
    if storage_backend() == "sqlserver":
        from .sqlserver_auxiliary import SqlServerJobRegistry
        return SqlServerJobRegistry(SqlServerSettings.from_env())
    from .jobs import ResultCollectionJobRegistry
    return ResultCollectionJobRegistry(path)


def build_result_storage(kind: str, output: str | Path):
    """明示JSONLはexportし、SQL運用のDB結果保存は名前空間付きSQLへ送る。"""
    from .batch import JsonlRaceResultStorage, SQLiteRaceResultStorage
    if kind == "jsonl":
        return JsonlRaceResultStorage(Path(output))
    if kind == "sqlserver":
        from .sqlserver_auxiliary import SqlServerRaceResultStorage
        return SqlServerRaceResultStorage(SqlServerSettings.from_env(), str(Path(output).resolve()))
    if kind == "sqlite":
        return SQLiteRaceResultStorage(Path(output))
    raise ValueError(f"unsupported results storage={kind}")
