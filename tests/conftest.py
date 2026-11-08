from pathlib import Path
import os

# 通常の契約テストはローカル運用設定ファイルから独立させる。
# SQL実接続はtest_sqlserver_integrationの明示設定で選択する。
os.environ.setdefault("JRA_SRB_STORAGE_BACKEND", "sqlite")

import pytest

from jra_srb.provider import FixtureProvider
from jra_srb.service import JraService


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def service(fixture_dir: Path) -> JraService:
    return JraService(provider=FixtureProvider(fixture_dir))
