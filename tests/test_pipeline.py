import datetime
import os
import pathlib
import tempfile

import numpy as np
import httpx as requests

from sentinel import pipeline
from sentinel.models import SessionLocal, Event, Incident, Entity, Camera


def test_run_tier0_detects_change():
    a = np.zeros((4, 4), dtype="uint8")
    b = a.copy()
    b[1, 1] = 255
    assert pipeline.run_tier0(a, b) > 0
    assert pipeline.run_tier0(a, a.copy()) == 0.0


def test_dedup_window_collapses_events():
    db = SessionLocal()
    c = Camera(name="cam", rtsp_url="rtsp://x", enabled=True)
    db.add(c)
    db.commit()
    db.refresh(c)
    now = datetime.datetime.now(datetime.timezone.utc)
    e1 = Event(camera_id=c.id, started_at=now, severity=2, status="pending")
    e2 = Event(camera_id=c.id, started_at=now, severity=1, status="pending")
    db.add_all([e1, e2])
    db.commit()
    db.refresh(e1)
    db.refresh(e2)
    inc1 = pipeline.dedup_to_incident(db, c.id, e1, now)
    inc2 = pipeline.dedup_to_incident(db, c.id, e2, now)
    assert inc1.id == inc2.id
    assert inc1.max_severity == 2
    assert e1.id in inc1.event_ids and e2.id in inc1.event_ids


def test_whitelist_suppression():
    vlm = {"severity": 3, "entities": ["mail_carrier"], "novel_activity": False}
    out = pipeline.apply_whitelist(None, vlm, ["mail_carrier"])
    assert out["severity"] == 0
    vlm2 = {"severity": 3, "entities": ["mail_carrier"], "novel_activity": True}
    out2 = pipeline.apply_whitelist(None, vlm2, ["mail_carrier"])
    assert out2["severity"] == 3
    # unknown entity escalates normally
    vlm3 = {"severity": 2, "entities": ["stranger"], "novel_activity": False}
    out3 = pipeline.apply_whitelist(None, vlm3, ["mail_carrier"])
    assert out3["severity"] == 2


def test_degraded_fallback_on_vlm_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(requests, "post", boom)
    os.environ.pop("GEMINI_API_KEY", None)
    result, frames = pipeline.assess_with_vlm(["f.jpg"], {"camera_id": 1}, 0)
    assert result["vlm_status"] == "degraded"
    assert result["severity"] == 2
    assert frames == 1


def test_retention_purges_old_bursts_only(tmp_path):
    old = tmp_path / "old.jpg"
    new = tmp_path / "new.jpg"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    import time
    old_mtime = old.stat().st_mtime - (15 * 86400)
    os.utime(old, (old_mtime, old_mtime))
    removed = pipeline.purge_old_bursts(str(tmp_path), days=14)
    assert removed == 1
    assert not old.exists()
    assert new.exists()


def test_vlm_budget_guard():
    assert pipeline.check_vlm_budget(100, 4) is True
    assert pipeline.check_vlm_budget(100, 10) is False
    assert pipeline.check_vlm_budget(0, 0) is True


def test_severity_rubric_keys():
    assert set(pipeline.SEVERITY_RUBRIC.keys()) == {0, 1, 2, 3}
    assert pipeline.DEDUP_WINDOW_S == 300