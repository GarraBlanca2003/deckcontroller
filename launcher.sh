#!/bin/bash

REPO_URL="https://github.com/GarraBlanca2003/deckcontroller"
BASE_DIR="/home/deck/programs"
CLONE_DIR="$BASE_DIR/deckcontroller"
BRANCH="main"
SCRIPT="$CLONE_DIR/sender.py"
VENV_DIR="$CLONE_DIR/.venv"
REQUIREMENTS="$CLONE_DIR/requirements.txt"
LAUNCHER="$CLONE_DIR/launcher.sh"

mkdir -p "$BASE_DIR"

if [ ! -d "$CLONE_DIR/.git" ]; then
    echo "[INFO] Cloning repository into $CLONE_DIR..."
    git clone --branch "$BRANCH" "$REPO_URL" "$CLONE_DIR" || {
        echo "[ERROR] Failed to clone repository."
        exit 1
    }
fi
cd "$CLONE_DIR" || {
    echo "[ERROR] Failed to cd into $CLONE_DIR."
    exit 1
}

echo "[INFO] Fetching latest changes..."
git fetch origin "$BRANCH"

LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse origin/$BRANCH)
BASE=$(git merge-base @ origin/$BRANCH)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[INFO] Program up to date."
elif [ "$LOCAL" = "$BASE" ]; then
    git pull origin "$BRANCH" || {
        echo "[ERROR] Failed to pull changes."
        exit 1
    }
elif [ "$REMOTE" = "$BASE" ]; then
    exit 1
else
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv "$VENV_DIR" || {
        exit 1
    }
fi

if [ -f "$REQUIREMENTS" ]; then
    echo "[INFO] Installing dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS" || {
        exit 1
    }
fi

if [ -f "$SCRIPT" ]; then
    chmod +x "$LAUNCHER"
    "$VENV_DIR/bin/python" "$SCRIPT"
else
    exit 1
fi
