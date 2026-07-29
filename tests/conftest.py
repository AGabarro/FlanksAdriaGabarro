from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cache import summary_cache
from app.db import create_all, reset_engine
from app.ingest import ingest_file
from app.main import app

SAMPLE = Path(__file__).parent / "data" / "test_data.csv"


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    reset_engine()
    summary_cache.reset()
    create_all()
    yield
    reset_engine()


@pytest.fixture
def report(database):
    return ingest_file(SAMPLE)


@pytest.fixture
def client(report):
    return TestClient(app)
