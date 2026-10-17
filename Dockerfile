# Production image for Nephron (Railway, Render, Fly.io, or any container host).
# Unlike Vercel, a container CAN install the system programs the OCR lab-upload needs, so Enhanced Screening by
# photo/PDF works here. The app is served by gunicorn (a real production server), not Flask's development server.
FROM python:3.13-slim

# System programs: Tesseract (OCR) and Poppler (pdftoppm, for reading PDF lab reports). Without these the app still
# runs - it just shows manual lab entry instead of the photo upload.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies first (cached unless requirements.txt changes).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Then the application code (models included - see ml/model and ml/model_stage2).
COPY . .

# The host sets $PORT. Bind gunicorn to it; two workers and a generous timeout for the one-time model load on start.
# "app:app" is the WSGI application object created in app.py.
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120 --access-logfile - --error-logfile -"]
