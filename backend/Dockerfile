FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY frontend/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm

COPY frontend/backend/ ./
COPY frontend/knowledge_base/ /knowledge_base/

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
