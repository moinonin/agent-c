import os

from fastapi.testclient import TestClient

from sentinel.app import app

API_KEY = os.environ["SENTINEL_API_KEY"]
client = TestClient(app)


def _authed(method, path, **kw):
    headers = kw.pop("headers", {})
    headers["X-API-Key"] = API_KEY
    return getattr(client, method)(path, headers=headers, **kw)


def test_health_open():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_camera_requires_api_key():
    r = client.post("/cameras", json={"name": "x", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    assert r.status_code == 401


def test_create_and_get_camera():
    r = _authed("post", "/cameras", json={"name": "front-door", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["enabled"] is True
    g = client.get(f"/cameras/{cid}")
    assert g.status_code == 200
    assert g.json()["event_count"] == 0


def test_get_missing_camera_404():
    assert client.get("/cameras/9999").status_code == 404


def test_list_cameras():
    _authed("post", "/cameras", json={"name": "c1", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    r = client.get("/cameras")
    assert r.status_code == 200
    assert len(r) if False else len(r.json()) >= 1


def test_patch_requires_api_key():
    r = _authed("post", "/cameras", json={"name": "c2", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    assert client.patch(f"/cameras/{cid}", json={"sensitivity": 0.3}).status_code == 401


def test_patch_invalid_sensitivity():
    r = _authed("post", "/cameras", json={"name": "c3", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    res = _authed("patch", f"/cameras/{cid}", json={"enabled": True, "sensitivity": 0.05})
    assert res.status_code == 422


def test_delete_camera_404():
    assert _authed("delete", "/cameras/9999").status_code == 404


def test_event_injection_triggers_pipeline():
    r = _authed("post", "/cameras", json={"name": "cam", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    ev = _authed("post", f"/cameras/{cid}/events", json={"burst_paths": ["f0.jpg", "f1.jpg", "f2.jpg"]})
    assert ev.status_code == 201
    body = ev.json()
    assert body["severity"] >= 1
    assert body["vlm_json"] is not None
    assert set(body["vlm_json"].keys()) >= {"summary", "severity", "anomaly_type"}


def test_event_injection_404_camera():
    assert _authed("post", "/cameras/9999/events", json={"burst_paths": ["f.jpg"]}).status_code == 404


def test_event_injection_requires_api_key():
    r = _authed("post", "/cameras", json={"name": "cam2", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    assert client.post(f"/cameras/{cid}/events", json={"burst_paths": ["f.jpg"]}).status_code == 401


def test_get_event_and_list():
    r = _authed("post", "/cameras", json={"name": "cam3", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    ev = _authed("post", f"/cameras/{cid}/events", json={"burst_paths": ["f.jpg"]})
    eid = ev.json()["id"]
    assert client.get(f"/events/{eid}").status_code == 200
    assert client.get("/events").json().__class__ is list
    sev = client.get(f"/events?severity_min=2").json()
    assert all(e["severity"] >= 2 for e in sev)


def test_feedback_once():
    r = _authed("post", "/cameras", json={"name": "cam4", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    ev = _authed("post", f"/cameras/{cid}/events", json={"burst_paths": ["f.jpg"]})
    eid = ev.json()["id"]
    fb = _authed("post", f"/events/{eid}/feedback", json={"feedback": "false_alarm"})
    assert fb.status_code == 200
    assert client.get(f"/events/{eid}").json()["owner_feedback"] == "false_alarm"
    dup = _authed("post", f"/events/{eid}/feedback", json={"feedback": "true_event"})
    assert dup.status_code == 409


def test_feedback_invalid_enum():
    r = _authed("post", "/cameras", json={"name": "cam5", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    ev = _authed("post", f"/cameras/{cid}/events", json={"burst_paths": ["f.jpg"]})
    eid = ev.json()["id"]
    assert _authed("post", f"/events/{eid}/feedback", json={"feedback": "nope"}).status_code == 422


def test_feedback_requires_api_key():
    r = _authed("post", "/cameras", json={"name": "cam6", "rtsp_url": "rtsp://127.0.0.1:8554/test"})
    cid = r.json()["id"]
    ev = _authed("post", f"/cameras/{cid}/events", json={"burst_paths": ["f.jpg"]})
    eid = ev.json()["id"]
    assert client.post(f"/events/{eid}/feedback", json={"feedback": "true_event"}).status_code == 401


def test_metrics_keys():
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    for k in ("median_detect_latency_s", "false_alert_rate_7d", "events_24h", "vlm_frames_frac"):
        assert k in body
    assert body["vlm_frames_frac"] <= 1.0


def test_incidents_list():
    r = client.get("/incidents")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_recalibrate_requires_api_key():
    assert client.post("/admin/recalibrate").status_code == 401


def test_recalibrate_ok():
    assert _authed("post", "/admin/recalibrate").status_code == 202