ARG BUILD_FROM
FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root
ENV DEBIAN_FRONTEND=noninteractive
ENV ENABLE_BROTHER_SUPPORT=true
ARG BASHIO_VERSION=v0.16.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq curl ca-certificates libusb-0.1-4 sane-airscan iproute2 python3 python3-pip python3-venv tesseract-ocr tesseract-ocr-deu poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/bashio.tar.gz "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" \
    && mkdir -p /tmp/bashio \
    && tar -xzf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio \
    && mv /tmp/bashio/lib /usr/lib/bashio \
    && ln -sf /usr/lib/bashio/bashio /usr/bin/bashio \
    && rm -rf /tmp/bashio /tmp/bashio.tar.gz

COPY config.local.js /etc/scanservjs/config.local.js
COPY brother-skey /opt/scanservjs-brother-skey
COPY sorter_engine.py /opt/scanservjs-sorter/sorter_engine.py
COPY requirements-sorter.txt /opt/scanservjs-sorter/requirements-sorter.txt
COPY run.sh /usr/local/bin/run.sh
RUN python3 -m venv /opt/scanservjs-sorter/.venv \
    && /opt/scanservjs-sorter/.venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/scanservjs-sorter/.venv/bin/pip install --no-cache-dir -r /opt/scanservjs-sorter/requirements-sorter.txt \
    && chmod +x /usr/local/bin/run.sh /opt/scanservjs-brother-skey/*.sh /opt/scanservjs-sorter/sorter_engine.py

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/run.sh"]
