#!/usr/bin/env bashio
set -e

# ── Dependencies ─────────────────────────────────────────────────────────
bashio::log.info "Installing Python dependencies..."
apk add --no-cache python3 py3-pip py3-setuptools py3-cryptography arp-scan net-tools
pip3 install --no-cache-dir \
    paho-mqtt \
    websocket-client \
    requests \
    aiohttp

bashio::log.info "Dependencies installed."
