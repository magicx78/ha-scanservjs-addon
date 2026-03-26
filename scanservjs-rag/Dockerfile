ARG BUILD_FROM
FROM ${BUILD_FROM}

# System-Abhängigkeiten + Python (Alpine apk)
RUN apk add --no-cache \
    python3 \
    py3-pip \
    tesseract-ocr \
    tesseract-ocr-data-deu \
    tesseract-ocr-data-eng \
    poppler-utils \
    jq

# Python-Abhängigkeiten
COPY app/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# App-Dateien
COPY app/ /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /app

CMD ["/run.sh"]
