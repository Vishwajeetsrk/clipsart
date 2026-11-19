"""The final renderer mixes an optional music bed and retains source audio."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

os.environ["CLIPSART_DATA"] = tempfile.mkdtemp(prefix="pc-render-audio-")
os.environ["CLIPSART_ACCOUNTS"] = "0"
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402
from studio import ctx, db, jobs, render, server  # noqa: E402
db.init()

root = Path(os.environ["CLIPSART_DATA"])
source, music, output = root / "source.mp4", root / "music.wav", root / "clips"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-t", "3", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True, capture_output=True)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
                "-ar", "44100", "-ac", "1", str(music)], check=True, capture_output=True)
result = render.render_clip(source, output, "mixed", {"start": 0, "end": 3, "layout": "crop", "captions": False,
                                                       "music_path": str(music), "music_volume": 0.12,
                                                       "source_volume": 0.7}, [], 640, 360)
probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                                    str(output / result["file"])], check=True, capture_output=True, text=True).stdout)
streams = probe["streams"]
audio = [s for s in streams if s.get("codec_type") == "audio"]
video = [s for s in streams if s.get("codec_type") == "video"]
ok = bool(audio and video and abs(float(probe["format"]["duration"]) - 3) < 0.4 and (output / result["cover"]).is_file())
print("PASS ffmpeg renders a music mix with video and source audio" if ok else f"FAIL mixed render output: {probe}")
dry_result = render.render_clip(source, output, "dry", {"start": 0, "end": 3, "layout": "crop", "captions": False}, [], 640, 360)
dry_probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                                       str(output / dry_result["file"])], check=True, capture_output=True, text=True).stdout)
dry_ok = any(s.get("codec_type") == "audio" for s in dry_probe["streams"])
print("PASS no-music render keeps original audio" if dry_ok else "FAIL no-music render lost original audio")
ok = ok and dry_ok
image_path = root / "overlay.png"
Image.new("RGBA", (80, 80), (255, 40, 20, 180)).save(image_path)
for effect, animation, name in (("warm", "none", "effect"), ("mono", "pulse", "animated")):
    styled = render.render_clip(source, output, name, {"start": 0, "end": 3, "layout": "crop", "captions": False,
                                                         "effect": effect, "animation": animation,
                                                         "overlay_path": str(image_path), "overlay_scale": 0.2}, [], 640, 360,
                               preview_size=(540, 960))
    styled_probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                                              str(output / styled["file"])], check=True, capture_output=True, text=True).stdout)
    styled_ok = any(s.get("codec_type") == "video" and (s["width"], s["height"]) == (540, 960)
                    for s in styled_probe["streams"])
    print(f"PASS {effect} effect, {animation} animation, and custom image overlay render" if styled_ok else f"FAIL {name} render")
    ok = ok and styled_ok
with ctx.as_user("u_local"):
    job = jobs.create({"type": "file", "path": str(source), "name": source.name}, {}, enqueue=False)
    job.update(status="done", source_path=str(source), width=640, height=360, duration=3.0)
    clip = {"id": "previewclip", "status": "done", "file": "previewclip.mp4", "start": 0.0, "end": 3.0,
            "hook": "Saved hook", "captions": False, "layout": "crop", "version": 1}
    job["clips"] = [clip]
    clip_dir = Path(job["dir"]) / "clips"; clip_dir.mkdir(parents=True, exist_ok=True)
    final_export = clip_dir / clip["file"]; final_export.write_bytes(b"preserve-final-export")
    jobs.save(job)
    client = TestClient(server.app, base_url="http://127.0.0.1:8765")
    headers = {"Origin": "http://127.0.0.1:8765"}
    response = client.post(f"/api/jobs/{job['id']}/clips/previewclip/preview",
                           json={"start": 0, "end": 3, "hook": "Preview hook", "captions": False, "layout": "crop",
                                 "effect": "vivid", "animation": "pulse", "overlay_scale": 0.2},
                           headers=headers)
    preview_ok = response.status_code == 200 and client.get(response.json().get("file", "")).status_code == 200
    preview_path = clip_dir / Path(response.json()["file"]).name if response.status_code == 200 else clip_dir / "missing.mp4"
    preview_probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                                                str(preview_path)], check=True, capture_output=True, text=True).stdout) if preview_path.is_file() else {"streams": []}
    preview_video = next(s for s in preview_probe["streams"] if s.get("codec_type") == "video")
    preview_ok = preview_ok and (preview_video["width"], preview_video["height"]) == (540, 960) and final_export.read_bytes() == b"preserve-final-export"
    preview_ok = preview_ok and clip["hook"] == "Saved hook" and clip["status"] == "done"
    print("PASS low-resolution preview leaves clip settings and final export unchanged" if preview_ok else f"FAIL preview changed saved state: {preview_video}")
    ok = ok and preview_ok
    with patch.object(render, "render_clip", side_effect=RuntimeError("synthetic encoder failure")):
        jobs.render_one(job, clip, [])
    rollback_ok = clip["status"] == "done" and bool(clip.get("render_error")) and final_export.read_bytes() == b"preserve-final-export"
    print("PASS failed final re-render keeps the previous clip available" if rollback_ok else f"FAIL failed render rollback: {clip}")
    ok = ok and rollback_ok
import shutil  # noqa: E402
shutil.rmtree(root, ignore_errors=True)
sys.exit(0 if ok else 1)
