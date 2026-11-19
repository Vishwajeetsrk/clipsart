# Clipsart

**Clipsart turns long videos and live streams into editable, captioned short clips.** Choose your moments, fine tune the video, design a thumbnail from its frames, then queue or publish to your connected channels. It is free and open source and runs on your computer or server.

## Features

- Find highlights in YouTube, Twitch and Kick videos, live streams, or uploaded video files with AI suggestions and speech transcription.
- Make vertical clips with word-by-word captions in Bounce, Hype and Clean styles. Choose blurred fill, zoom, centre crop or gameplay with facecam.
- Refine clips with a trim timeline, hook and post text editor, music mix controls, image overlay and fast preview rendering.
- Design a thumbnail from a video frame, add title text or a custom image, preview it, and save or restore the cover.
- Connect YouTube, Instagram and TikTok, prepare post titles and descriptions, schedule a post for a chosen time, or use the existing automatic queue.
- Organize creators, channels, clips, publishing rules and activity in separate workspaces.
- Send suggestions and problem reports from the app. Reports are kept in the admin inbox; when SMTP is configured they are also emailed to `support.learnifyai@gmail.com`.
- Support Clipsart's development through [Razorpay](https://razorpay.me/@learnifyaifree).
- Use Gemini, OpenAI, Grok, Groq, OpenRouter, Claude, Ollama or an OpenAI-compatible model. Clipsart also selects moments by loudness when no AI key is set.

## Quick start

You need Python 3.10 or newer and `ffmpeg`. Install ffmpeg with `winget install Gyan.FFmpeg` on Windows, `brew install ffmpeg` on macOS, or `sudo apt install ffmpeg` on Debian or Ubuntu. Clipsart stores videos, models and settings under its data folder and downloads a speech model on first start (about 480 MB).

Clone only your Clipsart repository into a short, permanent folder. Keep it out of temporary directories and assistant workspaces; on Windows, a deeply nested folder can prevent the speech model from loading.

Windows PowerShell:

```powershell
git clone https://github.com/Vishwajeetsrk/clipsart.git C:\Clipsart
cd C:\Clipsart
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m studio.server
```

macOS or Linux:

```bash
git clone https://github.com/Vishwajeetsrk/clipsart.git ~/Clipsart
cd ~/Clipsart
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m studio.server
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
