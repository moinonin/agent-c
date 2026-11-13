# Testing a Real Use Case for Sentinel

The unit tests in `tests/` prove the *contract* (routes, schemas, business rules).
This document describes how to prove the *behavior* — that Sentinel actually
detects what matters, fast enough, without drowning the owner in false alarms.

## The one metric that matters most

**False alerts per camera per day.** Everything else (latency, accuracy, cost) is
in service of keeping that number near zero while still catching the real events.
The soak test in section 2 is where you find out if you have actually achieved
that.

## 1. Offline replay harness (no camera needed - do this first)

Record 30-60 short clips (5-15 s) of your real cameras covering the cases you
care about: intruder, package theft, loitering, a delivery person, a pet, wind-blown
tree, rain, headlights, nothing. Label each clip with an expected severity (0-3).

Restream them as RTSP with `ffmpeg` + a tiny server (`mediamtx` /
`rtsp-simple-server`), then point Sentinel at `rtsp://127.0.0.1:8554/clipN`:

```bash
ffmpeg -re -stream_loop -1 -i clip.mp4 -c copy -f rtsp rtsp://127.0.0.1:8554/cam
```

For each clip, assert:
- `severity == expected`
- `alert_sent_at - started_at <= 10s`
- `vlm_json.summary` is non-empty

This gives you a deterministic regression set you can re-run on every change - the
golden set for the model.

## 2. Soak test (the metric that decides if it is usable)

Run one camera against a known-nuisance scene (wind, leaves, pets) for 60+ minutes
with `SENTINEL_RTSP_VALIDATION=off` and a real feed (or a long looped clip).
Then query `/metrics`:

- `vlm_frames_frac < 0.01` (Tier-2 budget: <1% of frames reach the VLM)
- `false_alert_rate_7d` <= 1 / hour / camera
- `median_detect_latency_s` <= 10

If those three hold, the system is trustworthy enough to deploy. If
`vlm_frames_frac` is high, your Tier-0 trigger is too sensitive - tighten the
motion threshold or add a zone mask.

## 3. Adversarial / red-team pass

Specifically try to break each tier:

- **Tier 0:** slow-moving intruder (below motion threshold), person in dark
  clothing against a dark background, camera partially obscured.
- **Tier 2:** send a burst where the VLM misclassifies (e.g. a mannequin, a
  poster of a person). Does the whitelist / severity rubric catch it?
- **Tier 3:** replay the same clip twice within 300 s - must collapse into one
  incident and one alert.
- **Tier 4:** feedback loop - mark 3 false alarms in 24 h - sensitivity
  auto-drops one step and the change is audit-logged (verify the row).
- **Availability:** kill the Gemini endpoint (unset key / firewall) - severity
  capped at 2, `vlm_status: degraded`, alert still sent.

## 4. Accuracy evaluation (labeled dataset)

For a real performance number, build a small labeled set (~200 clips, balanced
across severities 0-3). Run it through the pipeline offline and compute a
confusion matrix per severity. Track precision on severity >= 2 (the actionable
tier) - false positives there are the costly ones.

## 5. Integration and chaos checks

- Camera drop / reconnect mid-event (RTSP disconnect -> reconnect -> no crash,
  event ends gracefully).
- DB retention: seed 15-day-old burst files -> nightly purge removes bursts but
  keeps event rows.
- Auth: every mutating route returns 401 without `X-API-Key` (already in tests,
  keep it).
- Restart safety: kill uvicorn mid-event -> restart -> no orphaned "pending"
  events block the system.

## 6. What to wire into CI

A `pytest tests/ -q` gate on every PR (already green, 26 tests), plus a nightly
job that runs the offline replay suite (step 1) against a fixed clip pack and
fails if severity accuracy drops below a threshold (e.g. >= 90% on severity >= 2).
That is the regression net that actually protects the owner's trust.