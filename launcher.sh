#!/bin/bash
REPO_URL="https://github.com/GarraBlanca2003/deckcontroller"
BASE_DIR="/home/deck/programs"
CLONE_DIR="$BASE_DIR/deckcontroller"
BRANCH="main"
SCRIPT="$CLONE_DIR/sender.py"
VENV_DIR="$CLONE_DIR/.venv"
REQUIREMENTS="$CLONE_DIR/requirements.txt"
LAUNCHER_SH="$CLONE_DIR/launcher.sh"
FIRST_RUN_FLAG="$CLONE_DIR/.first_run_done"
STEAM_USERDATA_DIR="$HOME/.local/share/Steam/userdata"

mkdir -p "$BASE_DIR"

FIRST_RUN=false

if [ ! -d "$STEAM_USERDATA_DIR" ]; then
    echo "Steam userdata directory not found!"
    exit 1
fi

if [ ! -d "$CLONE_DIR/.git" ]; then
    rm -rf $CLONE_DIR
    echo "[INFO] Cloning repository into $CLONE_DIR..."
    git clone --branch "$BRANCH" "$REPO_URL" "$CLONE_DIR" || {
        echo "[ERROR] Failed to clone repository."
        exit 1
    }
    FIRST_RUN=true
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
    echo "[INFO] Repository is up to date."
elif [ "$LOCAL" = "$BASE" ]; then
    echo "[INFO] Pulling latest changes from origin/$BRANCH..."
    git pull origin "$BRANCH" || {
        echo "[ERROR] Failed to pull changes."
        exit 1
    }
elif [ "$REMOTE" = "$BASE" ]; then
    echo "[WARNING] Local changes not pushed. Aborting."
    exit 1
else
    echo "[ERROR] Repository has diverged. Manual intervention needed."
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv "$VENV_DIR" || {
        echo "[ERROR] Failed to create virtual environment."
        exit 1
    }
fi

if [ -f "$REQUIREMENTS" ]; then
    echo "[INFO] Installing dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS" || {
        echo "[ERROR] Failed to install requirements."
        exit 1
    }
else
    echo "[WARNING] No requirements.txt found. Skipping dependency installation."
fi

if [ "$FIRST_RUN" = true ]; then
    if [ -f "$LAUNCHER_SH" ]; then
        for USER_ID in "$STEAM_USERDATA_DIR"/*; do
        echo "[INFO] adding art for $USER_ID"
            GRID_DIR="$USER_ID/config/grid"
            mkdir -p "$GRID_DIR"
        echo "Installing artwork to $GRID_DIR"
        cp "$BASE_DIR/deckcontroller/image/hero.png" "$GRID_DIR/${APP_DESKTOP_NAME}_hero.png"
        cp "$BASE_DIR/deckcontroller/image/logo.png" "$GRID_DIR/${APP_DESKTOP_NAME}_logo.png"
        cp "$BASE_DIR/deckcontroller/image/library_hero.png" "$GRID_DIR/${APP_DESKTOP_NAME}_library_hero.png"
        cp "$BASE_DIR/deckcontroller/image/library_cover.png" "$GRID_DIR/${APP_DESKTOP_NAME}_library_cover.png"
        cp "$BASE_DIR/deckcontroller/image/icon.png" "$GRID_DIR/${APP_DESKTOP_NAME}_icon.png"
        cp "$BASE_DIR/deckcontroller/image/grid.png" "$GRID_DIR/${APP_DESKTOP_NAME}_grid.png"
    done
    echo "✅ Art installed"
    echo "[INFO] First time setup: making launcher.sh executable..."

        chmod +x "$LAUNCHER_SH"
        steamos-add-to-steam $BASE_DIR/deckcontroller/deckcontroller.desktop
        echo "[INFO] Done. Not launching Python script on first run."
    else
        echo "[WARNING] launcher.sh not found at $LAUNCHER_SH."
    fi
    touch "$FIRST_RUN_FLAG"
    exit 0
fi

if [ -f "$SCRIPT" ]; then
    echo "[INFO] Launching sender.py..."
    "$VENV_DIR/bin/python" "$SCRIPT"
else
    echo "[ERROR] sender.py not found at $SCRIPT."
    exit 1
fi