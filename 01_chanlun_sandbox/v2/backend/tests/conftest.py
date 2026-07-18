from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = AppConfig(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(config)) as test_client:
        yield test_client
