#!/bin/bash
# Start the receiver at login and keep it running: a launchd agent on macOS, a systemd user
# service on Linux. Ask your human before running it: it changes what starts at login.
#   receiver/install_service.sh            install (or update) and start it
#   receiver/install_service.sh --remove   stop and remove it
#   receiver/install_service.sh --print    show what it would write; change nothing
# It copies bedside_receiver.py to ~/bedside-sensor/ and runs that copy: on macOS a login
# service may not read ~/Documents, ~/Desktop or ~/Downloads, where this repo often lives.
# Run it again after updating the repo. Log: ~/bedside-sensor/receiver.log
set -euo pipefail
cd "$(dirname "$0")"
MODE=${1:-install}
HOME_DIR="$HOME/bedside-sensor"
SCRIPT="$HOME_DIR/bedside_receiver.py"
LOG="$HOME_DIR/receiver.log"
PORT=7690
OS=${BEDSIDE_OS:-$(uname -s)}
PY=$(command -v python3 || true)
[ -n "$PY" ] || { echo "python3 not found" >&2; exit 1; }

LABEL=local.bedside-sensor.receiver
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UNIT_NAME=bedside-receiver.service
UNIT="$HOME/.config/systemd/user/$UNIT_NAME"

plist() {
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$SCRIPT</string>
    </array>
    <key>WorkingDirectory</key><string>$HOME_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$LOG</string>
    <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
}

unit() {
    cat <<EOF
[Unit]
Description=Bedside sensor receiver
After=network-online.target

[Service]
ExecStart=$PY $SCRIPT
WorkingDirectory=$HOME_DIR
Restart=always
RestartSec=10
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=default.target
EOF
}

wait_healthy() {
    for _ in $(seq 15); do
        if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
            echo "ok receiver answering on port $PORT"
            return 0
        fi
        sleep 1
    done
    echo "receiver did not answer on port $PORT within 15 s; see $LOG" >&2
    return 1
}

case "$OS:$MODE" in
    Darwin:--print) echo "# $PLIST"; plist ;;
    Linux:--print) echo "# $UNIT"; unit ;;
    Darwin:install)
        mkdir -p "$HOME_DIR" "$(dirname "$PLIST")"
        cp bedside_receiver.py "$SCRIPT"
        pkill -f 'bedside_receiver.py' 2>/dev/null || true   # a copy started by hand
        launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
        plist > "$PLIST"
        launchctl bootstrap "gui/$(id -u)" "$PLIST"
        echo "installed launchd agent $LABEL"
        wait_healthy
        ;;
    Linux:install)
        mkdir -p "$HOME_DIR" "$(dirname "$UNIT")"
        cp bedside_receiver.py "$SCRIPT"
        pkill -f 'bedside_receiver.py' 2>/dev/null || true
        unit > "$UNIT"
        systemctl --user daemon-reload
        systemctl --user enable --now "$UNIT_NAME"
        systemctl --user restart "$UNIT_NAME"
        echo "installed systemd user service $UNIT_NAME"
        echo "to keep it running while you are logged out:  sudo loginctl enable-linger $USER"
        wait_healthy
        ;;
    Darwin:--remove)
        launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        echo "removed $LABEL (night files and the token are kept)"
        ;;
    Linux:--remove)
        systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
        rm -f "$UNIT"
        systemctl --user daemon-reload
        echo "removed $UNIT_NAME (night files and the token are kept)"
        ;;
    *)
        sed -n '2,9p' "$(basename "$0")" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
