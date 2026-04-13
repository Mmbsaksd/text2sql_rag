FROM python:3.12-slim as base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic \
    poppler-utils \
    tesseract-ocr \
    gcc \
    g++ \
    libspatialindex-dev \
    libgl1 \
    libglib2.0-0 \
    %% apt-get clean \
    && rm -rf /var/lib/apt/lists/*


FROM base as builder

WORKDIR /app
COPY requirements.txt .

RUN pip install --user --no-warn-script-location -r requirements.txt

ENV PATH=/root/.local/bin:$PATH

COPY app/ ./app/
COPY data/sql/ ./data/sql/
COPY data/generate_sample_data.py ./data/
COPY evaluate.py .
COPY tests/ ./tests/

RUN mkdir -p data/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1


CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]