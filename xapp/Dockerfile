# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# ASTRA xApp — Multi-stage Dockerfile
# Stage 1: Train ML models (runs once, output cached by Docker layer)
# Stage 2: Runtime image with pre-trained models baked in
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Model Training ──────────────────────────────────────────────────
FROM python:3.11-slim AS trainer

WORKDIR /app

# Install only what training needs (lighter than full runtime)
RUN pip install --no-cache-dir numpy torch --index-url https://download.pytorch.org/whl/cpu joblib scikit-learn

# Copy training code and project schema (needed by training scripts)
COPY training/ /app/training/
COPY xapp/ingestion/kpi_schema.py /app/xapp/ingestion/kpi_schema.py
COPY xapp/__init__.py /app/xapp/__init__.py
COPY xapp/ingestion/__init__.py /app/xapp/ingestion/__init__.py

ENV PYTHONPATH=/app

# Generate synthetic normal data and train the LSTM autoencoder
RUN mkdir -p /app/training/data /app/xapp/model/saved_models && \
    python training/generate_normal_data.py && \
    python training/train_lstm.py && \
    python training/train_forecast.py

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install all runtime dependencies
COPY xapp/requirements.txt /app/xapp/requirements.txt
RUN pip install --no-cache-dir -r /app/xapp/requirements.txt \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple/

# Copy full source
COPY . /app

# Copy pre-trained model artifacts from trainer stage
COPY --from=trainer /app/xapp/model/saved_models/ /app/xapp/model/saved_models/
COPY --from=trainer /app/training/data/ /app/training/data/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "xapp.main"]
