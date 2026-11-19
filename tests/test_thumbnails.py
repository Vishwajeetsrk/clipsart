"""Video frame capture, thumbnail upload, replacement, restoration and clip compatibility."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["CLIPSART_DATA"] = tempfile.mkdtemp(prefix="pc-thumbnail-")
os.environ["CLIPSART_ACCOUNTS"] = "0"
sys.path.insert(0, ".")

from PIL import Image  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from studio import auth, ctx, db, jobs, render, server  # noqa: E402

db.init()
root = Path(os.environ["CLIPSART_DATA"])
source = root / "source.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-t", "3", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True, capture_output=True)
rendered = render.render_clip(source, root / "rendered", "thumbnail-source",
                              {"start": 0, "end": 3, "layout": "crop", "captions": False}, [], 640, 360)
ok = True
with ctx.as_user(auth.local_user().id):
    job = jobs.create({"type": "file", "path": str(source), "name": source.name}, {}, enqueue=False)
    job.update(status="done", source_path=str(source), width=640, height=360, duration=3.0)
    clip_dir = Path(job["dir"]) / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clip_file = clip_dir / "thumbclip.v1.mp4"
    shutil.copyfile(root / "rendered" / rendered["file"], clip_file)
    cover = "thumbclip.v1.jpg"
    shutil.copyfile(root / "rendered" / rendered["cover"], clip_dir / cover)
    clip = {"id": "thumbclip", "status": "done", "file": clip_file.name, "cover": cover,
            "generated_cover": cover, "start": 0.0, "end": 3.0, "hook": "Saved hook", "captions": False,
            "layout": "crop", "version": 1}
    job["clips"] = [clip]
    jobs.save(job)

client = TestClient(server.app, base_url="http://127.0.0.1:8765")
headers = {"Origin": "http://127.0.0.1:8765"}
url = f"/api/jobs/{job['id']}/clips/thumbclip/thumbnail"
frame = client.post(url + "/frame", json={"seconds": 1.0}, headers=headers)
frame_ok = frame.status_code == 200 and client.get(frame.json()["file"]).status_code == 200
frame_file = clip_dir / Path(frame.json()["file"]).name if frame.status_code == 200 else clip_dir / "missing.jpg"
with Image.open(frame_file) as im:
    frame_ok = frame_ok and im.size == (720, 1280)
print("PASS extracts an in-range frame as a vertical thumbnail" if frame_ok else f"FAIL frame capture: {frame.status_code} {frame.text}")
ok = ok and frame_ok
outside = client.post(url + "/frame", json={"seconds": 3}, headers=headers)
outside_ok = outside.status_code == 400 and clip["cover"] == cover
print("PASS rejects a frame time outside the clip without changing its cover" if outside_ok else "FAIL out-of-range frame handling")
ok = ok and outside_ok

image = Image.new("RGB", (640, 640), (18, 92, 165))
buf = root / "uploaded.png"
image.save(buf)
with buf.open("rb") as f:
    saved = client.post(url + "/save", files={"file": ("uploaded.png", f, "image/png")},
                        data={"title": "My highlight", "style": "neon"}, headers=headers)
save_ok = saved.status_code == 200 and clip.get("thumbnail_custom") is True and clip["cover"] == saved.json().get("file")
with Image.open(clip_dir / clip["cover"]) as im:
    save_ok = save_ok and im.format == "JPEG" and im.size == (720, 1280)
save_ok = save_ok and clip.get("thumbnail_text") == "My highlight" and clip.get("thumbnail_style") == "neon"
print("PASS saves and normalizes an uploaded thumbnail with title settings" if save_ok else f"FAIL thumbnail save: {saved.status_code} {saved.text}")
ok = ok and save_ok
custom_cover = clip["cover"]
bad = client.post(url + "/save", files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
                  data={"title": "Broken", "style": "bold"}, headers=headers)
bad_ok = bad.status_code == 400 and clip["cover"] == custom_cover and (clip_dir / custom_cover).is_file()
print("PASS invalid image upload preserves the current thumbnail" if bad_ok else "FAIL invalid image rollback")
ok = ok and bad_ok
with patch.object(jobs, "save", side_effect=OSError("synthetic metadata write failure")):
    broken_client = TestClient(server.app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False)
    with buf.open("rb") as f:
        failed_save = broken_client.post(url + "/save", files={"file": ("uploaded.png", f, "image/png")},
                                         data={"title": "Failed write", "style": "bold"}, headers=headers)
rollback_ok = failed_save.status_code == 500 and clip["cover"] == custom_cover and (clip_dir / custom_cover).is_file()
rollback_ok = rollback_ok and {p.name for p in clip_dir.glob("thumbclip.thumb-*.jpg")} == {custom_cover}
print("PASS metadata write failure keeps the previous thumbnail and removes the uncommitted image" if rollback_ok else "FAIL thumbnail write rollback")
ok = ok and rollback_ok

next_cover = "thumbclip.v2.jpg"
(clip_dir / "thumbclip.v2.mp4").write_bytes(b"new render")
Image.new("RGB", (720, 1280), (2, 3, 4)).save(clip_dir / next_cover)
with patch.object(render, "render_clip", return_value={"file": "thumbclip.v2.mp4", "cover": next_cover, "layout": "crop"}):
    jobs.render_one(job, clip, [])
rerender_ok = clip["cover"] == custom_cover and clip["generated_cover"] == next_cover and clip["thumbnail_custom"]
print("PASS clip re-render preserves custom cover and refreshes generated cover" if rerender_ok else "FAIL custom cover lost on re-render")
ok = ok and rerender_ok
reset = client.post(url + "/reset", headers=headers)
reset_ok = reset.status_code == 200 and clip["cover"] == next_cover and not clip.get("thumbnail_custom")
reset_ok = reset_ok and not (clip_dir / custom_cover).exists()
print("PASS restores the generated thumbnail and removes the replaced custom image" if reset_ok else f"FAIL thumbnail reset: {reset.status_code} {reset.text}")
ok = ok and reset_ok

shutil.rmtree(root, ignore_errors=True)
sys.exit(0 if ok else 1)
