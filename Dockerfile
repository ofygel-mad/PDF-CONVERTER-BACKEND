FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for PyMuPDF, OpenCV (used by RapidOCR), libgomp (used by onnxruntime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# Create the data directory so the app can write sessions / job uploads.
RUN mkdir -p /app/data/sessions /app/data/ocr-reviews /app/data/job-uploads

EXPOSE 8000

# Simple startup - app handles everything
CMD ["python", "main.py"]
