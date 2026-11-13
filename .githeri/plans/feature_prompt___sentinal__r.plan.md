# Feature

**Name**: sentinel-realtime-cctv-anomaly-detection  
**Purpose**: Real-Time CCTV Anomaly-Detection & Alerting Agent  
**Reference Specification**: Structured Format B Specification  
**Expected Deliverables**:
- SQLAlchemy ORM database models and session setup (`src/sentinel/models.py`)
- FastAPI web application and rest endpoints (`src/sentinel/app.py` / `src/sentinel/main.py`)
- Anomaly detection, severity classification, deduplication logic, and whitelist filtering components
- Test suite asserting model setup, route behavior, and business rules

**Dependencies**:
- `fastapi`
- `uvicorn`
- `sqlalchemy`
- `pytest`
- `opencv-python`
- `numpy`
- `pydantic`
- `httpx`

**Assumptions**:
- Execution target platform: Linux / POSIX compatible environment
- SQLite backend database (`sqlite:///sentinel.db`)
- Environment variable configuration: `SENTINEL_API_KEY="test-api-key-12345"`

---

# Target Environment

- **Language**: Python
- **Framework**: FastAPI
- **ORM**: SQLAlchemy
- **Test Framework**: Pytest

---

# Global Success Criteria

1. **G1**: Full test suite passes without errors: `pytest tests/ -q`.
2. **G2**: Database schema supports `Camera`, `Event`, `Incident`, and `Entity` objects with appropriate attributes and relationships.
3. **G3**: All mutating FastAPI endpoints enforce `X-API-Key` authentication against `SENTINEL_API_KEY`.
4. **G4**: Tier 3 deduplication correctly collapses events for the same camera within 300 seconds into one incident.
5. **G5**: Whitelisted entities only trigger severity >= 1 when `novel_activity=True`.

---

# Execution Stages

## Stage 1: Database Models & Session Setup (Goal L1)

### Objective
Create and configure SQLAlchemy ORM database models (`Camera`, `Event`, `Incident`, `Entity`) and session management in `src/sentinel/models.py`.

### Inputs
- Local Goal `L1` blueprint specification
- Dependencies: `sqlalchemy`, `pydantic`

### Preconditions
- Python environment initialized with `sqlalchemy` installed.
- Workspace directory structure established (`src/sentinel/`).

### Discovery Tasks
- Inspect project directory to ensure target path `src/sentinel/` exists or is created.
- Check existing `__init__.py` files to confirm package structure.

### Execution Tasks
1. Read local goal `L1` model blueprint specifications.
2. Inspect target module path `src/sentinel/models.py`.
3. Create `src/sentinel/__init__.py` package marker (empty file).
4. Create file `src/sentinel/models.py`.
4. Define SQLAlchemy declarative base (`Base`).
5. Implement `Camera` table model with attributes (`id`, `name`, `rtsp_url`, `enabled`, `zones`, `schedule`, `sensitivity`, `created_at`).
6. Implement `Event` table model with attributes (`id`, `camera_id`, `started_at`, `ended_at`, `tier0_signal`, `burst_paths`, `severity`, `anomaly_type`, `vlm_json`, `confidence`, `status`, `alert_sent_at`, `owner_feedback`).
7. Implement `Incident` table model with attributes (`id`, `camera_id`, `window_start`, `window_end`, `event_ids`, `max_severity`, `alert_sent_at`).
8. Implement `Entity` table model with attributes (`id`, `kind`, `label`, `face_embedding_placeholder`, `whitelisted`).
9. Instantiate SQLite engine (`sqlite:///sentinel.db`) and `SessionLocal` maker.
10. Run verification test to confirm file content and model instantiation.

### Suggested Commands
```bash
# Verify directory structure
python -c "import pathlib; [pathlib.Path(p).mkdir(parents=True, exist_ok=True) for p in ('src/sentinel', 'tests')]"

# Create package marker and models file
python -c "import pathlib; [pathlib.Path(p).touch() for p in ('src/sentinel/__init__.py', 'src/sentinel/models.py')]"

# Check content existence
python -c "src = open('src/sentinel/models.py').read(); assert 'class Camera' in src; print('PASS')"
```

### Expected Outputs
- `src/sentinel/__init__.py`
- `src/sentinel/models.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L1    | `test -f src/sentinel/models.py && grep -q "class Camera" src/sentinel/models.py && echo PASS` | PASS |
| L1    | `python3 -c "from src.sentinel.models import Camera, Event, Incident, Entity; print('OK')"` | OK |

### Failure Procedure
If verification fails:
1. Stop execution immediately.
2. Inspect `src/sentinel/models.py` for import errors or syntax issues.
3. Verify SQLAlchemy package is installed in the active environment.
4. Correct syntax or missing table fields as required by the blueprint.
5. Re-run local verification commands.

### Completion Condition
`src/sentinel/models.py` exists, contains all specified models, and can be imported cleanly into Python without errors.

---

## Stage 2: FastAPI Application & Endpoint Skeleton Implementation (Goal L2)

### Objective
Implement the FastAPI web application, authentication middleware/dependency, Pydantic schemas, and routing handlers in `src/sentinel/app.py`.

### Inputs
- Local Goal `L2` blueprint specification
- `src/sentinel/models.py`
- Business Rule: `Auth Guard` (`X-API-Key` header matching `SENTINEL_API_KEY`)

### Preconditions
- Stage 1 completed successfully (`src/sentinel/models.py` imported and verified).

### Discovery Tasks
- Inspect `src/sentinel/models.py` to confirm model exports match target imports in `app.py`.
- Verify FastAPI and Pydantic dependencies are available.

### Execution Tasks
1. Read endpoint specifications and blueprint for local goal `L2`.
2. Inspect target file path `src/sentinel/app.py`.
3. Create `src/sentinel/app.py`.
4. Import required FastAPI, Pydantic, and SQLAlchemy utilities alongside `src.sentinel.models`.
5. Implement authentication guard `verify_api_key` checking header `X-API-Key` against `SENTINEL_API_KEY`.
6. Define request/response Pydantic models (`CameraCreate`, `CameraUpdate`, `EventInject`, `FeedbackRequest`).
7. Implement health check endpoint `GET /health`.
8. Implement camera management endpoints (`POST /cameras`, `GET /cameras`, `GET /cameras/{id}`, `PATCH /cameras/{id}`).
9. Implement event, incident, and entity endpoints.
10. Ensure database tables are created via `Base.metadata.create_all(bind=engine)` upon application initialization.

### Suggested Commands
```bash
# Verify app module creation
python -c "import pathlib; pathlib.Path('src/sentinel/app.py').touch()"

# Check syntax and imports
python3 -c "from src.sentinel.app import app; print(app.title)"
```

### Expected Outputs
- `src/sentinel/app.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L2    | `test -f src/sentinel/app.py && grep -q "app = FastAPI" src/sentinel/app.py && echo PASS` | PASS |
| L2    | `python3 -c "from src.sentinel.app import app; assert app.title == 'Sentinel'; echo PASS"` | PASS |

### Failure Procedure
If verification fails:
1. Stop execution immediately.
2. Inspect runtime errors produced by Python when importing `src.sentinel.app`.
3. Check for syntax typos in Pydantic schema definitions or endpoint route annotations.
4. Diagnose missing or broken route handler mappings.
5. Fix issues in `src/sentinel/app.py` and re-run verification checks.

### Completion Condition
`src/sentinel/app.py` exists, initializes FastAPI app named `Sentinel`, and imports cleanly without error.

---

## Stage 3: Business Logic & Rules Implementation

### Objective
Implement core business rules: Severity Rubric (0..3), Tier 3 Deduplication (300s window), Whitelist Rules, and Auth Guards on mutating endpoints.

### Inputs
- Business Rules from specification:
  - Severity Rubric: `0=nothing notable, 1=ambiguous, 2=actionable, 3=emergency`
  - Tier 3 Dedup: `events for the same camera within 300 s collapse into one incident`
  - Whitelist Rule: `whitelisted entity produces severity >= 1 only via novel_activity=true`
  - Auth Guard: `all mutating endpoints require X-API-Key header matching SENTINEL_API_KEY`

### Preconditions
- Stage 2 completed successfully.

### Discovery Tasks
- Inspect existing route implementations in `src/sentinel/app.py`.
- Identify where severity processing and deduplication logic should reside.

### Execution Tasks
1. Inspect `src/sentinel/app.py`.
2. Implement severity classification function based on rubric levels 0 through 3.
3. Implement deduplication service logic checking camera events within a 300-second window.
4. Update entity evaluation logic to enforce whitelist rules for non-novel activities.
5. Ensure all `POST`, `PUT`, `PATCH`, and `DELETE` routes enforce `verify_api_key`.
6. Write targeted unit tests in `tests/test_business_rules.py` covering deduplication, whitelist handling, and severity logic.

### Suggested Commands
```bash
# Create unit tests for business rules
python -c "import pathlib; pathlib.Path('tests').mkdir(parents=True, exist_ok=True); pathlib.Path('tests/test_business_rules.py').touch()"

# Execute test suite
pytest tests/test_business_rules.py -v
```

### Expected Outputs
- Updated `src/sentinel/app.py`
- `tests/test_business_rules.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| BR1   | `pytest tests/test_business_rules.py -q` | 0 failed |

### Failure Procedure
If verification fails:
1. Stop execution immediately.
2. Inspect failing test outputs to isolate failing business logic rule.
3. Adjust timestamp calculations or deduplication window query logic in `app.py`.
4. Verify `X-API-Key` headers are correctly checked on all mutating endpoints.
5. Re-run `pytest tests/test_business_rules.py`.

### Completion Condition
All business rule unit tests pass without failure.

---

## Stage 4: API Integration & Route Test Suite Validation

### Objective
Create comprehensive integration test suite covering all endpoints, response formats, error status codes, and HTTP client interactions using `httpx` and `pytest`.

### Inputs
- All 13 target routes defined in Stage 2
- Fast API TestClient / httpx

### Preconditions
- Stage 1, 2, and 3 complete.

### Discovery Tasks
- Inspect all endpoints registered on `app` in `src/sentinel/app.py`.
- Identify missing test coverage across endpoints.

### Execution Tasks
1. Inspect existing tests in `tests/`.
2. Create `tests/test_api.py`.
3. Add health check endpoint tests (`GET /health`).
4. Add authenticated vs unauthenticated camera creation tests (`POST /cameras`).
5. Add camera listing and camera detail retrieval tests (`GET /cameras`, `GET /cameras/{id}`).
6. Add camera patch tests (`PATCH /cameras/{id}`).
7. Add event injection, incident listing, and feedback routes tests.
8. Execute `pytest tests/ -q` to confirm full suite success.

### Suggested Commands
```bash
# Run complete test suite
pytest tests/ -v
```

### Expected Outputs
- `tests/test_api.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| INT1  | `pytest tests/ -q` | 0 failed |

### Failure Procedure
If verification fails:
1. Stop execution immediately.
2. Diagnose HTTP status code mismatches (e.g., 401 Unauthorized vs 422 Unprocessable Entity vs 404 Not Found).
3. Fix controller response logic in `src/sentinel/app.py`.
4. Re-run full test suite until all tests pass.

### Completion Condition
All tests in `tests/` execute and pass cleanly.

---

# Global Verification

Once all execution stages are complete, run global project validation:

1. **Full Test Suite Execution**:
   ```bash
   pytest tests/ -q
   ```
2. **Code Structure Integrity Check**:
   ```bash
   python3 -c "import src.sentinel.models; import src.sentinel.app; print('Imports functional')"
   ```
3. **Environment Security Check**:
   Confirm API key authorization behavior with correct (`SENTINEL_API_KEY`) and incorrect header inputs.

4. **End-to-End Smoke Harness** (runs against a live uvicorn server; asserts the L2/L5 contracts):
   ```python
   import os
   import time

   import httpx

   BASE = os.environ.get("SENTINEL_BASE_URL", "http://127.0.0.1:8000")
   API_KEY = os.environ["SENTINEL_API_KEY"]

   with httpx.Client(base_url=BASE, timeout=10.0) as client:
       # L1/L2: health is open, mutations are guarded
       assert client.get("/health").status_code == 200
       assert client.post("/cameras", json={"name": "front-door", "rtsp_url": "rtsp://127.0.0.1:8554/test"}).status_code == 401

       cam = client.post(
           "/cameras",
           json={"name": "front-door", "rtsp_url": "rtsp://127.0.0.1:8554/test"},
           headers={"X-API-Key": API_KEY},
       )
       assert cam.status_code == 201, cam.text
       camera_id = cam.json()["id"]

       # L4: event injection routes through the tier-1/tier-2 pathway
       started = time.time()
       ev = client.post(
           f"/cameras/{camera_id}/events",
           json={"burst_paths": ["bursts/f0.jpg", "bursts/f1.jpg", "bursts/f2.jpg"]},
           headers={"X-API-Key": API_KEY},
       )
       assert ev.status_code == 201, ev.text
       event_id = ev.json()["id"]

       # L5: feedback is accepted once and immutable afterwards
       fb = client.post(
           f"/events/{event_id}/feedback",
           json={"feedback": "false_alarm"},
           headers={"X-API-Key": API_KEY},
       )
       assert fb.status_code == 200, fb.text
       again = client.post(
           f"/events/{event_id}/feedback",
           json={"feedback": "true_event"},
           headers={"X-API-Key": API_KEY},
       )
       assert again.status_code == 409, again.text

       # L7: metrics expose the four required keys
       metrics = client.get("/metrics").json()
       for key in ("median_detect_latency_s", "false_alert_rate_7d", "events_24h", "vlm_frames_frac"):
           assert key in metrics, key
       print(f"SMOKE_OK latency={time.time() - started:.2f}s metrics={metrics}")
   ```

---

# Execution Rules

1. **Never skip stages**: Follow Stage 1 through Stage 4 in sequence.
2. **Never skip verification**: Execute local verification table checks after completing each stage.
3. **Never continue after a failed verification**: Stop and enter Failure Procedure immediately.
4. **Never modify files that have not been inspected**: Inspect files before editing.
5. **Always prefer incremental implementation**: Add functions and tests in small logical steps.
6. **Minimize edits**: Modify existing code accurately without unnecessary refactoring.
7. **Preserve backwards compatibility**: Ensure baseline schemas align with specs.
8. **Do not duplicate existing functionality**: Use SQLAlchemy ORM and FastAPI built-ins cleanly.
9. **Keep commits small and isolated**: Commit after each successful stage verification.
10. **Treat every stage as a complete iteration**: Ensure all outputs, verifications, and conditions pass before advancing.