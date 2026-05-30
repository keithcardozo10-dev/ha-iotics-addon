ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
        python3 py3-pip py3-setuptools py3-cryptography \
        arp-scan net-tools \
        ca-certificates && \
    pip3 install --no-cache-dir \
        websocket-client

COPY bridge.py /opt/iotics-bridge/bridge.py
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

LABEL \
    io.hass.name="Iotics Smart Home Bridge" \
    io.hass.description="Connect Iotics smart home devices to Home Assistant" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="1.0.0"
