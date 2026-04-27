import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core import database
from app.core.database import Base, configure_database, init_db
from app.main import app


@pytest.fixture()
def client():
    get_settings.cache_clear()
    configure_database("sqlite+pysqlite:///:memory:")
    init_db()
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=database.engine)


@pytest.fixture()
def auth_headers():
    return {"X-API-Key": "local-dev-ingest-key"}
