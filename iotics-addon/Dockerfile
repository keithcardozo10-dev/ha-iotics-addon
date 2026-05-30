FROM ghcr.io/home-assistant/{arch}-base:latest

ARG BUILD_ARCH

# Install Python and deps
RUN apk add --no-cache \
        python3 py3-pip py3-setuptools py3-cryptography \
        arp-scan net-tools \
        ca-certificates && \
    pip3 install --no-cache-dir \
        paho-mqtt \
        websocket-client \
        requests \
        aiohttp

# Copy bridge
COPY bridge.py /opt/iotics-bridge/bridge.py
RUN chmod +x /opt/iotics-bridge/bridge.py

# Copy run script
COPY run.sh /
RUN chmod +x /run.sh

# Run
CMD [ "/run.sh" ]

LABEL \
    io.hass.name="Iotics Smart Home Bridge" \
    io.hass.description="Connect Iotics smart home devices to Home Assistant" \
    io.hass.arch="${BUILD_ARCH}}" \
    io.hass.type="addon" \
    io.hass.version="1.0.0"
