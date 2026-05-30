FROM python:3-alpine

RUN apk add --no-cache bash arp-scan net-tools ca-certificates && \
    pip3 install --no-cache-dir websocket-client websockets

COPY bridge.py /opt/iotics-bridge/bridge.py
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

LABEL io.hass.name="Iotics Smart Home Bridge" \
      io.hass.description="Connect Iotics smart home to HA" \
      io.hass.type="addon" \
      io.hass.version="1.0.0"
