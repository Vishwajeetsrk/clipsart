"""Cross-Platform View Analytics tracking and performance synchronization.

Aggregates view counts, reach, and performance metrics across YouTube Shorts,
Instagram Reels, TikTok, and other platforms, maintaining daily view growth curves.
"""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, Any, List

from . import accounts, config, ctx

log = logging.getLogger("studio.analytics")
_lock = threading.RLock()
_HISTORY_FILE = config.DATA_DIR / "analytics_history.json"


def _read_posts() -> List[Dict[str, Any]]:
    posts_file = config.DATA_DIR / "posts.json"
    if not posts_file.exists():
        return []
    try:
        return json.loads(posts_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def _read_history() -> List[Dict[str, Any]]:
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(history: List[Dict[str, Any]]):
    with _lock:
        tmp = _HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(history, indent=1), encoding="utf-8")
        tmp.replace(_HISTORY_FILE)


def summary() -> Dict[str, Any]:
    """Computes comprehensive cross-platform distribution and performance summary."""
    posts = _read_posts()
    try:
        u = ctx.uid()
    except Exception:
        u = "local"
    my_posts = [p for p in posts if (not p.get("user") or p.get("user") == u) and p.get("status") == "posted"]
    
    platforms = {"youtube": {"posts": 0, "views": 0, "shares": 0},
                 "instagram": {"posts": 0, "views": 0, "shares": 0},
                 "tiktok": {"posts": 0, "views": 0, "shares": 0},
                 "facebook": {"posts": 0, "views": 0, "shares": 0},
                 "twitter": {"posts": 0, "views": 0, "shares": 0},
                 "linkedin": {"posts": 0, "views": 0, "shares": 0}}
    
    total_views = 0
    top_clips = []

    for p in my_posts:
        plat = p.get("platform", "other").lower()
        views = int(p.get("views") or 0)
        total_views += views
        
        if plat in platforms:
            platforms[plat]["posts"] += 1
            platforms[plat]["views"] += views
        
        top_clips.append({
            "id": p.get("id"),
            "title": p.get("title") or "Clip",
            "platform": plat,
            "account_name": p.get("account_name", ""),
            "views": views,
            "url": p.get("url", ""),
            "score": p.get("score", 0),
            "posted_at": p.get("posted_at") or p.get("created", 0)
        })

    # Sort top clips by views descending, then by score
    top_clips.sort(key=lambda x: (x["views"], x["score"]), reverse=True)
    
    # Calculate daily snapshot
    today = time.strftime("%Y-%m-%d", time.localtime())
    history = _read_history()
    
    # Update or append today's entry
    existing_today = next((h for h in history if h.get("day") == today and h.get("user") == u), None)
    if existing_today:
        existing_today.update(views=total_views, posts=len(my_posts))
    else:
        history.append({"day": today, "user": u, "views": total_views, "posts": len(my_posts)})
        if len(history) > 60:
            history = history[-60:]
        _save_history(history)

    user_history = [h for h in history if h.get("user") == u]
    
    return {
        "total_posts": len(my_posts),
        "total_views": total_views,
        "avg_views_per_clip": round(total_views / max(1, len(my_posts)), 1),
        "platforms": platforms,
        "top_clips": top_clips[:10],
        "history": user_history[-14:],
        "last_synced": time.time()
    }


def refresh() -> Dict[str, Any]:
    """Actively polls live view counts from platform APIs (YouTube, Instagram) and updates posts."""
    posts_file = config.DATA_DIR / "posts.json"
    if not posts_file.exists():
        return summary()
    
    with _lock:
        try:
            posts = json.loads(posts_file.read_text(encoding="utf-8"))
        except Exception:
            return summary()
        
        u = ctx.uid()
        my_posted = [p for p in posts if p.get("user") == u and p.get("status") == "posted" and p.get("remote_id")]
        
        # Poll YouTube Views
        yt_accounts = {p["account"] for p in my_posted if p.get("platform") == "youtube"}
        for aid in yt_accounts:
            acc = accounts.get(aid)
            if acc:
                rids = [p["remote_id"] for p in my_posted if p.get("account") == aid and p.get("remote_id")]
                try:
                    views_map = accounts.youtube_views(acc, rids)
                    for p in my_posted:
                        if p.get("account") == aid and p.get("remote_id") in views_map:
                            p["views"] = views_map[p["remote_id"]]
                except Exception as e:
                    log.warning(f"Error refreshing YouTube views for {aid}: {e}")

        # Poll Instagram Views
        for p in my_posted:
            if p.get("platform") == "instagram" and p.get("account"):
                acc = accounts.get(p["account"])
                if acc:
                    try:
                        v = accounts.instagram_views(acc, p["remote_id"])
                        if v is not None:
                            p["views"] = v
                    except Exception as e:
                        log.debug(f"Error refreshing Instagram views: {e}")

        # Save updated views
        tmp = posts_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(posts, indent=1), encoding="utf-8")
        tmp.replace(posts_file)

    return summary()
