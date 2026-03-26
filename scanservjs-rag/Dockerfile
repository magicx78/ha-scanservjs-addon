ARG BUILD_FROM=python:3.11-slim-bookworm
FROM ${BUILD_FROM}

# System-Abhängigkeiten
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    poppler-utils \
    libmagic1 \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten
COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# App-Dateien
COPY app/ /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /app

CMD ["/run.sh"]
