ARG BUILD_FROM
FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root
ENV DEBIAN_FRONTEND=noninteractive
ENV ENABLE_BROTHER_SUPPORT=true
ARG BASHIO_VERSION=v0.16.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq curl ca-certificates libusb-0.1-4 sane-airscan iproute2 imagemagick nodejs npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && if [ -f /etc/ImageMagick-6/policy.xml ]; then \
         sed -i 's|<policy domain="coder" rights="none" pattern="PDF"|<policy domain="coder" rights="read\|write" pattern="PDF"|g' /etc/ImageMagick-6/policy.xml; \
       fi

RUN curl -fsSL -o /tmp/bashio.tar.gz "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" \
    && mkdir -p /tmp/bashio \
    && tar -xzf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio \
    && mv /tmp/bashio/lib /usr/lib/bashio \
    && ln -sf /usr/lib/bashio/bashio /usr/bin/bashio \
    && rm -rf /tmp/bashio /tmp/bashio.tar.gz

RUN npm install -g @llamaindex/liteparse

COPY config.local.js /etc/scanservjs/config.local.js
COPY brother-skey /opt/scanservjs-brother-skey
COPY scripts /opt/scanservjs-liteparse/scripts
COPY liteparse.config.json /opt/scanservjs-liteparse/liteparse.config.json
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh /opt/scanservjs-brother-skey/*.sh /opt/scanservjs-liteparse/scripts/*.sh /opt/scanservjs-liteparse/scripts/*.js \
    && ln -sf /opt/scanservjs-liteparse/scripts/liteparse-test.sh /usr/local/bin/liteparse-test

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/run.sh"]
