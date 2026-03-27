ARG BUILD_FROM
FROM ${BUILD_FROM}

# System-Abhängigkeiten (Debian bookworm, apt-get)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    poppler-utils \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten in venv (kein --break-system-packages nötig)
COPY app/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

ENV PATH="/opt/venv/bin:$PATH"

# App-Dateien
COPY app/ /app/
COPY config.yaml /addon-config.yaml
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /app

CMD ["/run.sh"]
