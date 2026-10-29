#!/usr/bin/env bash
set -e

export DISPLAY=:99
export SCREEN_RES="1024x768x24"

echo "[*] Initializing IntelliCodeX Virtual Display & GUI Preview Environment..."

# Clean up any stale X locks
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

# 1. Start Xvfb (Virtual Framebuffer)
echo "[*] Starting Xvfb on display :99 (${SCREEN_RES})..."
Xvfb :99 -screen 0 ${SCREEN_RES} -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Wait for X display socket to become ready
for i in {1..50}; do
    if [ -S /tmp/.X11-unix/X99 ]; then
        echo "[+] Virtual display :99 socket is ready."
        break
    fi
    sleep 0.1
done

# 2. Start Openbox Window Manager (handles window placement, borders, and input focus)
echo "[*] Starting Openbox window manager..."
openbox &
WM_PID=$!

# 3. Start x11vnc server (attached to :99, listening on localhost only)
echo "[*] Starting x11vnc server on port 5900..."
x11vnc -display :99 -forever -shared -rfbport 5900 -nopw -listen 127.0.0.1 -bg -xkb -quiet
X11VNC_PID=$!

# 4. Start websockify for noVNC (serves HTML5 VNC client on port 6080)
echo "[*] Starting noVNC websockify bridge on port 6080..."
websockify --web /usr/share/novnc 6080 127.0.0.1:5900 &
WEBSOCKIFY_PID=$!

cleanup() {
    echo -e "\n[*] Shutting down GUI preview services..."
    [ -n "$APP_PID" ] && kill -TERM "$APP_PID" 2>/dev/null || true
    [ -n "$WEBSOCKIFY_PID" ] && kill -TERM "$WEBSOCKIFY_PID" 2>/dev/null || true
    [ -n "$WM_PID" ] && kill -TERM "$WM_PID" 2>/dev/null || true
    [ -n "$XVFB_PID" ] && kill -TERM "$XVFB_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

TARGET="${TARGET_FILE:-TodoApp.java}"
TARGET_PATH="/work/${TARGET}"

echo "[*] Compiling and launching graphical target: ${TARGET_PATH}..."
mkdir -p /tmp/build_classes
if [[ "$TARGET" == *.java ]]; then
    javac -encoding UTF-8 -d /tmp/build_classes "$TARGET_PATH"
    CLASSNAME=$(basename "$TARGET" .java)
    echo "[+] Launching Java Swing Application: ${CLASSNAME}..."
    java -cp /tmp/build_classes -Djava.awt.headless=false "$CLASSNAME" &
    APP_PID=$!
elif [ -n "$*" ]; then
    "$@" &
    APP_PID=$!
else
    echo "[!] Unrecognized target format: ${TARGET}"
    exit 1
fi

echo "=========================================================================="
echo "  INTELLICODEX GUI PREVIEW IS ACTIVE (noVNC Virtual Display)"
echo "  Local Web URL: http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale"
echo "=========================================================================="

# Keep alive while background app is running
wait $APP_PID
