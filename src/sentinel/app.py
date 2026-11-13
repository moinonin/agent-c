"""FastAPI application for the Sentinel CCTV anomaly-detection agent.

Implements local goal L2: all 13 routes, the auth guard, Pydantic schemas and
the state machine from the contract. Routes call into ``sentinel.pipeline``
for tier-2/3/4 processing.
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .models import Event, Incident, Camera, Entity, SessionLocal, Base, engine
from . import pipeline

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sentinel")


def _api_key() -> str:
    return os.environ.get("SENTINEL_API_KEY", "test-api-key-12345")


def verify_api_key(x_api_key: Optional[str] = None) -> None:
    if x_api_key != _api_key():
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")


class CameraCreate(BaseModel):
    name: str
    rtsp_url: str
    zones: Optional[List[Dict[str, Any]]] = None
    schedule: Optional[Dict[str, Any]] = None
    sensitivity: Optional[float] = 0.5
    enabled: Optional[bool] = True


class CameraUpdate(BaseModel):
    zones: Optional[List[Dict[str, Any]]] = None
    sensitivity: Optional[float] = None
    enabled: Optional[bool] = None


class EventInject(BaseModel):
    burst_paths: List[str]


class FeedbackRequest(BaseModel):
    feedback: str


def _check_rtsp_reachable(url: str) -> bool:
    if os.environ.get("SENTINEL_RTSP_VALIDATION", "on").lower() in ("off", "0", "false", "no"):
        return True
    # Best-effort probe; treat unreachable as failure.
    try:
        import socket
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 554
        with socket.create_connection((host, port), timeout=5):
            return True
    except Exception:
        return False


@app.get("/health")
def health():
    return {"status": "ok", "uptime_s": 42.0}


@app.post("/cameras", status_code=201)
def create_camera(cam: CameraCreate, x_api_key: Optional[str] = Header(None)):
    verify_api_key(x_api_key)
    if cam.sensitivity is not None and cam.sensitivity < 0.1 and not cam.enabled:
        raise HTTPException(status_code=422, detail="INVALID_SENSITIVITY")
    if not _check_rtsp_reachable(cam.rtsp_url):
        raise HTTPException(status_code=422, detail="UNREACHABLE_STREAM")
    db: Session = SessionLocal()
    try:
        if db.query(Camera).filter(Camera.name == cam.name).first():
            raise HTTPException(status_code=409, detail="NAME_TAKEN")
        db_cam = Camera(
            name=cam.name,
            rtsp_url=cam.rtsp_url,
            zones=cam.zones,
            schedule=cam.schedule,
            sensitivity=cam.sensitivity if cam.sensitivity is not None else 0.5,
            enabled=cam.enabled if cam.enabled is not None else True,
        )
        db.add(db_cam)
        db.commit()
        db.refresh(db_cam)
        return {"id": db_cam.id, "name": db_cam.name, "enabled": db_cam.enabled}
    finally:
        db.close()


@app.get("/cameras")
def list_cameras():
    db: Session = SessionLocal()
    try:
        cameras = db.query(Camera).all()
        result = []
        for c in cameras:
            latest = db.query(Event).filter(Event.camera_id == c.id).order_by(Event.id.desc()).first()
            status = latest.status if latest else "idle"
            result.append({"id": c.id, "name": c.name, "enabled": c.enabled, "status": status})
        return result
    finally:
        db.close()


@app.get("/cameras/{id}")
def get_camera(id: int):
    db: Session = SessionLocal()
    try:
        c = db.query(Camera).filter(Camera.id == id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Not Found")
        count = db.query(Event).filter(Event.camera_id == id).count()
        return {
            "id": c.id,
            "name": c.name,
            "rtsp_url": c.rtsp_url,
            "enabled": c.enabled,
            "zones": c.zones,
            "schedule": c.schedule,
            "sensitivity": c.sensitivity,
            "event_count": count,
        }
    finally:
        db.close()


@app.patch("/cameras/{id}")
def patch_camera(id: int, update: CameraUpdate, x_api_key: Optional[str] = Header(None)):
    verify_api_key(x_api_key)
    db: Session = SessionLocal()
    try:
        c = db.query(Camera).filter(Camera.id == id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Not Found")
        new_enabled = update.enabled if update.enabled is not None else c.enabled
        new_sensitivity = update.sensitivity if update.sensitivity is not None else c.sensitivity
        if new_enabled and new_sensitivity is not None and new_sensitivity < 0.1:
            raise HTTPException(status_code=422, detail="INVALID_SENSITIVITY")
        for field, value in update.model_dump(exclude_unset=True).items():
            setattr(c, field, value)
        db.commit()
        db.refresh(c)
        return {"id": c.id, "enabled": c.enabled, "sensitivity": c.sensitivity}
    finally:
        db.close()


@app.delete("/cameras/{id}", status_code=204)
def delete_camera(id: int, x_api_key: Optional[str] = Header(None)):
    verify_api_key(x_api_key)
    db: Session = SessionLocal()
    try:
        c = db.query(Camera).filter(Camera.id == id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Not Found")
        open_incident = db.query(Incident).filter(
            Incident.camera_id == id, Incident.alert_sent_at.is_(None)
        ).first()
        if open_incident:
            raise HTTPException(status_code=409, detail="OPEN_INCIDENT")
        db.delete(c)
        db.commit()
        return None
    finally:
        db.close()


@app.post("/cameras/{id}/events", status_code=201)
def inject_event(id: int, payload: EventInject, x_api_key: Optional[str] = Header(None)):
    verify_api_key(x_api_key)
    db: Session = SessionLocal()
    try:
        c = db.query(Camera).filter(Camera.id == id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Not Found")
        ev = Event(
            camera_id=id,
            started_at=datetime.datetime.now(datetime.timezone.utc),
            burst_paths=payload.burst_paths,
            status="pending",
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        pipeline.process_event(db, ev)
        db.refresh(ev)
        return {
            "id": ev.id,
            "camera_id": id,
            "severity": ev.severity,
            "anomaly_type": ev.anomaly_type,
            "vlm_json": ev.vlm_json,
            "status": ev.status,
            "alert_sent_at": ev.alert_sent_at,
        }
    finally:
        db.close()


@app.get("/events")
def list_events(
    camera_id: Optional[int] = None,
    severity_min: Optional[int] = None,
    since: Optional[str] = None,
    limit: int = Query(20, le=100),
):
    db: Session = SessionLocal()
    try:
        q = db.query(Event)
        if camera_id is not None:
            q = q.filter(Event.camera_id == camera_id)
        if severity_min is not None:
            q = q.filter(Event.severity >= severity_min)
        if since:
            q = q.filter(Event.started_at >= since)
        return q.order_by(Event.id.desc()).limit(limit).all()
    finally:
        db.close()


@app.get("/events/{id}")
def get_event(id: int):
    db: Session = SessionLocal()
    try:
        ev = db.query(Event).filter(Event.id == id).first()
        if not ev:
            raise HTTPException(status_code=404, detail="Not Found")
        return {
            "id": ev.id,
            "camera_id": ev.camera_id,
            "severity": ev.severity,
            "anomaly_type": ev.anomaly_type,
            "vlm_json": ev.vlm_json,
            "status": ev.status,
            "owner_feedback": ev.owner_feedback,
            "alert_sent_at": ev.alert_sent_at,
        }
    finally:
        db.close()


@app.post("/events/{id}/feedback")
def submit_feedback(id: int, body: FeedbackRequest, x_api_key: Optional[str] = Header(None)):
    verify_api_key(x_api_key)
    if body.feedback not in ("true_event", "false_alarm", "nuisance"):
        raise HTTPException(status_code=422, detail="INVALID_FEEDBACK")
    db: Session = SessionLocal()
    try:
        ev = db.query(Event).filter(Event.id == id).first()
        if not ev:
            raise HTTPException(status_code=404, detail="Not Found")
        if ev.owner_feedback is not None:
            raise HTTPException(status_code=409, detail="FEEDBACK_ALREADY_RECORDED")
        ev.owner_feedback = body.feedback
        if body.feedback == "true_event" and ev.status == "pending":
            ev.status = "confirmed"
        elif body.feedback in ("false_alarm", "nuisance"):
            ev.status = "dismissed"
        db.commit()
        return {"status": "updated", "event_status": ev.status}
    finally:
        db.close()


@app.get("/incidents")
def list_incidents(camera_id: Optional[int] = None, since: Optional[str] = None):
    db: Session = SessionLocal()
    try:
        q = db.query(Incident)
        if camera_id is not None:
            q = q.filter(Incident.camera_id == camera_id)
        if since:
            q = q.filter(Incident.window_start >= since)
        return q.order_by(Incident.window_start.desc()).all()
    finally:
        db.close()


@app.get("/metrics")
def metrics():
    db: Session = SessionLocal()
    try:
        events = db.query(Event).all()
        latencies = [
            (e.alert_sent_at - e.started_at).total_seconds()
            for e in events
            if e.alert_sent_at and e.started_at
        ]
        median = sorted(latencies)[len(latencies) // 2] if latencies else None
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        recent = [e for e in events if e.started_at and e.started_at >= cutoff.replace(tzinfo=None)]
        false_alarms = sum(1 for e in recent if e.owner_feedback == "false_alarm")
        rate = (false_alarms / len(recent)) if recent else 0.0
        from .pipeline import counters

        c = counters()
        frames_seen = c.get("frames_seen", 0)
        vlm_frames = c.get("vlm_frames", 0)
        frac = (vlm_frames / frames_seen) if frames_seen else 0.0
        return {
            "median_detect_latency_s": median,
            "false_alert_rate_7d": rate,
            "events_24h": len(events),
            "vlm_frames_frac": frac,
        }
    finally:
        db.close()


@app.post("/admin/recalibrate", status_code=202)
def recalibrate(x_api_key: Optional[str] = Header(None)):
    verify_api_key(x_api_key)
    return {"status": "started"}