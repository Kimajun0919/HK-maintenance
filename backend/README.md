# HK Maintenance RAG Chatbot

## 운영 배포 요약

이 백엔드는 Supabase 프로필 방식으로 여러 DB를 분리해서 운영할 수 있습니다. 같은 코드와 Docker 이미지를 쓰되, 배포 인스턴스마다 다른 `SUPABASE_PROFILE`과 DB URL을 넣습니다.

```env
DOC_STORAGE=supabase
SUPABASE_PROFILE=main
SUPABASE_PROFILE_STRICT=1
SUPABASE_DB_URL_MAIN=postgresql://...
```

fresh DB를 보는 인스턴스는 다음처럼 설정합니다.

```env
DOC_STORAGE=supabase
SUPABASE_PROFILE=fresh
SUPABASE_PROFILE_STRICT=1
SUPABASE_DB_URL_FRESH=postgresql://...
```

`SUPABASE_PROFILE_STRICT=1`이면 프로필 전용 URL이 없을 때 기존 `SUPABASE_DB_URL`로 fallback하지 않습니다. 운영 DB 오접속 방지를 위해 유지하는 것이 좋습니다.

### Render 서비스 구성

`render.yaml`은 두 개의 Web Service를 정의합니다.

| Service | Profile | Secret env |
|---|---|---|
| `hk-maintenance-rag` | `main` | `SUPABASE_DB_URL_MAIN` |
| `hk-maintenance-rag-fresh` | `fresh` | `SUPABASE_DB_URL_FRESH` |

Render free tier에서는 아래 저메모리 설정을 사용합니다.

```env
RAG_STARTUP_INDEX=0
RAG_ENABLE_NGRAM_INDEX=0
RAG_ENABLE_LEGACY_INDEX=0
EMBEDDING_BACKEND=none
```

이 모드는 시작 시 전체 문서 인덱스를 메모리에 만들지 않고, 검색 요청 때 Supabase DB를 직접 조회합니다. main DB처럼 문서가 많은 경우 free tier OOM을 피하기 위한 기본 설정입니다.

더 큰 서버에서는 환경변수로 덮어쓸 수 있습니다.

```env
RAG_STARTUP_INDEX=1
RAG_ENABLE_NGRAM_INDEX=1
RAG_ENABLE_LEGACY_INDEX=1
EMBEDDING_BACKEND=none
```

semantic embedding까지 쓰려면 `backend/requirements-embeddings.txt` 설치와 더 큰 메모리가 필요합니다.

### 새 DB 초기화

새 Supabase 프로젝트를 만든 뒤 로컬에서 스키마와 CSV 데이터를 넣습니다.

```powershell
$env:NEW_SUPABASE_DB_URL="postgresql://..."
python scripts/bootstrap_fresh_supabase.py "유지보수 접수내역.csv"
```

이미 빈 스키마가 생성된 DB에 데이터를 다시 넣을 때는:

```powershell
$env:NEW_SUPABASE_DB_URL="postgresql://..."
python scripts/bootstrap_fresh_supabase.py "유지보수 접수내역.csv" --allow-non-empty
```

현재 앱이 어떤 DB 프로필을 보는지는 `/api/meta` 응답의 `supabaseProfile`로 확인합니다.

유지보수 문서를 Supabase에 저장·관리하고 외부 LLM API로 RAG 질문·검색하는 웹 포털입니다.

## 기술 스택

| 항목 | 내용 |
|---|---|
| 백엔드 | FastAPI + uvicorn |
| 저장소 | Supabase (PostgreSQL) |
| 검색 | 문자 n-gram 인메모리 인덱스 |
| LLM | 외부 API (Claude / OpenAI-compatible) |
| 프론트엔드 | React (CDN, 빌드 없음) |

## 로컬 실행

```powershell
cd backend
python app.py
```

브라우저에서 `http://127.0.0.1:7860` 접속.

### 환경변수 (`.env`)

```env
# Supabase 연결 (필수)
SUPABASE_DB_URL=postgresql://user:pass@host:port/db
DOC_STORAGE=supabase
SUPABASE_SEED_FROM_FILES=0   # 초기 씨딩 완료 후 0으로 설정

# 포트 (선택, 기본 7860)
APP_PORT=7860

# 이미지 업로드 크기 제한 (선택, 기본 2MB)
ASSET_MAX_SIZE_MB=2
```

## 배포

### Render.com

루트의 `render.yaml` 기준으로 자동 설정됩니다.

```
Render → New → Blueprint → GitHub 레포 연결
→ SUPABASE_DB_URL 입력 → Deploy
```

### Hugging Face Spaces

```powershell
# 루트 .env에 설정 후
python ../scripts/deploy_hf_space.py
```

Space 시크릿에 `SUPABASE_DB_URL`, `SUPABASE_SEED_FROM_FILES=0` 추가.

### Docker

```bash
docker build -t hk-rag .
docker run -p 8080:8080 \
  -e SUPABASE_DB_URL=postgresql://... \
  -e DOC_STORAGE=supabase \
  -e SUPABASE_SEED_FROM_FILES=0 \
  hk-rag
```

## 지원 LLM API

포털 내 **⚙ API 관리**에서 등록·선택합니다. 모든 설정은 브라우저 localStorage에만 저장됩니다.

| 유형 | 예시 |
|---|---|
| Claude (Anthropic) | claude-sonnet-4-5 등 |
| OpenAI-compatible | OpenAI, Groq, Ollama, LM Studio, Together AI |
| 커스텀 헤더 | Luxia (`apikey: {key}`, 경로: `/chat`) |

OpenAI-compatible 응답 파서는 `choices[0].message.content` 외에도 `choices[0].text`, `answer`, `response`, `output_text`, `content`, `message`, `result` 형태를 처리합니다. Base URL이 `/v1`로 끝나고 경로도 `/v1/...`로 들어온 경우 중복 `/v1/v1`은 자동 보정합니다.

## 주요 API

| 메서드 | 경로 | 기능 |
|---|---|---|
| GET | `/api/docs` | 문서·폴더 목록 |
| POST | `/api/doc` | 문서 생성 |
| PUT | `/api/doc` | 문서 수정 |
| DELETE | `/api/doc` | 휴지통 이동 |
| POST | `/api/asset` | 이미지 업로드 |
| POST | `/api/convert` | .docx/.pdf → Markdown 변환 |
| POST | `/api/folder/parse` | 서버 로컬 폴더 분석·문서 가져오기 |
| GET | `/api/trash` | 휴지통 목록 |
| POST | `/api/trash/restore` | 복원 |
| DELETE | `/api/trash` | 영구 삭제 |
| POST | `/api/chat` | LLM 질문 |
| GET | `/api/search` | RAG 검색 |

## 의존성 설치

```powershell
pip install -r requirements.txt
```
