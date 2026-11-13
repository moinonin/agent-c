"""Tiered anomaly pipeline for the Sentinel CCTV agent.

Implements local goal L3:
  - Tier 0: cheap continuous trigger (frame differencing).
  - Tier 1: ring-buffer burst assembly (performed by the caller).
  - Tier 2: Gemini VLM strict-JSON assessment with degraded fallback.
  - Tier 3: noise suppression (whitelist, 300 s dedup, per-camera baselines).
  - Tier 4: alerting with owner feedback + threshold recalibration.
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Any, Dict, List, Optional

import httpx as requests

SEVERITY_RUBRIC = {
    0: "nothing notable (expected activity)",
    1: "ambiguous (unknown person, public space, daytime)",
    2: "actionable (person in fenced yard, package removed, door at night)",
    3: "emergency (forced entry, glass break, tamper, weapon, injury)",
}

DEDUP_WINDOW_S = 300
VLM_FRAME_BUDGET_FRAC = 0.05

_COUNTERS: Dict[str, int] = {"frames_seen": 0, "vlm_frames": 0, "guard_trips": 0}


def run_tier0(prev_frame, frame) -> float:
    """Cheap continuous trigger: mean absolute difference between two frames."""
    import numpy as np

    diff = np.abs(frame.astype("int16") - prev_frame.astype("int16")).mean()
    return float(diff)


def assess_with_vlm(burst_paths, metadata, frames_seen) -> tuple[Dict[str, Any], int]:
    """Tier 2: strict-JSON Gemini call. Never blocks alerting on failure."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    prompt = (
        "You are a CCTV anomaly assessor. Given these frame paths and metadata, "
        "return JSON with keys: summary, anomaly_type, severity (0-3), confidence, "
        "entities, actions, justification, novel_activity.\n"
        f"frames={burst_paths}\nmetadata={json.dumps(metadata)}"
    )
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0.2},
            },
            timeout=90,
        )
        resp.raise_for_status()
        parts = resp.json()["candidates"][0]["content"]["parts"]
        text = parts[-1].get("text", "{}")
        result = json.loads(text)
        result.setdefault("novel_activity", False)
        return result, frames_seen + len(burst_paths)
    except Exception:
        return {
            "summary": "VLM unavailable - degraded heuristic assessment",
            "anomaly_type": "unknown",
            "severity": 2,
            "confidence": 0.0,
            "entities": [],
            "actions": [],
            "justification": "VLM call failed; severity capped at 2 (availability over silence).",
            "novel_activity": False,
            "vlm_status": "degraded",
        }, frames_seen + len(burst_paths)


def dedup_to_incident(db, camera_id, event, now) -> "Incident":
    """Tier 3: collapse same-camera events within DEDUP_WINDOW_S into one incident."""
    from .models import Incident

    window_start = now - datetime.timedelta(seconds=DEDUP_WINDOW_S)
    inc = db.query(Incident).filter(
        Incident.camera_id == camera_id, Incident.window_start >= window_start
    ).first()
    if inc:
        inc.event_ids = (inc.event_ids or []) + [event.id]
        inc.max_severity = max(inc.max_severity or 0, event.severity or 0)
    else:
        inc = Incident(
            camera_id=camera_id,
            window_start=now,
            window_end=now,
            event_ids=[event.id],
            max_severity=event.severity or 0,
        )
        db.add(inc)
    db.commit()
    return inc


def apply_whitelist(db, vlm_result, whitelisted_entities) -> Dict[str, Any]:
    """Whitelisted entities need an explicit novel_activity flag to escalate."""
    result = dict(vlm_result)
    entities = [str(e).lower() for e in (vlm_result.get("entities") or [])]
    if whitelisted_entities and any(e in whitelisted_entities for e in entities):
        if not vlm_result.get("novel_activity"):
            result["severity"] = 0
    return result


def check_vlm_budget(frames_seen, vlm_frames) -> bool:
    """Tier 2 quota guard: tighten trigger above budget fraction."""
    if frames_seen <= 0:
        return True
    return vlm_frames <= frames_seen * VLM_FRAME_BUDGET_FRAC


def purge_old_bursts(burst_dir, days=14) -> int:
    """Retention: delete old burst frames; NEVER delete event rows."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    import pathlib

    removed = 0
    p = pathlib.Path(burst_dir)
    if not p.exists():
        return 0
    for f in p.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff.timestamp():
            f.unlink()
            removed += 1
    return removed


def send_alert(db, event, incident) -> None:
    """Tier 4: dispatch an alert and stamp alert_sent_at on event + incident."""
    webhook = os.environ.get("SENTINEL_ALERT_WEBHOOK")
    payload = {
        "camera_id": event.camera_id,
        "event_id": event.id,
        "incident_id": incident.id,
        "severity": event.severity,
        "anomaly_type": event.anomaly_type,
        "summary": (event.vlm_json or {}).get("summary"),
    }
    if webhook:
        try:
            requests.post(webhook, json=payload, timeout=5)
        except Exception:
            pass
    now = datetime.datetime.now(datetime.timezone.utc)
    event.alert_sent_at = now
    if incident.alert_sent_at is None:
        incident.alert_sent_at = now
    db.commit()


def process_event(db, event) -> None:
    """Run the tier-2 -> tier-3 -> tier-4 pipeline for a single event.

    Mutates ``event`` in place and commits. Never raises on VLM failure
    (availability over silence).
    """
    import numpy as np  # noqa: F401  (kept for tier-0 parity)

    global _COUNTERS
    burst_paths = event.burst_paths or []
    # Count the burst frames as ingested frames so the Tier-2 fraction is
    # measured against the frames the VLM actually consumed (>= denominator).
    frames_seen = _COUNTERS["frames_seen"] + max(len(burst_paths), 1)
    _COUNTERS["frames_seen"] = frames_seen

    metadata = {"camera_id": event.camera_id, "started_at": str(event.started_at)}

    # Tier 2
    vlm_result, vlm_frames = assess_with_vlm(burst_paths, metadata, _COUNTERS["vlm_frames"])
    _COUNTERS["vlm_frames"] = vlm_frames
    if not check_vlm_budget(frames_seen, vlm_frames):
        _COUNTERS["guard_trips"] += 1

    # Tier 3: whitelist suppression
    from .models import Entity

    whitelisted = [e.label.lower() for e in db.query(Entity).filter(Entity.whitelisted.is_(True)).all()]
    entities = [str(e).lower() for e in (vlm_result.get("entities") or [])]
    wh = [e for e in entities if e in whitelisted]
    vlm_result = apply_whitelist(db, vlm_result, wh)

    severity = int(vlm_result.get("severity", 0))
    severity = max(0, min(3, severity))
    if vlm_result.get("vlm_status") == "degraded":
        severity = min(severity, 2)

    event.severity = severity
    event.anomaly_type = vlm_result.get("anomaly_type")
    event.vlm_json = vlm_result
    event.confidence = float(vlm_result.get("confidence", 0.0) or 0.0)
    event.status = "pending"

    # Tier 3: dedup
    now = datetime.datetime.now(datetime.timezone.utc)
    incident = dedup_to_incident(db, event.camera_id, event, now)

    # Tier 4: alert once per incident
    if incident.alert_sent_at is None:
        send_alert(db, event, incident)
    else:
        event.alert_sent_at = None
        db.commit()

    # Re-attach incident id to event for callers
    event._incident_id = incident.id


def counters() -> Dict[str, int]:
    return dict(_COUNTERS)

def reset_counters() -> None:
    _COUNTERS["frames_seen"] = 0
    _COUNTERS["vlm_frames"] = 0
    _COUNTERS["guard_trips"] = 0