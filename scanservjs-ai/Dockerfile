ARG BUILD_FROM
FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root
ENV DEBIAN_FRONTEND=noninteractive
ENV ENABLE_BROTHER_SUPPORT=true
ARG BASHIO_VERSION=v0.16.2

# System-Pakete: scanservjs-Basis + Python für KI-Scripts + OCR (build: 2026-03-22-v5)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        jq curl ca-certificates libusb-0.1-4 sane-airscan iproute2 \
        python3 python3-pip python3-venv cron \
        tesseract-ocr tesseract-ocr-deu ocrmypdf poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Bashio
RUN curl -fsSL -o /tmp/bashio.tar.gz "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" \
    && mkdir -p /tmp/bashio \
    && tar -xzf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio \
    && mv /tmp/bashio/lib /usr/lib/bashio \
    && ln -sf /usr/lib/bashio/bashio /usr/bin/bashio \
    && rm -rf /tmp/bashio /tmp/bashio.tar.gz

# Python venv + Abhängigkeiten für KI-Scripts (venv vermeidet PEP 668 Konflikte)
COPY scripts/requirements.txt /opt/paperless-ai/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /opt/paperless-ai/requirements.txt
ENV PATH="/opt/venv/bin:$PATH"

# KI-Scripts
COPY scripts/ /opt/paperless-ai/

# scanservjs-Konfiguration
COPY config.local.js /etc/scanservjs/config.local.js
COPY brother-skey /opt/scanservjs-brother-skey
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh /opt/scanservjs-brother-skey/*.sh

# Claude-Theme: CSS + JS in scanservjs-Frontend injizieren
COPY custom.css /opt/custom.css
COPY custom.js  /opt/custom.js
RUN for html in \
        /usr/lib/scanservjs/client/dist/index.html \
        /app/client/dist/index.html; do \
      if [ -f "$html" ]; then \
        sed -i 's|</head>|<link rel="stylesheet" href="/custom.css"></head>|' "$html"; \
        sed -i 's|</body>|<script src="/custom.js"></script></body>|' "$html"; \
        cp /opt/custom.css "$(dirname "$html")/custom.css"; \
        cp /opt/custom.js  "$(dirname "$html")/custom.js"; \
        echo "Claude-Theme + KI-Panels injiziert: $html"; \
      fi; \
    done

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/run.sh"]
