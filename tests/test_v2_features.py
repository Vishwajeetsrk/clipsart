"""Unit and integration tests for V2 features:
- Sound Effects (SFX) synthesis and mixing
- Speaker Diarization and Multi-Color Subtitles
- Multimodal Vision Scene Analysis
- Cross-Platform Analytics Tracking
- Progressive Web App (PWA) Manifest and Service Worker
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check(name, condition):
    if not condition:
        raise AssertionError(f"Check failed: {name}")
    print(f"PASS {name}")


def main():
    tmp_dir = Path(tempfile.mkdtemp(prefix="v2_test_"))
    os.environ.update(CLIPSART_DATA=str(tmp_dir), DATABASE_URL="", CLIPSART_ACCOUNTS="0")

    try:
        from studio import analytics, db, diarize, render, server, sfx, vision
        from fastapi.testclient import TestClient
        db.init()

        # -------------------------------------------------------------
        # 1. SFX Synthesis & Mix Track
        # -------------------------------------------------------------
        sfx_dir = tmp_dir / "sfx"
        lib = sfx.synthesize_sfx_library(sfx_dir)
        check("sfx library created 4 core sound effects", len(lib) == 4 and all(Path(p).is_file() for p in lib.values()))
        check("sfx files have valid content", all(Path(p).stat().st_size > 500 for p in lib.values()))

        words = [
            {"w": "Look", "s": 0.5, "e": 0.8},
            {"w": "at", "s": 0.9, "e": 1.1},
            {"w": "this", "s": 1.2, "e": 1.5},
            {"w": "🔥", "s": 2.0, "e": 2.2},
            {"w": "amazing", "s": 3.0, "e": 3.5},
            {"w": "shot!", "s": 4.0, "e": 4.5}
        ]
        events = sfx.plan_sfx_events(words, "WAIT FOR IT", duration=6.0)
        check("sfx planner scheduled hook and punchline events", len(events) >= 2)

        out_wav = tmp_dir / "sfx_track.wav"
        track_ok = sfx.generate_sfx_track(events, 6.0, out_wav)
        check("sfx track generated", track_ok and out_wav.is_file() and out_wav.stat().st_size > 1000)

        # -------------------------------------------------------------
        # 2. Speaker Diarization
        # -------------------------------------------------------------
        conv_words = [
            {"w": "Hey", "s": 0.0, "e": 0.4},
            {"w": "welcome", "s": 0.5, "e": 0.9},
            {"w": "everybody", "s": 1.0, "e": 1.4},
            {"w": "Thanks", "s": 2.2, "e": 2.6},
            {"w": "for", "s": 2.7, "e": 2.9},
            {"w": "having", "s": 3.0, "e": 3.3},
            {"w": "me", "s": 3.4, "e": 3.6},
            {"w": "Glad", "s": 4.5, "e": 4.8},
            {"w": "you're", "s": 4.9, "e": 5.1},
            {"w": "here", "s": 5.2, "e": 5.5}
        ]
        diarized = diarize.diarize_words(conv_words)
        check("diarization assigns speaker ids to all words", len(diarized) == len(conv_words) and all("speaker" in w for w in diarized))
        spk_ids = {w["speaker"] for w in diarized}
        check("diarization identifies multiple speakers across pauses", len(spk_ids) >= 2)
        check("first turn belongs to speaker 1", diarized[0]["speaker"] == 1)
        check("second turn after pause belongs to speaker 2", diarized[3]["speaker"] == 2)

        # -------------------------------------------------------------
        # 3. Multi-Speaker ASS Subtitles
        # -------------------------------------------------------------
        ass_text = render.build_ass(diarized, 0.0, 6.0, "PODCAST MOMENT", "bounce", [], 200, 1500, multi_speaker=True)
        check("ass subtitles contain speaker 2 cyan styling (&HFFFF00&)", "&HFFFF00&" in ass_text)
        check("ass subtitles contain dialogue events for both speakers", "Dialogue: " in ass_text)

        # -------------------------------------------------------------
        # 4. Multimodal Vision Scene Analysis
        # -------------------------------------------------------------
        # Test fallback analysis when no video or synthetic frame
        v_res = vision.analyze_scene(tmp_dir / "nonexistent.mp4", 0.0, 5.0)
        check("vision fallback provides valid visual_energy", 0 <= v_res.get("visual_energy", -1) <= 100)
        check("vision fallback provides valid expression and tags", "expression" in v_res and "action_tags" in v_res)

        # -------------------------------------------------------------
        # 5. Analytics Engine & History Storage
        # -------------------------------------------------------------
        summary = analytics.summary()
        check("analytics summary structure", isinstance(summary, dict) and "total_views" in summary and "platforms" in summary)
        check("analytics platform breakdown includes core channels", all(p in summary["platforms"] for p in ("youtube", "instagram", "tiktok")))
        ref = analytics.refresh()
        check("analytics refresh returns updated summary", isinstance(ref, dict) and "history" in ref)

        # -------------------------------------------------------------
        # 6. Server Endpoints & PWA Assets
        # -------------------------------------------------------------
        client = TestClient(server.app, base_url="http://127.0.0.1:8765")

        # PWA Manifest
        res_m = client.get("/manifest.json")
        check("pwa manifest.json endpoint responds 200", res_m.status_code == 200)
        m_data = res_m.json()
        check("pwa manifest contains name and start_url", m_data.get("name") == "Clipsart" and m_data.get("start_url") == "/app")

        # PWA Service Worker
        res_sw = client.get("/sw.js")
        check("pwa service worker responds 200", res_sw.status_code == 200 and "Service-Worker-Allowed" in res_sw.headers)
        check("pwa service worker contains cache logic", "clipsart-shell" in res_sw.text)

        # Analytics API
        res_an = client.get("/api/analytics")
        check("api/analytics responds 200", res_an.status_code == 200 and "platforms" in res_an.json())

        res_ref = client.post("/api/analytics/refresh")
        check("api/analytics/refresh responds 200", res_ref.status_code == 200 and "total_views" in res_ref.json())

        # Cloud Sync Test API
        cloud_folder = tmp_dir / "cloud_drive"
        cloud_folder.mkdir(parents=True, exist_ok=True)
        res_put = client.put("/api/settings", json={"cloud_sync_folder": str(cloud_folder)})
        check("api/settings updates cloud_sync_folder", res_put.status_code == 200 and res_put.json().get("cloud_sync_folder") == str(cloud_folder))
        res_cloud = client.post("/api/cloud-sync/test")
        check("api/cloud-sync/test responds 200", res_cloud.status_code == 200 and "writable" in res_cloud.json().get("message", "").lower())

        # -------------------------------------------------------------
        # 7. Connected Apps (Instagram, Pinterest, Threads, Active/Expired/Removed)
        # -------------------------------------------------------------
        from studio import accounts
        # Direct Connect Pinterest
        pin_res = client.post("/api/accounts/direct", json={"platform": "pinterest", "name": "Pinterest-IG", "token": "web", "extra_id": "board_art"})
        check("api/accounts/direct connects Pinterest", pin_res.status_code == 200 and pin_res.json().get("ok"))
        pin_id = pin_res.json()["account"]["id"]

        # Direct Connect Threads with Threads App ID
        th_res = client.post("/api/accounts/direct", json={"platform": "threads", "name": "@clipsart_hq", "token": "web", "extra_id": "104829104810293"})
        check("api/accounts/direct connects Threads with App ID", th_res.status_code == 200 and th_res.json().get("ok"))
        th_id = th_res.json()["account"]["id"]
        check("threads account records app_id", th_res.json()["account"].get("app_id") == "104829104810293")

        # Verify Threads OAuth App configuration in /api/apps
        apps_res = client.get("/api/apps")
        check("api/apps includes threads configuration", apps_res.status_code == 200 and "threads" in apps_res.json())
        th_cfg = apps_res.json()["threads"]
        check("threads app id label is correct", th_cfg.get("id_label") == "Threads app ID")
        check("threads redirect uri contains oauth/threads/callback", "/oauth/threads/callback" in th_cfg.get("redirect", ""))

        # Save Threads App ID and Secret via PUT /api/apps
        save_app_res = client.put("/api/apps", json={"platform": "threads", "client_id": "104829104810293", "client_secret": "threads_secret_key_123"})
        check("api/apps saves Threads app ID & secret", save_app_res.status_code == 200 and save_app_res.json().get("threads", {}).get("ready") is True)

        # Check OAuth authorization URL generation
        th_auth_url = accounts.connect_url("threads")
        check("threads connect_url generates valid authorization link", "threads.net/oauth/authorize" in th_auth_url and "client_id=104829104810293" in th_auth_url)

        # List accounts with status and permissions
        accs_res = client.get("/api/accounts")
        check("api/accounts lists accounts", accs_res.status_code == 200)
        acc_list = accs_res.json()
        pin_acc = next((a for a in acc_list if a["id"] == pin_id), None)
        check("pinterest account has permissions list", pin_acc and len(pin_acc.get("permissions", [])) >= 2)
        check("account has active status", pin_acc and pin_acc.get("status") == "active")

        # Test account connection endpoint
        test_res = client.post(f"/api/accounts/{pin_id}/test")
        check("api/accounts/{id}/test verifies connection", test_res.status_code == 200 and test_res.json().get("ok"))

        # Remove account (moves to removed list)
        del_res = client.delete(f"/api/accounts/{pin_id}")
        check("api/accounts/{id} removes account", del_res.status_code == 200 and del_res.json().get("ok"))

        # Verify in removed accounts list
        rem_res = client.get("/api/accounts/removed")
        check("api/accounts/removed returns removed account", rem_res.status_code == 200 and any(a["id"] == pin_id for a in rem_res.json()))

        # Restore account
        rest_res = client.post(f"/api/accounts/{pin_id}/restore")
        check("api/accounts/{id}/restore restores account to active", rest_res.status_code == 200 and rest_res.json().get("ok"))

        accs_res2 = client.get("/api/accounts")
        check("restored account is active in accounts list", any(a["id"] == pin_id for a in accs_res2.json()))

        # Test AI providers and brand logo frontend assets
        ai_res = client.get("/api/ai")
        check("api/ai responds 200", ai_res.status_code == 200)
        ai_data = ai_res.json()
        prov_ids = [p["id"] for p in ai_data.get("providers", [])]
        expected_provs = ["gemini", "openai", "xai", "groq", "openrouter", "anthropic", "ollama", "custom"]
        check("api/ai includes all 8 core providers", all(p in prov_ids for p in expected_provs))

        # Check frontend index.html integration
        with open("web/index.html", "r", encoding="utf-8") as f:
            html = f.read()
        check("index.html links devicon stylesheet", "devicon.min.css" in html)
        check("index.html brandLogo supports gemini", "gemini" in html and "gem-g-" in html)
        check("index.html brandLogo supports openai", "OpenAI" in html and "10A37F" in html)
        check("index.html brandLogo supports anthropic claude", "Anthropic Claude" in html and "D97757" in html)
        check("index.html brandLogo supports grok xai", "xAI Grok" in html)
        check("index.html brandLogo supports groq", "Groq" in html and "F55036" in html)
        check("index.html brandLogo supports openrouter", "OpenRouter" in html and "6366F1" in html)
        check("index.html brandLogo supports ollama", "Ollama" in html)
        check("index.html brandLogo supports custom", "Custom AI" in html)

        print("\nAll V2 feature tests completed successfully!")
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
