FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/*.py .
# v3 엔티티 사전. scripts/mine_terms.py 산출물이며 런타임이 읽는다.
# (backend/settings.json 은 의도적으로 제외 — 현재 이미지에 포함되지 않아
#  운영이 rag.py 기본값으로 동작 중이므로, 여기서 넣으면 v1 검색 가중치가
#  조용히 바뀐다. 별도 확인 후 처리할 것.)
COPY backend/domain_terms.json .
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
