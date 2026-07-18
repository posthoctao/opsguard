import os

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AI_PROVIDER"] = "rules"
os.environ["RUNTIME_BACKEND"] = "memory"
os.environ["AUTO_PROCESS_ALERTS"] = "true"
os.environ["REPAIR_SOURCE_PROFILE"] = "demo-buffer-bug"

from app.core.config import get_settings  # noqa: E402
from app.db.session import configure_database, create_tables, drop_tables  # noqa: E402
from app.dependencies import (  # noqa: E402
    set_repair_client_override,
    set_runtime_override,
)
from app.main import app  # noqa: E402
from app.runtime.memory import InMemoryRuntime  # noqa: E402


@pytest.fixture(autouse=True)
def reset_app_state():
    get_settings.cache_clear()
    configure_database("sqlite://")
    create_tables()
    runtime = InMemoryRuntime()
    set_runtime_override(runtime)
    set_repair_client_override(None)
    yield runtime
    drop_tables()
    set_runtime_override(None)
    set_repair_client_override(None)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
