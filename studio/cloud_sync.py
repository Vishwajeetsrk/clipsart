"""Google Drive, Dropbox, and Local Cloud Folder synchronization for finished clips."""
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from . import accounts, creators


def get_sync_dir() -> Optional[Path]:
    """Returns the validated Path of the configured cloud sync folder, or None if unconfigured/missing."""
    s = accounts.settings()
    raw = (s.get("cloud_sync_folder") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p if p.is_dir() else None
    except OSError:
        return None


def configured() -> bool:
    return get_sync_dir() is not None


def _clean_filename(text: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:60] if cleaned else "clip"


def export_clip(job: dict, clip: dict) -> Optional[str]:
    """Copies a rendered clip and its thumbnail into the user's cloud sync folder."""
    target_dir = get_sync_dir()
    if not target_dir:
        return None

    src_dir = Path(job.get("dir", "")) / "clips"
    clip_file = clip.get("file")
    if not clip_file:
        return None

    src_file = src_dir / clip_file
    if not src_file.is_file():
        return None

    creator = creators.get(job.get("creator")) or {}
    creator_folder = _clean_filename(creator.get("name") or "General")
    dest_dir = target_dir / creator_folder
    dest_dir.mkdir(parents=True, exist_ok=True)

    title = _clean_filename(clip.get("title") or clip.get("hook") or "clip")
    dest_file = dest_dir / f"{clip.get('id', 'clip')}_{title}.mp4"

    # Atomic write to avoid partial sync by cloud clients (Google Drive / Dropbox)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest_dir), prefix="sync_", suffix=".tmp")
    os.close(tmp_fd)
    try:
        shutil.copyfile(src_file, tmp_path)
        os.replace(tmp_path, dest_file)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    # Also sync thumbnail cover if available
    cover_file = clip.get("cover")
    if cover_file and (src_dir / cover_file).is_file():
        dest_thumb = dest_dir / f"{clip.get('id', 'clip')}_{title}.jpg"
        try:
            shutil.copyfile(src_dir / cover_file, dest_thumb)
        except Exception:
            pass

    return str(dest_file)
