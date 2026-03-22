from pathlib import Path

import pytest

from jra_srb.provider import FixtureProvider
from jra_srb.service import JraService


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def service(fixture_dir: Path) -> JraService:
    return JraService(provider=FixtureProvider(fixture_dir))
