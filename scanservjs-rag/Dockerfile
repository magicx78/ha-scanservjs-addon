ARG BUILD_FROM
FROM ${BUILD_FROM}

# System-Abhängigkeiten (Alpine apk)
RUN apk add --no-cache \
    tesseract-ocr \
    tesseract-ocr-data-deu \
    tesseract-ocr-data-eng \
    poppler-utils \
    file \
    jq \
    gcc \
    musl-dev \
    python3-dev

# Python-Abhängigkeiten
COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# App-Dateien
COPY app/ /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /app

CMD ["/run.sh"]
