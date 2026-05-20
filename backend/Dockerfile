FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/*.py .
COPY frontend/ frontend/
COPY v2/ v2/

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8080
ENV PYTHONUNBUFFERED=1

# Docker defaults use Supabase-backed chunk search. The web process does not
# build a full in-memory startup index, so this stays within small host memory.
ENV SUPABASE_SEED_FROM_FILES=0
ENV SUPABASE_AUTO_MIGRATE=0
ENV EMBEDDING_BACKEND=hash
ENV RAG_STARTUP_INDEX=0
EXPOSE 8080

CMD ["python", "app.py"]
