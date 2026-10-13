FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend app
COPY app ./app
COPY pytest.ini .
COPY tests ./tests

ENV PYTHONPATH=/app
ENV SQLITE_DB_PATH=/app/data/checkout_radar.db
ENV EVIDENCE_DIR=/app/data/evidence
ENV FRONTEND_DIR=/app/frontend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
