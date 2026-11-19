"""Explicit-time post scheduling; uses an isolated temporary user-data folder."""
import os
import sys
import io
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-schedule-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_ACCOUNTS"] = "1"
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402
from studio import accounts, auth, creators, ctx, db, jobs, posting, server  # noqa: E402

db.init()
fails = []


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    ok or fails.append(name)


def time_now():
    return datetime.now(timezone.utc).timestamp()


u, _ = auth._create("schedule@example.com", "Schedule", password_hash="x")
client = TestClient(server.app, base_url="http://127.0.0.1:8765")
client.cookies.set(auth.COOKIE, auth.start_session(u.id))
origin = {"Origin": "http://127.0.0.1:8765"}
with ctx.as_user(u.id):
    creator = creators.create({"name": "Scheduler", "post_gap_min": 5, "daily_cap": 2})
    accounts._put({"id": "account-one", "platform": "youtube", "name": "Channel", "added": 1})
    jobs_to_schedule = []
    for n in range(1, 5):
        job = jobs.create({"type": "file", "path": "", "name": f"video-{n}.mp4"}, {}, enqueue=False, creator=creator["id"])
        job["clips"].append({"id": f"clip-{n}", "status": "done", "file": f"clip-{n}.mp4", "title": f"Clip {n}", "hook": "Hook", "start": 0, "end": 10})
        job["status"] = "done"
        jobs.save(job)
        jobs_to_schedule.append(job)

    try:
        posting._local_schedule("2026-03-08T02:30", "America/New_York")
        gap_rejected = False
    except ValueError:
        gap_rejected = True
    check("rejects a nonexistent daylight-saving wall time", gap_rejected)
    try:
        posting._local_schedule("2026-11-01T01:30", "America/New_York")
        overlap_rejected = False
    except ValueError:
        overlap_rejected = True
    check("rejects an ambiguous daylight-saving wall time", overlap_rejected)

    local_time = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
    def schedule(job, at, zone="UTC"):
        return client.post("/api/posts", json={"job": job["id"], "clip": job["clips"][0]["id"], "accounts": ["account-one"],
                                                "scheduled_at": at.strftime("%Y-%m-%dT%H:%M"), "timezone": zone}, headers=origin)

    r = schedule(jobs_to_schedule[0], local_time)
    check("creates a post at the selected UTC time", r.status_code, 200)
    scheduled = next(p for p in posting._posts if p.get("job") == jobs_to_schedule[0]["id"])
    check("stores epoch and timezone on the scheduled post",
          abs(scheduled["due_at"] - local_time.timestamp()) < 1 and scheduled["scheduled_timezone"] == "UTC")
    music_fixture = Path(os.environ["PEAKCUT_DATA"]) / "test-music.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    "-ar", "44100", "-ac", "1", str(music_fixture)], check=True, capture_output=True)
    music_bytes = music_fixture.read_bytes()
    r = client.post(f"/api/jobs/{jobs_to_schedule[0]['id']}/clips/clip-1/music",
                    files={"file": ("tone.wav", io.BytesIO(music_bytes), "audio/wav")},
                    data={"rights_confirmed": "yes", "attribution": "Original test tone", "license_url": "https://example.com/license"},
                    headers=origin)
    check("imports owned/licensed audio and keeps attribution", r.status_code == 200 and r.json().get("attribution") == "Original test tone")
    check("requires reuse rights confirmation before accepting a music file",
          client.post(f"/api/jobs/{jobs_to_schedule[0]['id']}/clips/clip-1/music",
                      files={"file": ("tone.wav", io.BytesIO(music_bytes), "audio/wav")},
                      data={"rights_confirmed": "no"}, headers=origin).status_code, 400)
    r = schedule(jobs_to_schedule[1], local_time + timedelta(minutes=2))
    check("rejects a schedule inside the account spacing window", (r.status_code, "at least 5 minutes" in r.text), (400, True))
    r = schedule(jobs_to_schedule[1], local_time + timedelta(minutes=10))
    check("accepts another time respecting account spacing", r.status_code, 200)
    r = schedule(jobs_to_schedule[2], local_time + timedelta(minutes=20))
    check("enforces the account daily cap", (r.status_code, "already has 2 post(s)" in r.text), (400, True))
    r = schedule(jobs_to_schedule[2], local_time + timedelta(minutes=20), "Not/A_Real_Zone")
    check("rejects an unknown timezone", (r.status_code, "timezone" in r.text.lower()), (400, True))

    made = posting.enqueue(jobs_to_schedule[3], jobs_to_schedule[3]["clips"][0], ["account-one", "account-one"])
    check("keeps automatic queue scheduling and ignores duplicate account ids", len(made) == 1 and made[0]["due_at"] > time_now())

import shutil  # noqa: E402
db.engine.dispose()
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
