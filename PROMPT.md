# FEATURE PROMPT — Sentinal: Real-Time CCTV Anomaly-Detection & Alerting Agent

## Problem statement

A homeowner owns 4 IP cameras (RTSP/ONVIF). When "unusual activity" occurs
(intruder, package theft, loitering, tampering), the owner learns about it only
by manually scrubbing hours of recorded video — always too late to react. Build
a self-hosted agent that watches the camera streams continuously, detects
unusual activity within seconds, enriches the event with a multimodal
understanding of what happened, and pushes a pushable, actable alert to the
owner while the event is still in progress.

## Architectural principle (non-negotiable)

Do NOT sample frames on a timer. Continuous tiered pipeline:
- Tier 0 (always on, cheap, local): frame differencing + a tiny person/vehicle
  detector running at 10-20 fps; emits raw events with timestamps.
- Tier 1: rolling pre-event ring buffer (default 20 s before, 5 s after at 1 fps)
  assembles a temporally ordered frame burst plus structured metadata.
- Tier 2 (expensive, rare): the VLM planner call (Gemini, provider `gemini`)
  receives the burst + metadata and returns strict JSON: summary, anomaly_type,
  severity 0-3, confidence, entities, actions, one-line justification.
- Tier 3: noise suppression — known-person/known-vehicle whitelist, learned
  per-camera per-hour baseline, dedup + 5-minute incident aggregation.
- Tier 4: alerting with owner feedback that recalibrates thresholds.
Only ~0.1% of frames may reach Tier 2. Detect-to-phone latency budget: <= 10 s.

## Stack (fixed)

- Python 3.11+, FastAPI, uvicorn, SQLAlchemy 2 + SQLite (WAL mode).
- Tier 0: OpenCV (background subtraction / absdiff) + numpy. No GPU required.
- Tier 2: Google Gemini via provider `gemini` (model per project config),
  `response_mime_type=application/json` with a strict response schema.
- Background work: `asyncio` + per-camera reader tasks + a worker queue.
- Tests: pytest. Packaging: pyproject.toml (src layout, package name `sentinel`).

## Data model (required tables)

- `cameras` (id, name, rtsp_url, enabled, zones JSON, schedule JSON,
  sensitivity FLOAT, created_at)
- `events` (id, camera_id FK, started_at, ended_at, tier0_signal JSON,
  burst_paths JSON, severity INT, anomaly_type, vlm_json JSON, confidence
  FLOAT, status ENUM[pending, confirmed, dismissed, escalated],
  alert_sent_at, owner_feedback ENUM[null, true_event, false_alarm, nuisance])
- `incidents` (id, camera_id FK, window_start, window_end, event_ids JSON,
  max_severity INT, alert_sent_at)
- `entities` (id, kind ENUM[person, vehicle, package, animal, unknown],
  label, face_embedding_placeholder, whitelisted BOOL)

## HTTP API surface (every route must be declared in the spec `endpoints`)

1.  `GET  /health`                -> 200 `{status:"ok", uptime_s}` — no auth.
2.  `POST /cameras`               -> 201, body {name, rtsp_url, zones?, schedule?}; validates RTSP URL reachable via ffprobe/OpenCV with 5s timeout; 422 on unreachable stream.
3.  `GET  /cameras`               -> 200 list, each with `enabled` and latest `status`.
4.  `GET  /cameras/{id}`          -> 200 camera + recent event count; 404 if missing.
5.  `PATCH /cameras/{id}`         -> 200 updated camera (zones/sensitivity/enabled).
6.  `DELETE /cameras/{id}`        -> 204; 404 if missing.
7.  `POST /cameras/{id}/events`   -> 201 manual event injection (client posts burst frame paths) — the tier-1/tier-2 pathway, used by tests and by the ingestion loop.
8.  `GET  /events?camera_id&severity_min&since` -> 200 paginated (default 20/page, max 100), newest first.
9.  `GET  /events/{id}`           -> 200 event incl. burst_paths + vlm_json; 404 if missing.
10. `POST /events/{id}/feedback`  -> 200 {status: updated}, body {feedback: true_event|false_alarm|nuisance}; 404 if missing; 422 on invalid enum.
11. `GET  /incidents?camera_id&since` -> 200 list of aggregated incidents.
12. `GET  /metrics`               -> 200 {median_detect_latency_s, false_alert_rate_7d, events_24h, vlm_frames_frac} — all four keys required.
13. `POST /admin/recalibrate`     -> 202 {status:"started"} — recomputes per-camera per-hour baselines from stored events.

## State machine (explicit transition guards — M2 closure)

- Event status transitions (all others MUST be rejected with 422 `INVALID_TRANSITION`):
  `pending` -> `confirmed` (owner feedback true_event),
  `pending`|`confirmed` -> `dismissed` (owner feedback false_alarm or nuisance),
  `confirmed` -> `escalated` (owner clicks emergency action, one-way, never reversible).
- A `dismissed` event NEVER fires an alert, even after recalibration.
- Camera `enabled` may be PATCHed false at any time; re-enabling requires a
  positive sensitivity value (>= 0.1) — a disabled camera with sensitivity <= 0
  is rejected 422.
- DELETE /cameras/{id} is allowed only from `enabled=true|false` states and
  cancels its reader task first; 409 if an incident for that camera is open.
- Feedback may be written at most once per event; a second write returns 409
  `FEEDBACK_ALREADY_RECORDED` (audit trail is append-only).

## Business rules (must be enforced, not aspirational)

- Severity rubric (hard-coded, documented in code): 0 = nothing notable
  (expected: mail carrier, known person); 1 = ambiguous (unknown person on
  public sidewalk during day); 2 = actionable (person in fenced yard, package
  removed from porch, door opened at night); 3 = emergency (forced entry, glass
  break, tamper, weapon visible, injury).
- Tier 3 dedup: events for the same camera within 300 s collapse into one
  incident; alert once per incident, not per event.
- Whitelist: entity with whitelisted=true can produce severity >= 1 only via
  explicit VLM `novel_activity=true` flag.
- Owner feedback false_alarm increments the camera's suppression counter; after
  3 false alarms in 24 h the camera's sensitivity auto-drops one step and the
  change is logged (never silently — audit row).
- Retention: bursts older than 14 days purged by a nightly job; event rows
  retained. NEVER delete event rows.
- Tier 2 quota guard: if VLM frames processed exceed 5% of ingested frames in
  any 1-hour window, the trigger threshold tightens and `/metrics` records the
  guard trip. VLM failures fall back to severity capped at 2 with
  `vlm_status: "degraded"` and an alert is still sent (availability over
  silence).
- All mutating endpoints require `X-API-Key` header matching `SENTINEL_API_KEY`
  env var; return 401 missing/mismatched key. `/health` and `/metrics` are
  read-only and exempt.

## Local verification goals (executable, command-shaped)

- L1: `curl -s http://127.0.0.1:8000/health` -> 200 and body contains `"status":"ok"`.
- L2: `curl -s -X POST -H 'X-API-Key: $SENTINEL_API_KEY' -H 'Content-Type: application/json' -d '{"name":"front-door","rtsp_url":"rtsp://127.0.0.1:8554/test"}' http://127.0.0.1:8000/cameras` -> 201 with `id` present.
- L3: Same POST without the `X-API-Key` header -> 401 `UNAUTHORIZED`.
- L4: `POST /cameras/front-door-id/events` with 3 synthetic burst paths -> 201 event with severity >= 1 and non-null `vlm_json` containing keys `summary`, `severity`, `anomaly_type`.
- L5: `POST /events/{id}/feedback` with `{"feedback":"false_alarm"}` -> 200 then `GET /events/{id}` shows `owner_feedback == "false_alarm"`.
- L6: `GET /events?severity_min=2&since=<iso>` returns only rows with severity >= 2 and honors `limit=20` default.
- L7: `GET /metrics` -> 200 with all four required keys present and
  `vlm_frames_frac <= 1.0`.
- L8: `pytest tests/test_pipeline.py -q` -> all pass, covering: severity rubric
  boundary cases, dedup/aggregation window, whitelist suppression, degraded-VLM
  fallback, retention purge of bursts (not events), and auth guard on every
  mutating route.

## Global verification

- `pytest tests/ -q` (full suite, no generic markers) — must pass.
- `python -c "import sentinel"` boots the FastAPI app without a running camera.
- Static: `ruff check src/` clean, `mypy src/sentinel` passes on new modules.

## Completion criteria (definition of done)

1. All 13 routes implemented and declared in the spec; auth guard verified by L3.
2. End-to-end latency measured on a synthetic event: `started_at` ->
   `alert_sent_at` median <= 10 s, recorded in `/metrics`.
3. Tier 2 frame fraction < 1% on a 60-minute synthetic soak with 1 known-nuisance
   camera (leaves/wind) — measured via `GET /metrics` `vlm_frames_frac`.
4. Feedback loop changes future alert behavior observably (L5 + a regression test).
5. False-alert rate on the 60-minute soak <= 1 per hour per camera.
6. PLAN.md runway gates all checked; no TODOs left in `src/`.