import os
import pathlib
import sys
import tempfile

# Configure the environment BEFORE importing the application so the engine binds
# to a throwaway SQLite file and RTSP reachability checks are disabled in tests.
os.environ.setdefault("SENTINEL_API_KEY", "test-api-key-12345")
os.environ["SENTINEL_RTSP_VALIDATION"] = "off"

_DB_PATH = pathlib.Path(tempfile.gettempdir()) / "sentinel_test.db"
if _DB_PATH.exists():
    _DB_PATH.unlink()
os.environ["SENTINEL_DB_URL"] = "sqlite:///" + str(_DB_PATH)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from sentinel.models import init_db

init_db()

import pytest
from sentinel.models import SessionLocal, Camera, Event, Incident, Entity
from sentinel.pipeline import reset_counters


@pytest.fixture(autouse=True)
def _clean_db():
    reset_counters()
    db = SessionLocal()
    for model in (Event, Incident, Entity, Camera):
        db.query(model).delete()
    db.commit()
    db.close()
    yield