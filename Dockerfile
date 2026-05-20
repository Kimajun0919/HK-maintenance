FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/*.py .
COPY frontend/ frontend/

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8080
ENV PYTHONUNBUFFERED=1

# Safe Docker defaults for low-memory hosts such as Render free tier.
# Override these at deploy time on larger servers:
#   Normal server: RAG_STARTUP_INDEX=1, RAG_ENABLE_NGRAM_INDEX=0, RAG_ENABLE_LEGACY_INDEX=0
#   Higher-memory: RAG_STARTUP_INDEX=1, RAG_ENABLE_NGRAM_INDEX=1, RAG_ENABLE_LEGACY_INDEX=1
#   Semantic mode: also set EMBEDDING_BACKEND=sentence-transformers after installing embedding deps.
ENV SUPABASE_SEED_FROM_FILES=0
ENV SUPABASE_AUTO_MIGRATE=0
ENV EMBEDDING_BACKEND=none
ENV RAG_STARTUP_INDEX=0
ENV RAG_ENABLE_NGRAM_INDEX=0
ENV RAG_ENABLE_LEGACY_INDEX=0
EXPOSE 8080

CMD ["python", "app.py"]
