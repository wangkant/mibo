#!/usr/bin/env bash
# Runs one check in WSL on a virtual screen of its own, so that no window reaches the Windows desktop through WSLg.
#
#   wsl -d Ubuntu-24.04 -- bash tools/xplat/wsl_run.sh python tools/window_smoke.py
#
# It starts Xvfb on the first free display from :99 up, with openbox and a session bus of its own, sets DISPLAY to
# it with WAYLAND_DISPLAY unset (and Qt and GTK held to X11), checks that the screen is its own virtual one, and
# runs the command from the checkout
# with the venv in MIBO_XPLAT_VENV (default ~/.cache/mibo-xplat/venv), into which the checkout is installed with
# the extras in MIBO_XPLAT_EXTRAS (default app,dev). It needs xvfb, openbox, dbus-x11 and xdotool from apt.
# While the check runs it counts the windows on that screen; the last lines say how many and the check's exit status,
# which is also this script's.
set -uo pipefail

SIZE="1280 900"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${MIBO_XPLAT_VENV:-$HOME/.cache/mibo-xplat/venv}"
EXTRAS="${MIBO_XPLAT_EXTRAS:-app,dev}"

if [ $# -eq 0 ]; then
  echo "usage: wsl_run.sh COMMAND [ARGS...]" >&2
  exit 2
fi
for tool in Xvfb openbox dbus-run-session xdotool python3; do
  command -v "$tool" >/dev/null || { echo "missing: $tool (apt install xvfb openbox dbus-x11 xdotool)" >&2; exit 2; }
done

# WSLg's own screen and compositor are never used.
unset WAYLAND_DISPLAY DISPLAY
export QT_QPA_PLATFORM=xcb GDK_BACKEND=x11 XDG_SESSION_TYPE=x11

# uv when it is there (Ubuntu's python3 has no venv module without python3-venv), else venv and pip.
if command -v uv >/dev/null; then
  [ -x "$VENV/bin/python" ] || uv venv -q --python python3 "$VENV" || exit 2
  (cd "$ROOT" && VIRTUAL_ENV="$VENV" uv pip install -q -e ".[$EXTRAS]") || exit 2
else
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV" || exit 2
  (cd "$ROOT" && "$VENV/bin/python" -m pip install -q -e ".[$EXTRAS]") || exit 2
fi
export PATH="$VENV/bin:$PATH"

# WSLg mounts /tmp/.X11-unix read-only, so Xvfb serves on the abstract socket alone; that is enough on Linux.
# A display another check holds has its lock file, or makes this Xvfb exit; the next number is tried then.
LOG="$(mktemp -d)"
XVFB=""
for n in $(seq 99 199); do
  [ -e "/tmp/.X$n-lock" ] && continue
  Xvfb ":$n" -screen 0 "${SIZE// /x}x24" -nolisten tcp >"$LOG/xvfb.log" 2>&1 &
  XVFB=$!
  for _ in $(seq 1 50); do
    kill -0 "$XVFB" 2>/dev/null || break
    DISPLAY=":$n" xdotool getdisplaygeometry >/dev/null 2>&1 && break
    sleep 0.1
  done
  kill -0 "$XVFB" 2>/dev/null && { export DISPLAY=":$n"; break; }
  XVFB=""
done
if [ -z "$XVFB" ] || [ "$(xdotool getdisplaygeometry 2>/dev/null)" != "$SIZE" ]; then
  echo "no virtual $SIZE screen of its own could be started: nothing was run" >&2
  [ -n "$XVFB" ] && kill "$XVFB" 2>/dev/null
  exit 2
fi
echo "virtual screen $DISPLAY: $(xdotool getdisplaygeometry)"
openbox >"$LOG/openbox.log" 2>&1 &
WM=$!

# The highest number of windows mapped on the virtual screen while the check runs.
(
  most=0
  while kill -0 "$XVFB" 2>/dev/null; do
    n=$(xdotool search --onlyvisible --name '' 2>/dev/null | wc -l)
    [ "$n" -gt "$most" ] && most=$n && echo "$most" >"$LOG/most"
    sleep 0.5
  done
) &
WATCH=$!

cd "$ROOT"
dbus-run-session -- "$@"
STATUS=$?

kill "$WATCH" "$WM" 2>/dev/null
kill "$XVFB" 2>/dev/null
wait 2>/dev/null
echo "windows seen on the virtual screen $DISPLAY: $(cat "$LOG/most" 2>/dev/null || echo 0)"
echo "check exit status: $STATUS"
rm -rf "$LOG"
exit "$STATUS"
