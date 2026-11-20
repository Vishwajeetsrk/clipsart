"""Multimodal visual scene analyzer for video clips and live stream moments.

Extracts keyframes from video files via FFmpeg and inspects visual action,
facial expressions (shock, laugh, rage, focus), and scene dynamics using
Gemini Flash Vision (or optical motion fallback).
"""
import io
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any

from . import ai

log = logging.getLogger("studio.vision")


def extract_frame(video_path: Path, timestamp: float) -> bytes:
    """Extracts a single JPEG image frame at timestamp from a video file into memory."""
    if not video_path.is_file():
        return b""
    cmd = [
        "ffmpeg", "-nostdin", "-ss", f"{max(0.0, timestamp):.2f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-f", "image2",
        "-vcodec", "mjpeg",
        "-q:v", "3",
        "pipe:1"
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=True)
        return proc.stdout
    except Exception as e:
        log.warning(f"Failed extracting frame at {timestamp}s: {e}")
        return b""


def extract_scene_keyframes(video_path: Path, start: float, end: float, count: int = 3) -> List[Tuple[float, bytes]]:
    """Extracts evenly spaced keyframes across a time interval."""
    dur = max(0.5, end - start)
    timestamps = [start + 0.2 + (dur - 0.4) * (i / max(1, count - 1)) for i in range(count)]
    frames = []
    for ts in timestamps:
        frame_bytes = extract_frame(video_path, ts)
        if frame_bytes:
            frames.append((round(ts, 2), frame_bytes))
    return frames


def _optical_motion_fallback(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """Measures visual motion energy by computing frame difference variance across keyframes."""
    if len(frames) < 2:
        return {"visual_energy": 55, "expression": "focused", "action_tags": ["standard motion"], "visual_hook": "WATCH THIS MOMENT"}
    
    try:
        from PIL import Image
        import numpy as np
        
        diffs = []
        for i in range(len(frames) - 1):
            im1 = Image.open(io.BytesIO(frames[i][1])).convert("L").resize((160, 90))
            im2 = Image.open(io.BytesIO(frames[i+1][1])).convert("L").resize((160, 90))
            arr1, arr2 = np.array(im1, dtype=np.float32), np.array(im2, dtype=np.float32)
            delta = float(np.mean(np.abs(arr1 - arr2)))
            diffs.append(delta)
        
        mean_diff = float(np.mean(diffs)) if diffs else 10.0
        # Scale mean diff (typically 2 - 40) into 0-100 score
        energy = int(min(98, max(25, mean_diff * 3.2)))
        expr = "shocked" if energy > 75 else "laughing" if energy > 60 else "focused"
        tags = ["high motion" if energy > 70 else "medium motion", "active gameplay"]
        return {
            "visual_energy": energy,
            "expression": expr,
            "action_tags": tags,
            "visual_hook": "WAIT FOR THE PLAY" if energy > 70 else "KEY MOMENT"
        }
    except Exception:
        return {"visual_energy": 50, "expression": "focused", "action_tags": ["motion detected"], "visual_hook": "WATCH THIS"}


def analyze_scene(video_path: Path, start: float, end: float, hook: str = "") -> Dict[str, Any]:
    """Analyzes visual scene dynamics, facial expressions, and visual energy for a clip.
    
    Uses Gemini / OpenAI vision if configured; otherwise uses fast optical motion diffing.
    """
    frames = extract_scene_keyframes(video_path, start, end, count=3)
    if not frames:
        return {"visual_energy": 50, "expression": "neutral", "action_tags": [], "visual_hook": hook or "MOMENT"}

    # If AI service with vision is ready, call ai.see on the most dynamic frame (midpoint)
    if ai.ready():
        mid_frame = frames[len(frames) // 2][1]
        prompt = (
            "Analyze this video frame from a video moment.\n"
            "Respond in JSON with these keys:\n"
            "{\"visual_energy\": (integer 0-100, level of action or excitement),\n"
            " \"expression\": (one word: shocked, laughing, screaming, focused, grinning, or neutral),\n"
            " \"action_tags\": [array of 2-3 short action tags, e.g. \"headshot\", \"laugh\", \"celebration\"],\n"
            " \"visual_hook\": (punchy 3-5 word ALL CAPS hook describing visual action)}\n"
            "Answer with valid JSON only."
        )
        try:
            resp_text, _, _ = ai.see(prompt, mid_frame, timeout=12)
            if resp_text:
                m = re.search(r"\{.*\}", resp_text, re.S)
                if m:
                    data = json.loads(m.group(0))
                    return {
                        "visual_energy": int(data.get("visual_energy", 65)),
                        "expression": str(data.get("expression", "focused")),
                        "action_tags": list(data.get("action_tags", [])),
                        "visual_hook": str(data.get("visual_hook", hook or "WATCH THIS")).upper()[:40]
                    }
        except Exception as e:
            log.debug(f"AI vision call fallback to optical diff: {e}")

    # Fallback to optical motion delta
    return _optical_motion_fallback(frames)
