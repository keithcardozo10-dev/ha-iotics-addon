#!/bin/bash
# ==============================================================================
# Iotics Smart Home Bridge Add-on for Home Assistant
# ==============================================================================

set -e

echo "[IOTICS] Starting Iotics Smart Home Bridge..."

# Credentials come from addon config (set as env vars by HA supervisor)
IOTICS_EMAIL="${IOTICS_EMAIL:-}"
IOTICS_PASSWORD="${IOTICS_PASSWORD:-}"
IOTICS_APPID="${IOTICS_APPID:-696f74696373617070}"

# Also try /data/options.json if env vars are empty (fallback)
if [ -z "$IOTICS_EMAIL" ] || [ -z "$IOTICS_PASSWORD" ]; then
    if [ -f /data/options.json ]; then
        echo "[IOTICS] Reading config from /data/options.json..."
        CONFIG=$(cat /data/options.json)
        [ -z "$IOTICS_EMAIL" ] && IOTICS_EMAIL=$(echo "$CONFIG" | python3 -c "import json,sys; print(json.load(sys.stdin).get('iotics_email',''))")
        [ -z "$IOTICS_PASSWORD" ] && IOTICS_PASSWORD=$(echo "$CONFIG" | python3 -c "import json,sys; print(json.load(sys.stdin).get('iotics_password',''))")
        APPID=$(echo "$CONFIG" | python3 -c "import json,sys; print(json.load(sys.stdin).get('iotics_appid',''))")
        [ -n "$APPID" ] && IOTICS_APPID="$APPID"
    fi
fi

if [ -z "$IOTICS_EMAIL" ] || [ -z "$IOTICS_PASSWORD" ]; then
    echo "[IOTICS] ERROR: IOTICS_EMAIL and IOTICS_PASSWORD must be set"
    exit 1
fi

echo "[IOTICS] Email: ${IOTICS_EMAIL}"
echo "[IOTICS] AppID: ${IOTICS_APPID}"

HASS_TOKEN="${SUPERVISOR_TOKEN:-}"
HASS_URL="${HASS_URL:-http://supervisor/core}"

if [ -z "$HASS_TOKEN" ]; then
    echo "[IOTICS] ERROR: SUPERVISOR_TOKEN not available"
    exit 1
fi

echo "[IOTICS] Starting bridge..."
cd /opt/iotics-bridge
exec python3 -u /opt/iotics-bridge/bridge.py \
    --iotics-email "${IOTICS_EMAIL}" \
    --iotics-password "${IOTICS_PASSWORD}" \
    --iotics-appid "${IOTICS_APPID}" \
    --log-level info \
    --log-file /tmp/iotics_bridge.log
