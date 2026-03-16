ARG BUILD_FROM
FROM $BUILD_FROM

USER root
ENV DEBIAN_FRONTEND=noninteractive
ENV ENABLE_BROTHER_SUPPORT=false
ARG BASHIO_VERSION=v0.16.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq curl ca-certificates libusb-0.1-4 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/bashio.tar.gz "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" \
    && mkdir -p /tmp/bashio \
    && tar -xzf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio \
    && mv /tmp/bashio/lib /usr/lib/bashio \
    && ln -sf /usr/lib/bashio/bashio /usr/bin/bashio \
    && rm -rf /tmp/bashio /tmp/bashio.tar.gz

COPY config.local.js /etc/scanservjs/config.local.js
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080

ENTRYPOINT ["/run.sh"]
