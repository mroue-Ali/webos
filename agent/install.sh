#!/bin/sh
# Install or update webos-agent, the webos panel's host helper, as a systemd service.
#
#   cd ~/apps/webos && sudo sh agent/install.sh
#
# It only touches: the webos-agent group, /usr/local/lib/webos-agent,
# /etc/webos-agent.conf (written once, never overwritten) and the webos-agent unit.
# It never touches SSH, the firewall or any other service.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run it with sudo:  sudo sh agent/install.sh" >&2
    exit 1
fi
APPS_USER="${SUDO_USER:-}"
if [ -z "$APPS_USER" ] || [ "$APPS_USER" = "root" ]; then
    echo "Run it with sudo from the user who owns your apps, not as root directly." >&2
    exit 1
fi
HOME_DIR="$(getent passwd "$APPS_USER" | cut -d: -f6)"
APPS_GROUP="$(id -gn "$APPS_USER")"
APPS_ROOT="$HOME_DIR/apps"
HERE="$(cd "$(dirname "$0")" && pwd)"

missing=""
for cmd in python3 git docker nginx certbot ss ip ssh-keygen; do
    command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"
done
if [ -n "$missing" ]; then
    echo "Missing on this server:$missing" >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "webos-agent needs Python 3.10 or newer." >&2
    exit 1
fi

getent group webos-agent >/dev/null || groupadd --system webos-agent
install -d -m 0755 /usr/local/lib/webos-agent
install -m 0755 "$HERE/webos_agent.py" /usr/local/lib/webos-agent/webos_agent.py

if [ ! -f /etc/webos-agent.conf ]; then
    printf '[agent]\napps_root = %s\nuser = %s\n' "$APPS_ROOT" "$APPS_USER" > /etc/webos-agent.conf
    chmod 0644 /etc/webos-agent.conf
fi

# Docker keeps client state in ~/.docker, the only home folder the sandbox lets it write.
[ -d "$HOME_DIR/.docker" ] || install -d -o "$APPS_USER" -g "$APPS_GROUP" -m 0700 "$HOME_DIR/.docker"
[ -d "$APPS_ROOT" ] || install -d -o "$APPS_USER" -g "$APPS_GROUP" -m 0755 "$APPS_ROOT"

sed -e "s|@APPS_ROOT@|$APPS_ROOT|g" -e "s|@HOME@|$HOME_DIR|g" \
    "$HERE/webos-agent.service" > /etc/systemd/system/webos-agent.service
systemctl daemon-reload
systemctl enable webos-agent >/dev/null 2>&1
systemctl restart webos-agent
sleep 2

if ! systemctl is-active --quiet webos-agent; then
    echo "webos-agent didn't start. See:  journalctl -u webos-agent -n 50" >&2
    exit 1
fi
echo "webos-agent is running (apps in $APPS_ROOT, as $APPS_USER)."
echo "Add this line to ~/apps/webos/.env, then run 'docker compose up -d' there:"
echo "WEBOS_AGENT_GID=$(getent group webos-agent | cut -d: -f3)"
