FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir grpcio
COPY twin-service /app
CMD ["python", "server.py"]
