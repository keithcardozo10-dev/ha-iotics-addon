#!/usr/bin/env bashio
# ==============================================================================
# Iotics Smart Home Bridge Add-on for Home Assistant
# Runs the bridge in a Docker container with HA supervisor access
# ==============================================================================

set -e

bashio::log.info "Starting Iotics Smart Home Bridge..."

# ── Read configuration ──────────────────────────────────────────────────
IOTICS_EMAIL=$(bashio::config 'iotics_email')
IOTICS_PASSWORD=$(bashio::config 'iotics_password')
IOTICS_APPID=$(bashio::config 'iotics_appid')

# ── Validate ────────────────────────────────────────────────────────────
if bashio::config.is_empty 'iotics_email' || bashio::config.is_empty 'iotics_password'; then
    bashio::log.fatal "Iotics email and password are required. Configure them in the add-on settings."
    exit 1
fi

bashio::log.info "Iotics email: ${IOTICS_EMAIL}"
bashio::log.info "Iotics appid: ${IOTICS_APPID}"

# ── Export for the bridge script ────────────────────────────────────────
export IOTICS_EMAIL
export IOTICS_PASSWORD
export IOTICS_APPID

# ── HA supervisor details ───────────────────────────────────────────────
export HASS_TOKEN="${SUPERVISOR_TOKEN}"
export HASS_URL="http://supervisor/core"

# ── AWS IoT Core — auto-discovered from bridge via dynamic tokens ───────
# The bridge auto-discovers AWS endpoint, access key, and secret key from
# the AWS IoT device gateway during its first cloud API poll. No static
# config needed — just your Iotics login credentials.
# ────────────────────────────────────────────────────────────────────────

# ── Run bridge ──────────────────────────────────────────────────────────
cd /opt/iotics-bridge

bashio::log.info "Starting bridge (log: /tmp/iotics_bridge_v4.log)..."
exec python3 -u /opt/iotics-bridge/bridge.py \
    --log-level info \
    --log-file /tmp/iotics_bridge_v4.log \
    --ha-token "${SUPERVISOR_TOKEN}" \
    --ha-url "http://supervisor/core" \
    --iotics-email "${IOTICS_EMAIL}" \
    --iotics-password "${IOTICS_PASSWORD}" \
    --iotics-appid "${IOTICS_APPID}"
