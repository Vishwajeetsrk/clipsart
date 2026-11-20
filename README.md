# Clipsart

**Clipsart turns long videos and live streams into editable, captioned short clips.**
Choose your moments, fine-tune the video in 4K or 1080p, design thumbnails from frames, and publish directly to connected channels or via 1-click web shortcuts. It is 100% free, open source, and runs locally on your computer or private server.

---

## ⚡ Quick Start

### Prerequisites
- **Python 3.10 or newer**: [Download Python](https://www.python.org/downloads/) *(ensure "Add Python to PATH" is checked during setup)*.
- **FFmpeg**:
  - **Windows**: `winget install Gyan.FFmpeg`
  - **macOS**: `brew install ffmpeg`
  - **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install ffmpeg`

Clipsart downloads a local offline speech model on first run (~480 MB) stored in `data/models/`. No third-party accounts or cloud APIs are required to run locally.

---

### Windows (1-Click Run)

Simply double-click **`start-clipsart.bat`** in the repository root folder, or run in PowerShell:

```powershell
# 1. Clone the repository
git clone https://github.com/Vishwajeetsrk/clipsart.git C:\Clipsart
cd C:\Clipsart

# 2. Launch with the automated starter
.\start-clipsart.bat
```

The script will automatically set up the virtual environment (`.venv`), install dependencies, launch the server, and open your browser at **`http://127.0.0.1:8765/app`**.

---

### macOS & Linux (1-Click Run)

Open Terminal and execute:

```bash
# 1. Clone the repository
git clone https://github.com/Vishwajeetsrk/clipsart.git ~/Clipsart
cd ~/Clipsart

# 2. Make executable and run
chmod +x start-clipsart.sh
./start-clipsart.sh
```

---

### Manual Setup & Commands (PowerShell / Bash)

If you prefer running commands manually:

```bash
# 1. Create a Python virtual environment
python -m venv .venv

# 2. Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (Command Prompt):
.\.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Start the Clipsart server
python -m studio.server
```

Once running, navigate to:
👉 **`http://127.0.0.1:8765/app`** (or `http://localhost:8765/app`)

---

## 🧪 Testing & Verification Commands

Clipsart includes a comprehensive automated regression suite covering speech models, AI providers, media rendering, caption overlapping, facecam detection, and social media integrations:

```bash
# Verify Python syntax and bytecode compilation across all modules
python -m compileall -q studio tests

# Run the complete test suite (all modules)
python tests/run.py

# Run individual test suites
python -m unittest tests/test_social_workflow_expansion.py
python -m unittest tests/test_render_audio.py
python -m unittest tests/test_connect.py
python -m unittest tests/test_stuck.py
python -m unittest tests/test_facecam.py
```

*Note: The regression runner executes against isolated temporary directories and never alters your saved clips, database, or credentials.*

---

## 🚀 Key Features & Capabilities

### 1. Multi-Genre AI Moment Clipping
- Tailored prompts for **Gaming & Streaming**, **Podcast & Interview**, **Education & Explainer**, and **Business & Finance**.
- URL ingestion from **YouTube**, **Twitch**, and **Kick** via `yt-dlp`.
- Multi-GB local video file uploads with resumable chunked uploading.
- Automatic **Audio Loudness Peak Fallback**: If no AI API key is configured, Clipsart uses root-mean-square (RMS) acoustic energy and silence detection to extract high-energy highlights.

### 2. 4K Ultra HD & Hardware-Accelerated Video Rendering
- **Export Resolutions**:
  - **✨ 4K Ultra HD** (`2160×3840` vertical, 22 Mbps high-bitrate encoding / CRF 18).
  - **1080p Full HD** (`1080×1920`, 6 Mbps).
  - **720p HD** (`720×1280`, 3.5 Mbps).
- **Hardware Acceleration**: Auto-detects NVIDIA NVENC (`h264_nvenc`), Apple Silicon VideoToolbox (`h264_videotoolbox`), Intel QuickSync (`h264_qsv`), and AMD AMF (`h264_amf`) with CPU fallback (`libx264`).
- **Dynamic Audio Ducking**: Background music automatically dips by ~12 dB during speech using sidechain compression and smoothly fades out.

### 3. Professional NLE Video Editor & 11 Caption Styles
- **11 Typography Styles**: Hormozi Gold, Beast Green, Cyberpunk, Karaoke Coral, Minimalist, Bounce, Hype, Clean, Neon Glow, Bold Box, and Cinematic.
- **Auto-Emoji Detection**: Contextually places animated emojis (🔥, 💀, 💰, 🏆, 🤯, 💡) on punchlines.
- **Romanization**: Converts Hindi and Urdu speech into clean Roman letters (Hinglish).
- **NLE Keyboard Shortcuts**:
  - <kbd>Space</kbd> / <kbd>K</kbd>: Play / Pause
  - <kbd>I</kbd>: Mark In point at playhead
  - <kbd>O</kbd>: Mark Out point at playhead
  - <kbd>←</kbd> / <kbd>→</kbd> or <kbd>J</kbd> / <kbd>L</kbd>: Seek frame (±1.0s or ±0.2s with <kbd>Shift</kbd>)
- **Real-Time Frame Scrubbing**: Adjusting the Out point automatically scrubs to the exact closing frame.

### 4. Thumbnail Studio
- Capture full-resolution video frames at exact timestamps.
- Customize title text with Bold, Clean, or Neon glowing styles.
- Save custom thumbnails or restore AI-generated covers anytime.

### 5. Dual-Mode Social Media Publishing
Clipsart supports two publishing workflows to accommodate both solo creators and production agencies:

| Platform | 1-Click Direct Web Publish (No API App Needed) | Automated Background API Upload |
| :--- | :--- | :--- |
| **YouTube Shorts** | ✅ Copies title/caption, downloads MP4, opens YouTube Studio | ✅ Resumable OAuth 2.0 Upload API |
| **Instagram Reels** | ✅ Copies caption & tags, downloads MP4, opens Instagram Create | ✅ Meta Graph API Reels Upload |
| **TikTok** | ✅ Copies caption & tags, downloads MP4, opens TikTok Studio | ✅ Content Posting API / Direct Post |
| **Facebook Reels** | ✅ Copies caption & tags, downloads MP4, opens Facebook Reels | ✅ Meta Graph API Page Video Reels |
| **X (Twitter)** | ✅ Pre-fills tweet composer with hook and hashtags | ✅ v1.1 Media Chunked Upload + v2 Tweet |
| **LinkedIn Video** | ✅ Pre-fills post draft with summary and hashtags | ✅ UGC Video Upload API |

### 6. Workflow & Community Integrations
- **Discord & Telegram Drops**: Instant 1-click or automated MP4 clip drops and webhook notifications to your community channels.
- **Notion Kanban Sync**: Syncs video titles, hooks, tags, AI scores, and publishing status into a Notion database board.
- **Cloud Storage Backup**: Automatic local export into Google Drive, Dropbox, or OneDrive sync folders.
- **Content Scheduling & Calendar**:
  - Automated scheduling queue respecting daily post limits and minimum time gaps.
  - Live `.ics` calendar subscription feed (`/api/calendar/feed.ics`) compatible with Google Calendar, Apple Calendar, and Microsoft Outlook.
  - 1-click Google Calendar reminder creation.

---

## ⚙️ Configuration & Environment Variables

Settings can be saved directly in the web dashboard (**Settings → AI**, **Settings → Connected apps**) or defined in a `.env` file using the `CLIPSART_` prefix (see [`.env.example`](.env.example)).

```ini
# AI Provider Configuration
CLIPSART_AI_PROVIDER=gemini
CLIPSART_AI_MODELS=gemini-2.5-flash
CLIPSART_AI_KEY=your-api-key-here

# Public Address (Required for Meta / Instagram OAuth webhook callbacks)
CLIPSART_PUBLIC_URL=http://127.0.0.1:8765

# Multi-User Accounts & Security (0 for local personal mode, 1 for public server)
CLIPSART_ACCOUNTS=0
CLIPSART_STORAGE_LIMIT_GB=100

# Optional SMTP Notifications
CLIPSART_CONTACT_EMAIL=support.learnifyai@gmail.com
CLIPSART_SMTP_HOST=smtp.gmail.com
CLIPSART_SMTP_PORT=587
CLIPSART_SMTP_USER=your-email@gmail.com
CLIPSART_SMTP_PASSWORD=your-app-password
CLIPSART_MAIL_FROM=Clipsart <hello@your-domain.example>
```

Supported AI providers:
- **Google Gemini**: [Google AI Studio](https://aistudio.google.com/apikey) (`gemini-2.5-flash`, `gemini-1.5-pro`)
- **OpenAI**: [OpenAI Platform](https://platform.openai.com/api-keys) (`gpt-4o`, `gpt-4o-mini`)
- **Groq**: [Groq Console](https://console.groq.com/keys) (`llama-3.3-70b-versatile`)
- **Anthropic**: [Anthropic Console](https://console.anthropic.com) (`claude-3-5-sonnet`)
- **xAI**: [xAI Console](https://console.x.ai) (`grok-beta`)
- **OpenRouter**: [OpenRouter](https://openrouter.ai/keys)
- **Ollama**: Local offline LLM models (`http://localhost:11434`)

---

## 🌐 Production Server & Docker Deployment

To deploy Clipsart on a VPS or cloud instance with automated HTTPS (via Caddy) and PostgreSQL:

```bash
# 1. Configure production environment
cp .env.example .env
nano .env

# Set CLIPSART_ACCOUNTS=1, CLIPSART_DOMAIN=clips.yourdomain.com, COMPOSE_PROFILES=own-https

# 2. Launch with Docker Compose
docker compose up -d --build

# 3. Grant Administrator access to your account
docker compose exec studio python -m studio.admin grant you@yourdomain.com
```

Refer to [`DEPLOY.md`](DEPLOY.md) for full Nginx, Caddy, subdomain DNS, and systemd service instructions.

---

## 📂 Project Architecture

```
Clipsart/
├── start-clipsart.bat    # Windows 1-click desktop launcher
├── start-clipsart.sh     # macOS / Linux 1-click launcher
├── requirements.txt      # Core Python dependencies
├── studio/               # Backend media engine & FastAPI server
│   ├── server.py         # REST & WebSocket API endpoints
│   ├── render.py         # FFmpeg filtergraphs, 4K rendering, ASS subtitles, ducking
│   ├── transcribe.py     # Local offline speech-to-text (sherpa-onnx)
│   ├── brain.py          # AI moment detection & multi-genre prompts
│   ├── accounts.py       # Social media OAuth & upload APIs (YT, IG, TT, FB, X, LI)
│   ├── posting.py        # Post queue, calendar feeds, auto-mirroring
│   ├── facecam.py        # OpenCV face and motion tracker for gaming streams
│   ├── notion.py         # Notion Kanban database synchronization
│   ├── alerts.py         # Discord & Telegram community drops
│   └── cloud_sync.py     # Local cloud folder export (Drive / Dropbox)
├── web/                  # Responsive web application
│   ├── index.html        # Single-page studio interface & video editor
│   ├── brand/            # Official vector logos and icons
│   └── assets/           # Typography, styles, and animation helpers
└── tests/                # Automated regression test suite
    └── run.py            # Primary test runner
```

---

## 📄 License & Attribution

- **License**: [MIT License](LICENSE).
- **Fonts**: Caption fonts located in `studio/fonts/` are licensed under the SIL Open Font License.
- **Safety**: Only process, edit, and publish videos, music, and media you own or have explicit authorization to redistribute.
