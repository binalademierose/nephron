FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120 --access-logfile - --error-logfile -"]
