FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir prometheus-client
COPY core/kpi_exporter.py /app/kpi_exporter.py
CMD ["python", "kpi_exporter.py"]
