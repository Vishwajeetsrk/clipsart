"""Syncs finished and scheduled clips into a Notion database (Kanban board)."""
import time
from typing import Optional
import httpx
from . import accounts, ctx

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def configured() -> bool:
    s = accounts.settings()
    return bool(s.get("notion_token") and s.get("notion_database_id"))


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def sync_clip(title: str, hook: str = "", status: str = "Ready", duration: float = 0.0,
              score: int = 0, tags: Optional[list] = None, clip_url: str = "") -> dict:
    """Creates a new card in the creator's Notion Content Kanban database."""
    s = accounts.settings()
    token = s.get("notion_token", "").strip()
    db_id = s.get("notion_database_id", "").strip().replace("-", "")

    if not token or not db_id:
        raise ValueError("Notion integration is not configured. Add your Token and Database ID in Settings.")

    clean_tags = [{"name": str(t).replace("#", "").strip()[:50]} for t in (tags or []) if str(t).strip()][:10]

    properties = {
        "Name": {
            "title": [{"text": {"content": title[:100] or "Untitled Clip"}}]
        }
    }

    # Optional properties added safely
    if hook:
        properties["Hook"] = {
            "rich_text": [{"text": {"content": hook[:500]}}]
        }
    if score:
        properties["Score"] = {"number": int(score)}
    if duration:
        properties["Duration"] = {"number": round(float(duration), 1)}
    if clean_tags:
        properties["Tags"] = {"multi_select": clean_tags}
    if status:
        properties["Status"] = {"select": {"name": status}}

    payload = {
        "parent": {"database_id": db_id},
        "properties": properties
    }

    try:
        r = httpx.post(f"{NOTION_API}/pages", json=payload, headers=_headers(token), timeout=20)
        if r.status_code >= 400:
            err = r.json().get("message", f"Notion API error {r.status_code}")
            raise ValueError(f"Notion: {err}")
        data = r.json()
        return {"id": data.get("id"), "url": data.get("url")}
    except httpx.RequestError as e:
        raise ValueError(f"Could not connect to Notion: {e}")
