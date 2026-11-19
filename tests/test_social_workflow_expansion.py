"""Tests for Social Media and Workflow Expansions:
Option 1: X / Twitter & LinkedIn Video
Option 2: Facebook Reels
Option 3: Notion Kanban Sync & Cloud Folder Auto-Backup
Option 4: Community MP4 Video Drops (Discord & Telegram)
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ["CLIPSART_DATA"] = tempfile.mkdtemp(prefix="pc-social-")
os.environ["DATABASE_URL"] = ""
os.environ["CLIPSART_ACCOUNTS"] = "1"
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402
from studio import accounts, alerts, auth, cloud_sync, creators, ctx, db, jobs, notion, posting, server  # noqa: E402

db.init()
fails = []


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    ok or fails.append(name)


u, _ = auth._create("creator@example.com", "Creator", password_hash="x")
with db.engine.begin() as c:
    c.execute(db.users.update().where(db.users.c.id == u.id).values(is_admin=True))
client = TestClient(server.app, base_url="http://127.0.0.1:8765")
client.cookies.set(auth.COOKIE, auth.start_session(u.id))
origin = {"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"}

with ctx.as_user(u.id):
    # 1. Test Settings defaults and update
    s = accounts.settings()
    check("settings default cloud_sync_folder", s.get("cloud_sync_folder"), "")
    check("settings default notion_token", s.get("notion_token"), "")
    check("settings default auto_drop_community", s.get("auto_drop_community"), False)

    sync_tmp_dir = tempfile.mkdtemp(prefix="cloud-sync-")
    r = client.put("/api/settings", json={
        "cloud_sync_folder": sync_tmp_dir,
        "notion_token": "secret_notion_123",
        "notion_database_id": "4a5b6c7d-8e9f-0123-4567-89abcdef0123",
        "auto_drop_community": True,
        "discord_webhook": "https://discord.com/api/webhooks/123/abc",
        "telegram_token": "123456:ABC-DEF",
        "telegram_chat": "-1001234567"
    }, headers=origin)
    check("update settings status 200", r.status_code, 200)

    # Check secret masking when read via API
    r_get = client.get("/api/settings", headers=origin)
    settings_data = r_get.json()
    check("notion_token masked", settings_data.get("notion_token"), True)
    check("discord_webhook masked", settings_data.get("discord_webhook"), True)
    check("telegram_token masked", settings_data.get("telegram_token"), True)
    check("cloud_sync_folder unmasked", settings_data.get("cloud_sync_folder"), sync_tmp_dir)

    # 2. Test Notion Integration
    check("notion configured is True", notion.configured(), True)
    
    mock_notion_res = MagicMock()
    mock_notion_res.status_code = 200
    mock_notion_res.json.return_value = {
        "id": "page_notion_999",
        "url": "https://notion.so/page_notion_999"
    }
    
    with patch("httpx.post", return_value=mock_notion_res):
        sync_result = notion.sync_clip(
            title="Mindset Shift",
            hook="Stop wasting time",
            status="Ready",
            duration=42.5,
            score=95,
            tags=["podcast", "productivity"]
        )
        check("notion sync_clip returns id", sync_result.get("id"), "page_notion_999")
        check("notion sync_clip returns url", sync_result.get("url"), "https://notion.so/page_notion_999")

    # 3. Test Cloud Sync (Google Drive / Dropbox)
    check("cloud_sync configured is True", cloud_sync.configured(), True)

    creator = creators.create({"name": "Tech Podcasts", "post_gap_min": 5, "daily_cap": 2})
    job = jobs.create({"type": "file", "path": "", "name": "interview.mp4"}, {}, enqueue=False, creator=creator["id"])
    
    clips_dir = Path(job["dir"]) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_file = clips_dir / "clip_01.mp4"
    clip_file.write_bytes(b"dummy mp4 video bytes")
    cover_file = clips_dir / "clip_01.jpg"
    cover_file.write_bytes(b"dummy cover jpg")

    clip = {
        "id": "c1",
        "status": "done",
        "file": "clip_01.mp4",
        "cover": "clip_01.jpg",
        "title": "Best Tech Advice",
        "hook": "Here is the secret",
        "score": 90,
        "start": 0,
        "end": 30,
        "hashtags": ["tech", "ai"]
    }
    job["clips"].append(clip)
    job["status"] = "done"
    jobs.save(job)

    dest_exported = cloud_sync.export_clip(job, clip)
    check("cloud_sync exported successfully", bool(dest_exported), True)
    check("exported mp4 exists", Path(dest_exported).is_file(), True)
    check("exported file matches creator folder", "Tech Podcasts" in dest_exported, True)

    # Test cloud sync export API endpoint
    r_export = client.post(f"/api/cloud-sync/export/{job['id']}/c1", headers=origin)
    check("cloud-sync export endpoint returns 200", r_export.status_code, 200)
    check("cloud-sync export response ok", r_export.json().get("ok"), True)

    # 4. Test Community MP4 Video Drops (Discord & Telegram)
    check("alerts configured is True", alerts.configured(), True)
    
    mock_discord_resp = MagicMock()
    mock_discord_resp.status_code = 204
    
    mock_telegram_resp = MagicMock()
    mock_telegram_resp.status_code = 200
    mock_telegram_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}

    with patch("httpx.post", side_effect=[mock_discord_resp, mock_telegram_resp]):
        problems = alerts.send_clip_drop(clip_file, "Best Tech Advice", "Here is the secret", "Watch this clip!")
        check("send_clip_drop returns no problems", len(problems), 0)

    # Test community drop endpoint
    with patch("httpx.post", side_effect=[mock_discord_resp, mock_telegram_resp]):
        r_drop = client.post(f"/api/alerts/drop/{job['id']}/c1", headers=origin)
        check("alerts drop endpoint returns 200", r_drop.status_code, 200)

    # 5. Test Social Platform Uploads: Twitter, LinkedIn, Facebook Reels
    # Mock Twitter API
    mock_tw_init = MagicMock(status_code=200)
    mock_tw_init.json.return_value = {"media_id_string": "tw_media_123"}
    mock_tw_append = MagicMock(status_code=204)
    mock_tw_finalize = MagicMock(status_code=200)
    mock_tw_finalize.json.return_value = {"media_id_string": "tw_media_123"}
    mock_tw_tweet = MagicMock(status_code=201)
    mock_tw_tweet.json.return_value = {"data": {"id": "1892837465"}}

    with patch("httpx.post", side_effect=[mock_tw_init, mock_tw_append, mock_tw_finalize, mock_tw_tweet]):
        tw_id, tw_url = accounts.twitter_upload(
            {"bearer_token": "tw_tok"}, clip_file, "Exciting new clip! #podcast"
        )
        check("twitter_upload returns tweet id", tw_id, "1892837465")
        check("twitter_upload returns tweet url", tw_url, "https://twitter.com/i/status/1892837465")

    # Mock LinkedIn API
    mock_li_register = MagicMock(status_code=200)
    mock_li_register.json.return_value = {
        "value": {
            "asset": "urn:li:digitalmediaAsset:C5500A",
            "uploadMechanism": {
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {
                    "uploadUrl": "https://api.linkedin.com/mediaUpload/123"
                }
            }
        }
    }
    mock_li_put = MagicMock(status_code=200)
    mock_li_post = MagicMock(status_code=201)
    mock_li_post.json.return_value = {"id": "urn:li:ugcPost:67890"}

    with patch("httpx.post", side_effect=[mock_li_register, mock_li_post]), patch("httpx.put", return_value=mock_li_put):
        li_id, li_url = accounts.linkedin_upload(
            {"access_token": "li_tok", "person_id": "urn:li:person:abcdef"},
            clip_file, "Business lessons from industry leaders #business", "Business Lessons"
        )
        check("linkedin_upload returns post id", li_id, "urn:li:ugcPost:67890")
        check("linkedin_upload returns post url", li_url, "https://www.linkedin.com/feed/update/urn:li:ugcPost:67890")

    # Mock Facebook Reels API
    mock_fb_init = MagicMock(status_code=200)
    mock_fb_init.json.return_value = {"video_id": "fb_vid_123", "upload_url": "https://rupload.facebook.com/123"}
    mock_fb_upload = MagicMock(status_code=200)
    mock_fb_publish = MagicMock(status_code=200)

    with patch("httpx.post", side_effect=[mock_fb_init, mock_fb_upload, mock_fb_publish]):
        fb_id, fb_url = accounts.facebook_upload(
            {"access_token": "fb_tok", "page_id": "fb_page_456"},
            clip_file, "Viral gaming moment! #gaming", "c1"
        )
        check("facebook_upload returns video id", fb_id, "fb_vid_123")
        check("facebook_upload returns reel url", fb_url, "https://www.facebook.com/watch/?v=fb_vid_123")

    # 6. Test Posting Queue dispatch for these new platforms
    post_item_tw = {
        "id": "post_tw_1",
        "job": job["id"],
        "clip": "c1",
        "creator": creator["id"],
        "platform": "twitter",
        "account": "acc_tw",
        "account_name": "X Account",
        "status": "scheduled",
        "tries": 0,
        "post_at": 1000
    }
    with patch("studio.accounts.twitter_upload", return_value=("1892837465", "https://twitter.com/i/status/1892837465")), \
         patch("studio.accounts.get", return_value={"id": "acc_tw", "name": "X Account", "platform": "twitter"}):
        posting._post(post_item_tw)
        check("posting twitter sets status to posted", post_item_tw["status"], "posted")
        check("posting twitter sets remote url", post_item_tw["url"], "https://twitter.com/i/status/1892837465")

    post_item_li = {
        "id": "post_li_1",
        "job": job["id"],
        "clip": "c1",
        "creator": creator["id"],
        "platform": "linkedin",
        "account": "acc_li",
        "account_name": "LinkedIn Page",
        "status": "scheduled",
        "tries": 0,
        "post_at": 1000
    }
    with patch("studio.accounts.linkedin_upload", return_value=("urn:li:ugcPost:67890", "https://www.linkedin.com/feed/update/urn:li:ugcPost:67890")), \
         patch("studio.accounts.get", return_value={"id": "acc_li", "name": "LinkedIn Page", "platform": "linkedin"}):
        posting._post(post_item_li)
        check("posting linkedin sets status to posted", post_item_li["status"], "posted")
        check("posting linkedin sets remote url", post_item_li["url"], "https://www.linkedin.com/feed/update/urn:li:ugcPost:67890")

    post_item_fb = {
        "id": "post_fb_1",
        "job": job["id"],
        "clip": "c1",
        "creator": creator["id"],
        "platform": "facebook",
        "account": "acc_fb",
        "account_name": "FB Page",
        "status": "scheduled",
        "tries": 0,
        "post_at": 1000
    }
    with patch("studio.accounts.facebook_upload", return_value=("fb_vid_123", "https://www.facebook.com/watch/?v=fb_vid_123")), \
         patch("studio.accounts.get", return_value={"id": "acc_fb", "name": "FB Page", "platform": "facebook"}):
        posting._post(post_item_fb)
        check("posting facebook sets status to posted", post_item_fb["status"], "posted")
        check("posting facebook sets remote url", post_item_fb["url"], "https://www.facebook.com/watch/?v=fb_vid_123")

    # 7. Test Direct Connect API for all social platforms
    r_tw = client.post("/api/accounts/direct", json={"platform": "twitter", "name": "@podcastclip", "token": "tw_bearer_123"}, headers=origin)
    check("direct connect twitter returns 200", r_tw.status_code, 200)
    check("direct connect twitter name", r_tw.json()["account"]["name"], "@podcastclip")

    r_li = client.post("/api/accounts/direct", json={"platform": "linkedin", "name": "Tech Founder", "token": "li_tok_123", "extra_id": "urn:li:person:123"}, headers=origin)
    check("direct connect linkedin returns 200", r_li.status_code, 200)

    r_fb = client.post("/api/accounts/direct", json={"platform": "facebook", "name": "Viral Page", "token": "fb_tok_123", "extra_id": "10099"}, headers=origin)
    check("direct connect facebook returns 200", r_fb.status_code, 200)

    # Test 1-Click Fast Connect without token for Instagram and TikTok
    r_ig_fast = client.post("/api/accounts/direct", json={"platform": "instagram", "name": "@gamingguru"}, headers=origin)
    check("1-click fast connect instagram returns 200", r_ig_fast.status_code, 200)
    check("1-click fast connect instagram handle", r_ig_fast.json()["account"]["name"], "@gamingguru")

    r_tt_fast = client.post("/api/accounts/direct", json={"platform": "tiktok", "name": "@tiktokstar"}, headers=origin)
    check("1-click fast connect tiktok returns 200", r_tt_fast.status_code, 200)
    check("1-click fast connect tiktok handle", r_tt_fast.json()["account"]["name"], "@tiktokstar")

    # Verify all accounts returned with URLs by list_accounts
    all_accs = client.get("/api/accounts", headers=origin).json()
    acc_map = {a["platform"]: a for a in all_accs}
    check("accounts list has twitter", "twitter" in acc_map, True)
    check("accounts list has linkedin", "linkedin" in acc_map, True)
    check("accounts list has facebook", "facebook" in acc_map, True)
    check("accounts list has instagram", "instagram" in acc_map, True)
    check("accounts list has tiktok", "tiktok" in acc_map, True)
    check("accounts list has url", bool(acc_map["twitter"].get("url")), True)

    # 8. Test Storage Backup Download (.zip)
    r_backup = client.get("/api/storage/backup", headers=origin)
    check("storage backup returns 200", r_backup.status_code, 200)
    check("storage backup is zip", r_backup.headers.get("content-type"), "application/zip")
    check("storage backup non-empty", len(r_backup.content) > 10, True)

if fails:
    print(f"\n{len(fails)} test(s) failed!")
    sys.exit(1)
else:
    print(f"\nAll social workflow expansion tests passed!")
