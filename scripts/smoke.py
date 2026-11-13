import os
import time

import httpx

BASE = os.environ.get("SENTINEL_BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ["SENTINEL_API_KEY"]


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        assert client.get("/health").status_code == 200

        # mutations are guarded
        assert client.post("/cameras", json={"name": "front-door", "rtsp_url": "rtsp://127.0.0.1:8554/test"}).status_code == 401

        cam = client.post(
            "/cameras",
            json={"name": "front-door", "rtsp_url": "rtsp://127.0.0.1:8554/test"},
            headers={"X-API-Key": API_KEY},
        )
        assert cam.status_code == 201, cam.text
        camera_id = cam.json()["id"]

        started = time.time()
        ev = client.post(
            f"/cameras/{camera_id}/events",
            json={"burst_paths": ["bursts/f0.jpg", "bursts/f1.jpg", "bursts/f2.jpg"]},
            headers={"X-API-Key": API_KEY},
        )
        assert ev.status_code == 201, ev.text
        event_id = ev.json()["id"]
        assert ev.json()["severity"] >= 1
        assert ev.json()["vlm_json"] is not None

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

        metrics = client.get("/metrics").json()
        for key in ("median_detect_latency_s", "false_alert_rate_7d", "events_24h", "vlm_frames_frac"):
            assert key in metrics, key
        print(f"SMOKE_OK latency={time.time() - started:.2f}s metrics={metrics}")


if __name__ == "__main__":
    main()