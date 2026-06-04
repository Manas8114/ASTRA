# ─────────────────────────────────────────────────────────────────────────────
# ASTRA xApp — Single-stage Dockerfile (fast build, pre-trained models)
#
# FAST BUILD STRATEGY:
#   If xapp/model/saved_models/*.pt files exist locally, they are copied
#   directly — NO training happens in Docker (build < 2 min).
#
#   If model files are missing, run locally first:
#     python training/generate_normal_data.py
#     python training/train_lstm.py
#     python training/train_forecast.py
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# GPU support: set USE_GPU=true at build time for CUDA-enabled PyTorch
ARG USE_GPU=false
ENV ASTRA_USE_GPU=${USE_GPU}

# Install all runtime dependencies (cached layer — only re-runs if requirements change)
COPY xapp/requirements.txt /app/xapp/requirements.txt

RUN if [ "$USE_GPU" = "true" ]; then \
        echo "[Docker] Installing GPU-enabled PyTorch..." && \
        pip install --no-cache-dir -r /app/xapp/requirements.txt \
            --extra-index-url https://download.pytorch.org/whl/cu121 && \
        pip install --no-cache-dir onnxruntime-gpu 2>/dev/null || true; \
    else \
        pip install --no-cache-dir -r /app/xapp/requirements.txt \
            --index-url https://download.pytorch.org/whl/cpu \
            --extra-index-url https://pypi.org/simple/; \
    fi

# Copy full source + pre-trained models in one step
COPY . /app

# Ensure model directories exist; train only if weights are missing (fallback)
RUN mkdir -p /app/training/data /app/xapp/model/saved_models && \
    if [ ! -f /app/xapp/model/saved_models/lstm_ae_best.pt ]; then \
        echo "[Docker] No pre-trained weights found — running minimal training..." && \
        pip install --no-cache-dir numpy torch joblib scikit-learn pandas \
            --index-url https://download.pytorch.org/whl/cpu \
            --extra-index-url https://pypi.org/simple/ -q && \
        ASTRA_LSTM_EPOCHS=3 python training/generate_normal_data.py && \
        ASTRA_LSTM_EPOCHS=3 python training/train_lstm.py && \
        ASTRA_FORECAST_EPOCHS=2 ASTRA_FORECAST_LEN=30 python training/train_forecast.py; \
    else \
        echo "[Docker] Pre-trained weights found — skipping training."; \
    fi

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "xapp.main"]

