#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  Starting Clipsart Video Studio..."
echo "============================================================"
echo ""

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Please install Python 3.10 or newer."
    exit 1
fi

# 2. Check FFmpeg
if ! command -v ffmpeg &>/dev/null; then
    if [ ! -f "./bin/ffmpeg" ]; then
        echo "[NOTICE] FFmpeg was not detected in PATH."
        echo "Install via: brew install ffmpeg (macOS) or sudo apt install ffmpeg (Linux)"
        echo ""
    else
        export PATH="$(pwd)/bin:$PATH"
    fi
fi

# 3. Setup Virtual Environment
if [ ! -d ".venv" ]; then
    echo "[1/3] Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# 4. Check Dependencies
if [ ! -f ".venv/.installed" ]; then
    echo "[2/3] Installing / updating required packages..."
    pip install -q -r requirements.txt
    touch .venv/.installed
fi

# 5. Launch Studio Server & Open Browser
echo "[3/3] Launching Clipsart Studio on http://127.0.0.1:8765/app ..."

if command -v open &>/dev/null; then
    (sleep 2 && open http://127.0.0.1:8765/app) &
elif command -v xdg-open &>/dev/null; then
    (sleep 2 && xdg-open http://127.0.0.1:8765/app) &
fi

python3 -m studio.server
