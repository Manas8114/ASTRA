FROM python:3.11-slim

WORKDIR /app
COPY xapp/requirements.txt /app/xapp/requirements.txt
RUN pip install --no-cache-dir -r /app/xapp/requirements.txt
COPY . /app
ENV PYTHONPATH=/app
CMD ["python", "-m", "xapp.main"]
