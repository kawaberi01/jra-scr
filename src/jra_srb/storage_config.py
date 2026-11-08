"""概要: API・CLI共通の永続化backendとSQL Server接続設定を読み込む。
作成日: 2026-10-15
入力: JRA_SRB_STORAGE_BACKEND、JRA_SRB_SQLSERVER_*環境変数。
出力: 秘密を表示しない設定オブジェクト。
実行例: uv run jra-srb --help
注意事項: 接続文字列をSQLiteパスとして扱わない。SQL選択時にSQLiteへfallbackしない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping


def storage_environment() -> dict[str, str]:
    """ローカル設定ファイルを読み、明示環境変数を優先した設定を返す。

    Notes:
        設定ファイルの値をプロセス環境へ書き戻さない。ファイルの未配置時は
        従来設定を使う。明示したファイルが存在しない場合は例外を伝える。
    """
    explicit = os.environ.get("JRA_SRB_STORAGE_ENV_FILE")
    path = Path(explicit or "data/storage/runtime.env")
    values = {}
    if explicit or path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.strip().partition("=")
            if separator and (name == "JRA_SRB_STORAGE_BACKEND" or name.startswith("JRA_SRB_SQLSERVER_") or name == "JRA_SRB_RESULTS_STORAGE"):
                values[name] = value.strip().strip('"').strip("'")
    return {**values, **os.environ}


def storage_backend(environ: Mapping[str, str] | None = None) -> str:
    """明示backendを返し、未対応の設定値は接続前に拒否する。"""
    env = storage_environment() if environ is None else environ
    backend = env.get("JRA_SRB_STORAGE_BACKEND", "sqlite").strip().lower()
    if backend not in {"sqlite", "sqlserver"}:
        raise ValueError("JRA_SRB_STORAGE_BACKEND must be sqlite or sqlserver")
    return backend


@dataclass(frozen=True)
class SqlServerSettings:
    """reader/writerを分離し、秘密がreprへ出ないSQL接続設定を保持する。"""

    reader_connection_string: str = field(repr=False)
    writer_connection_string: str = field(repr=False)
    database: str
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SqlServerSettings:
        """環境変数から設定を読み、接続先DB名とtimeoutの明示を検査する。

        Raises:
            ValueError: 必須設定がない、または設定値が不正な場合。
        """
        env = storage_environment() if environ is None else environ
        names = ("JRA_SRB_SQLSERVER_READER_CONNECTION_STRING", "JRA_SRB_SQLSERVER_WRITER_CONNECTION_STRING")
        values = [env.get(name, "").strip() for name in names]
        for name, value in zip(names, values, strict=True):
            if not value:
                raise ValueError(f"{name} is required for sqlserver backend")
        database = env.get("JRA_SRB_SQLSERVER_DATABASE", "").strip()
        if not database:
            raise ValueError("JRA_SRB_SQLSERVER_DATABASE is required")
        timeout = int(env.get("JRA_SRB_SQLSERVER_TIMEOUT_SECONDS", "30"))
        if timeout < 1:
            raise ValueError("JRA_SRB_SQLSERVER_TIMEOUT_SECONDS must be positive")
        return cls(values[0], values[1], database, timeout)
