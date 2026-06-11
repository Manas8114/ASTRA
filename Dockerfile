FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system -r pyproject.toml

COPY . .

# Assume models are already generated via setup_models.py
ENV PYTHONPATH=/app
ENV ASTRA_MODE=prod

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "xapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
