# Clipsart

**Clipsart turns long videos and live streams into editable, captioned short clips.** Choose your moments, fine tune the video, design a thumbnail from its frames, then queue or publish to your connected channels. It is free and open source and runs on your computer or server.

## Features

- **Multi-Genre AI Clipping**: Specialized clip-scout prompts tailored for **Gaming & Streaming**, **Podcast & Interview**, **Education & Explainer**, and **Business & Finance** content from YouTube, Twitch, Kick, or local video uploads.
- **11 Professional Caption Styles**: Hormozi Gold, Beast Green, Cyberpunk, Karaoke Coral, Minimalist, Bounce, Hype, Clean, Neon Glow, Bold Box, and Cinematic with live visual previews.
- **Auto-Emoji Detection**: Automatically places energetic animated emojis (💰, 🔥, 💀, 🏆, 🤯, 💡, etc.) next to punchline words.
- **Hardware-Accelerated Exports**: Real-time encoder detection supporting NVIDIA NVENC (`h264_nvenc`), Apple Silicon VideoToolbox (`h264_videotoolbox`), Intel QuickSync (`h264_qsv`), and AMD AMF (`h264_amf`) with CPU fallback (`libx264`).
- **Dynamic Audio Ducking & Fades**: Background music automatically dips by ~12 dB during speech using sidechain compression, with dead-air / silence detection.
- **Google Calendar & Content Schedule**: 1-click Google Calendar web event creation plus live `.ics` calendar subscription feed (`/api/calendar/feed.ics`) for Google Calendar, Apple Calendar, and Outlook.
- **Clip Editor & Thumbnail Studio**: Interactive trim slider, hook and copy editor, image overlay, audio volume balance, and frame-accurate thumbnail designer.
- **1-Click Desktop Launchers**: Zero setup desktop scripts (`start-clipsart.bat` on Windows, `start-clipsart.sh` on macOS/Linux) with no mandatory accounts required.
- **Publishing & Workspaces**: Direct posting to YouTube Shorts, Instagram Reels, and TikTok with scheduled queues and multi-creator workspaces.
- Send suggestions and problem reports from the app. Reports are kept in the admin inbox; when SMTP is configured they are also emailed to `support.learnifyai@gmail.com`.
- Support Clipsart's development through [Razorpay](https://razorpay.me/@learnifyaifree).
- Use Gemini, OpenAI, Grok, Groq, OpenRouter, Claude, Ollama or an OpenAI-compatible model. Clipsart also selects moments by loudness when no AI key is set.

## Quick start

You need Python 3.10 or newer and `ffmpeg`. Install ffmpeg with `winget install Gyan.FFmpeg` on Windows, `brew install ffmpeg` on macOS, or `sudo apt install ffmpeg` on Debian or Ubuntu. Clipsart stores videos, models and settings under its data folder and downloads a speech model on first start (about 480 MB).

Clone only your Clipsart repository into a short, permanent folder. Keep it out of temporary directories and assistant workspaces; on Windows, a deeply nested folder can prevent the speech model from loading.

Windows:

Double-click `start-clipsart.bat` (or in PowerShell):

```powershell
git clone https://github.com/Vishwajeetsrk/clipsart.git C:\Clipsart
cd C:\Clipsart
.\start-clipsart.bat
```

macOS or Linux:

```bash
git clone https://github.com/Vishwajeetsrk/clipsart.git ~/Clipsart
cd ~/Clipsart
chmod +x start-clipsart.sh && ./start-clipsart.sh
```

Open <http://127.0.0.1:8765>, go to **Settings → AI**, and save your model key. On a personal computer sign in is off by default. Do not expose the app publicly until you enable accounts and configure HTTPS.

## Configure AI

The dashboard is the easiest place to set an AI provider, key and model. Settings can also go in a private `.env` file, using the `CLIPSART_` prefix documented in [`.env.example`](.env.example). Existing configuration, databases and user media are preserved when updating.

```ini
CLIPSART_AI_PROVIDER=gemini
CLIPSART_AI_MODELS=gemini-2.5-flash
CLIPSART_AI_KEY=your-key-here
```

Get a key from [Google AI Studio](https://aistudio.google.com/apikey), [OpenAI](https://platform.openai.com/api-keys), [xAI](https://console.x.ai), [Groq](https://console.groq.com/keys), [OpenRouter](https://openrouter.ai/keys), or [Anthropic](https://console.anthropic.com). Ollama can run a local model. The provider bills you directly; Clipsart does not add a fee. Speech transcription runs on your computer.

## Suggestion and report email

The app always stores reports and ideas for signed-in users in Clipsart's admin inbox. Email delivery is optional. To send a notification to `support.learnifyai@gmail.com`, configure these `CLIPSART_` settings with an SMTP provider. Keep credentials private in `.env` and do not commit that file.

```ini
CLIPSART_CONTACT_EMAIL=support.learnifyai@gmail.com
CLIPSART_SMTP_HOST=
CLIPSART_SMTP_PORT=587
CLIPSART_SMTP_USER=
CLIPSART_SMTP_PASSWORD=
CLIPSART_MAIL_FROM=Clipsart <hello@your-domain.example>
```

The sender must be an address your provider permits. When SMTP is not configured or sending fails, users can still see that the report was saved; the app does not claim the message was emailed.

## Configure a public server

For a server, set `CLIPSART_ACCOUNTS=1`, configure an HTTPS domain, and follow [DEPLOY.md](DEPLOY.md) for Docker, PostgreSQL and Caddy. Register OAuth callback URLs with the publishing platforms you enable. Clipsart never asks for those platforms' passwords. Account emails, optional Google sign-in, Instagram and TikTok app credentials, storage and upload limits are documented in `.env.example`.

Use `python -m studio.admin grant you@example.com` on the server to grant an account administrator access. The admin page is at `/admin`. User content and settings remain in the data folder; preserve it when upgrading or backing up.

### Use a subdomain such as `clipsart.learnifyai.in`

Add a DNS `A` record with name `clipsart` and the public IPv4 address of the Linux server that will run Clipsart. This creates `clipsart.learnifyai.in` without changing the existing `learnifyai.in` website. If your server has only IPv6, add an `AAAA` record instead; if your hosting provider gives you a hostname, use a `CNAME` record to that hostname. Then set `CLIPSART_DOMAIN=clipsart.learnifyai.in` and `COMPOSE_PROFILES=own-https` in the server's private `.env`, allow inbound ports 80 and 443, and run `docker compose up -d --build`. Caddy obtains and renews HTTPS certificates automatically after DNS points at that server. See [DEPLOY.md](DEPLOY.md).

## Update

From the project folder, run:

```bash
git pull
python -m pip install -r requirements.txt
```

Restart Clipsart after updating. For Docker, run `docker compose up -d --build`. Do not remove your `.env` or data folder.

## Check the commands and tests

```bash
python -m compileall -q studio tests
python tests/run.py
```

The regression runner starts the app against isolated temporary data. It requires no live publishing credentials and should never be run with your personal data as a test fixture.

## Project map

- `studio/` contains the FastAPI service and media pipeline.
- `web/` contains the app, landing, authentication and admin pages and brand files.
- `tests/` contains the regression suite.
- `deploy/`, `Dockerfile` and `docker-compose.yml` contain server deployment files.
- [PRD.md](PRD.md) lists product requirements, [TASKS.md](TASKS.md) tracks delivery, and [GLOBAL_RULES.md](GLOBAL_RULES.md) describes repository rules.

## Rights and safety

Only clip and publish videos, music and artwork you have created or have permission to reuse. Imported music is not assumed to be copyright free; retain its licence and attribution. Review AI-selected moments, captions, thumbnails and post copy before publishing. Respect the terms of each source and publishing platform.

## License

[MIT](LICENSE). Caption fonts under `studio/fonts/` are licensed under the SIL Open Font License; their license texts are in that folder.
