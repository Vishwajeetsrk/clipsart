"""Sound effects (SFX) engine for punchy short-form viral videos.

Synthesizes and caches studio-quality short SFX (whoosh, pop, ding, boom)
using numpy and soundfile, and provides FFmpeg filter mixing for punchline triggers.
"""
from pathlib import Path
import math
import numpy as np
import soundfile as sf

from . import config

SFX_DIR = config.DATA_DIR / "sfx"
SAMPLE_RATE = 44100

SFX_NAMES = ("whoosh", "pop", "ding", "boom")


def synthesize_sfx_library(target_dir: Path = None) -> dict:
    """Generates clean studio-grade audio effects on disk and returns paths."""
    out_dir = Path(target_dir) if target_dir else SFX_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {}
    
    # 1. Whoosh: 0.35s dynamic filtered sweep for hook/transition entry
    whoosh_path = out_dir / "whoosh.wav"
    if not whoosh_path.exists():
        t = np.linspace(0, 0.35, int(SAMPLE_RATE * 0.35), endpoint=False)
        noise = np.random.uniform(-1, 1, len(t))
        envelope = (np.sin(np.pi * t / 0.35) ** 2)
        phase = 2 * np.pi * (180 * t + 820 * (t ** 2))
        whoosh = noise * envelope * np.sin(phase) * 0.65
        sf.write(str(whoosh_path), whoosh.astype(np.float32), SAMPLE_RATE)
    res["whoosh"] = whoosh_path

    # 2. Pop: 0.10s snappy bubble/word punch
    pop_path = out_dir / "pop.wav"
    if not pop_path.exists():
        t = np.linspace(0, 0.10, int(SAMPLE_RATE * 0.10), endpoint=False)
        freq = np.linspace(1500, 280, len(t))
        pop = np.sin(2 * np.pi * freq * t) * np.exp(-t * 42) * 0.75
        sf.write(str(pop_path), pop.astype(np.float32), SAMPLE_RATE)
    res["pop"] = pop_path

    # 3. Ding: 0.45s crystal harmonic chime for highlight moments
    ding_path = out_dir / "ding.wav"
    if not ding_path.exists():
        t = np.linspace(0, 0.45, int(SAMPLE_RATE * 0.45), endpoint=False)
        ding = (np.sin(2 * np.pi * 2093 * t) * 0.6 + np.sin(2 * np.pi * 4186 * t) * 0.28) * np.exp(-t * 9) * 0.65
        sf.write(str(ding_path), ding.astype(np.float32), SAMPLE_RATE)
    res["ding"] = ding_path

    # 4. Boom: 0.65s deep sub-bass cinematic hit for punchline climax
    boom_path = out_dir / "boom.wav"
    if not boom_path.exists():
        t = np.linspace(0, 0.65, int(SAMPLE_RATE * 0.65), endpoint=False)
        freq = np.linspace(140, 42, len(t))
        boom = np.sin(2 * np.pi * freq * t) * np.exp(-t * 6.5) * 0.8
        sf.write(str(boom_path), boom.astype(np.float32), SAMPLE_RATE)
    res["boom"] = boom_path

    return res


def ensure_sfx():
    return synthesize_sfx_library(SFX_DIR)


def get_sfx_path(name: str) -> Path:
    ensure_sfx()
    name = name.lower().replace(".wav", "").strip()
    p = SFX_DIR / f"{name}.wav"
    if p.exists():
        return p
    return SFX_DIR / "pop.wav"


def plan_sfx_events(words: list, hook: str, clip_dur: float = None, auto_emoji: bool = True, sfx_preset: str = "punchy", duration: float = None) -> list[dict]:
    """Plans timestamps and types of sound effects throughout a clip.
    
    Returns list of dicts: [{'name': 'whoosh', 'time': 0.1, 'volume': 0.6}, ...]
    """
    if clip_dur is None:
        clip_dur = float(duration if duration is not None else 30.0)
    ensure_sfx()
    events = []
    
    # Entrance whoosh at hook start
    if hook and clip_dur > 1.5:
        events.append({"name": "whoosh", "time": 0.1, "volume": 0.55})

    # Find punchline highlights or auto-emoji moments
    from .render import EMOJI_WORDS, _key
    
    emoji_hits = 0
    for w in words:
        t = w.get("s", 0)
        if t < 0.8 or t > clip_dur - 1.2:
            continue
        k = _key(w.get("w", ""))
        if auto_emoji and k in EMOJI_WORDS and emoji_hits < 4:
            sfx_type = "ding" if k in ("win", "rich", "money", "cash", "gold", "trophy", "top") else "pop"
            events.append({"name": sfx_type, "time": round(t, 2), "volume": 0.45})
            emoji_hits += 1

    # Climax boom near last punchline if long enough
    if clip_dur >= 8.0:
        climax_t = max(clip_dur - 2.5, clip_dur * 0.82)
        events.append({"name": "boom", "time": round(climax_t, 2), "volume": 0.5})

    return events


def generate_sfx_track(events: list, duration: float, out_path: Path, sr: int = 48000) -> bool:
    """Pre-renders all scheduled sound effects onto a single audio track with microsecond accuracy."""
    if not events or duration <= 0:
        return False
    ensure_sfx()
    total_samples = int(sr * duration)
    track = np.zeros((total_samples, 2), dtype=np.float32)
    
    loaded_cache = {}
    for ev in events:
        name = ev["name"]
        if name not in loaded_cache:
            p = get_sfx_path(name)
            data, file_sr = sf.read(str(p))
            if data.ndim == 1:
                data = np.column_stack([data, data])
            if file_sr != sr:
                indices = np.round(np.linspace(0, len(data) - 1, int(len(data) * sr / file_sr))).astype(int)
                data = data[indices]
            loaded_cache[name] = data
        
        sample = loaded_cache[name]
        start_idx = int(ev["time"] * sr)
        if start_idx >= total_samples:
            continue
        vol = max(0.05, min(1.0, ev.get("volume", 0.5)))
        end_idx = min(total_samples, start_idx + len(sample))
        sample_len = end_idx - start_idx
        track[start_idx:end_idx] += sample[:sample_len] * vol

    max_val = float(np.max(np.abs(track)))
    if max_val > 0.95:
        track = track * (0.95 / max_val)

    sf.write(str(out_path), track.astype(np.float32), sr)
    return True


def build_sfx_filter(base_audio_label: str, events: list[dict], out_label: str = "a_out") -> tuple[list[str], list[str]]:
    """Builds extra FFmpeg inputs and complex filter string for mixing planned SFX.
    
    Returns: (extra_ffmpeg_inputs, filtergraph_str)
    """
    if not events:
        return [], f"[{base_audio_label}]anull[{out_label}]"

    extra_inputs = []
    mix_labels = [f"[{base_audio_label}]"]
    filter_parts = []

    for i, ev in enumerate(events):
        path = get_sfx_path(ev["name"])
        extra_inputs.extend(["-i", str(path)])
        
        # Audio input index will be resolved by caller (or mapped sequentially)
        # We construct an adelay filter for the sound effect
        delay_ms = max(0, int(ev["time"] * 1000))
        vol = max(0.1, min(1.0, ev.get("volume", 0.5)))
        sfx_in = f"sfx_in_{i}"
        sfx_delayed = f"sfx_d_{i}"
        
        filter_parts.append(f"[{sfx_in}]volume={vol:.2f},adelay={delay_ms}|{delay_ms}[{sfx_delayed}]")
        mix_labels.append(f"[{sfx_delayed}]")

    num_inputs = len(mix_labels)
    filter_parts.append(f"{''.join(mix_labels)}amix=inputs={num_inputs}:duration=first:dropout_transition=2[{out_label}]")
    
    return extra_inputs, ";".join(filter_parts)
