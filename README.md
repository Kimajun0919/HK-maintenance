# HK-maintenance

HK-maintenance는 유지보수 문서와 접수내역을 Supabase에 저장하고, 폴더 기반 문서 관리와 RAG 검색/질문을 제공하는 웹 포털입니다.

프론트엔드는 별도 빌드 없이 CDN React로 동작하고, 백엔드는 FastAPI로 정적 파일과 API를 함께 제공합니다.

## 주요 기능

- 폴더/문서 CRUD
- Markdown, TXT, DOCX, PDF, XLSX 문서 import
- 이미지 asset 업로드와 문서 내 참조
- 휴지통, 복원, 영구 삭제
- Supabase/PostgreSQL 기반 문서 저장
- CSV 유지보수 접수내역 import
- 접수내역 구조화 테이블과 검색용 문서 동시 생성
- RAG 검색과 LLM 질문
- Claude, OpenAI-compatible, Ollama, Groq, Luxia 등 외부 LLM API 설정
- Render/Docker 배포
- Supabase DB 프로필 분리 운영

## 디렉터리 구조

| 경로 | 설명 |
|---|---|
| `backend/` | FastAPI 백엔드, RAG 검색, Supabase storage |
| `frontend/` | React 포털 UI |
| `scripts/` | 배포, CSV import, vector index rebuild 스크립트 |
| `apps/windows/` | Windows WebView 앱 |
| `apps/macos/` | macOS WebView 앱 |
| `apps/android/` | Android WebView 앱 |
| `render.yaml` | Render Blueprint 설정 |
| `Dockerfile` | Render/Docker 배포 이미지 |
| `.env.example` | 환경변수 예시 |

## 로컬 실행

Windows에서는 루트 폴더의 `start-local.bat`를 실행하면 가상환경 준비, 의존성 설치, 서버 실행, 브라우저 열기를 자동으로 처리합니다.

수동 실행:

```powershell
cd C:\test\HK-maintenance
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python backend\app.py
```

접속:

```text
http://127.0.0.1:7860
```

상태 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:7860/healthz
Invoke-RestMethod http://127.0.0.1:7860/api/meta
```

`/api/meta`의 `supabaseProfile` 값으로 현재 바라보는 DB 프로필을 확인할 수 있습니다.

## 필수 환경변수

Supabase를 쓰는 기본 설정:

```env
DOC_STORAGE=supabase
SUPABASE_PROFILE=main
SUPABASE_PROFILE_STRICT=1
SUPABASE_DB_URL_MAIN=postgresql://...
SUPABASE_SEED_FROM_FILES=0
SUPABASE_AUTO_MIGRATE=0
```

로컬 파일만으로 테스트하려면 Supabase URL을 비우고 `DOC_STORAGE=files`로 둡니다.

```env
DOC_STORAGE=files
```

## Supabase 프로필 운영

이 프로젝트는 하나의 코드로 여러 Supabase DB를 분리해서 운영할 수 있습니다. 사용자가 화면에서 DB를 선택하는 방식이 아니라, 앱 인스턴스마다 하나의 DB를 바라보게 하는 방식입니다.

```env
SUPABASE_PROFILE=main
SUPABASE_PROFILE_STRICT=1
SUPABASE_DB_URL_MAIN=postgresql://...
SUPABASE_DB_URL_FRESH=postgresql://...
```

- `SUPABASE_PROFILE=main`: `SUPABASE_DB_URL_MAIN` 사용
- `SUPABASE_PROFILE=fresh`: `SUPABASE_DB_URL_FRESH` 사용
- `SUPABASE_PROFILE_STRICT=1`: 프로필 URL이 없으면 기존 `SUPABASE_DB_URL`로 fallback하지 않음

DB URL은 git에 커밋하지 않습니다. 로컬은 `.env`, Render는 Secret Env Var에만 저장합니다.

## 새 Supabase DB 초기화

fresh DB 같은 새 Supabase 프로젝트를 만든 뒤, 로컬에서 스키마와 CSV 데이터를 넣습니다.

```powershell
$env:NEW_SUPABASE_DB_URL="postgresql://..."
python scripts/bootstrap_fresh_supabase.py "유지보수 접수내역.csv"
```

이미 빈 스키마가 있는 DB에 다시 넣을 때:

```powershell
$env:NEW_SUPABASE_DB_URL="postgresql://..."
python scripts/bootstrap_fresh_supabase.py "유지보수 접수내역.csv" --allow-non-empty
```

CSV 구조만 확인:

```powershell
python scripts/bootstrap_fresh_supabase.py "유지보수 접수내역.csv" --dry-run
```

bootstrap 스크립트가 하는 일:

- `maintenance_docs` 생성
- `maintenance_docs_folders` 생성
- `maintenance_docs_assets` 생성
- `maintenance_docs_chunks` 생성
- `maintenance_requests` 생성
- `maintenance_requests_imports` 생성
- CSV 30개 컬럼을 `maintenance_requests`에 보존
- `idx` 기준으로 upsert
- `유지보수_접수내역/접수_{idx}.md` 문서를 생성해 기존 폴더 UI/RAG 검색에 연결

## CSV 접수내역 import

현재 CSV 구조는 다음 컬럼을 기대합니다.

```text
idx,user_id,contact_person,manager_id,worker_id,type_id,status_id,title,content,
request_date,expected_date,completed_date,
expected_pm_hours,expected_design_hours,expected_pub_hours,expected_dev_hours,
expected_hours_confirmed,expected_hours_confirmed_at,
actual_pm_hours,actual_design_hours,actual_pub_hours,actual_dev_hours,
is_urgent,issues,report_title,progress_rate,progress_status,notes,created_at,updated_at
```

기존 DB에 같은 CSV를 다시 넣어도 `idx` 기준으로 갱신됩니다.

```powershell
python scripts/import_maintenance_requests_csv.py "유지보수 접수내역.csv"
```

## Render 배포

`render.yaml`은 DB별로 앱을 따로 띄우도록 구성되어 있습니다.

| Render service | Profile | Required secret env |
|---|---|---|
| `hk-maintenance-rag` | `main` | `SUPABASE_DB_URL_MAIN` |
| `hk-maintenance-rag-fresh` | `fresh` | `SUPABASE_DB_URL_FRESH` |

배포 순서:

1. Render Dashboard에서 Blueprint를 이 GitHub repo에 연결합니다.
2. `hk-maintenance-rag` 서비스 Environment에 `SUPABASE_DB_URL_MAIN`을 Secret Env Var로 넣습니다.
3. `hk-maintenance-rag-fresh` 서비스 Environment에 `SUPABASE_DB_URL_FRESH`를 Secret Env Var로 넣습니다.
4. 두 서비스를 각각 Deploy합니다.

두 서비스는 같은 코드와 Dockerfile을 쓰지만 서로 다른 DB를 봅니다.

```text
https://hk-maintenance-rag.onrender.com        -> main DB
https://hk-maintenance-rag-fresh.onrender.com  -> fresh DB
```

## Render Free Tier 메모리 설정

Render free tier는 512Mi 메모리 제한이 있습니다. main DB처럼 문서가 많을 때 전체 RAG 인덱스를 시작 시 메모리에 만들면 OOM이 발생할 수 있습니다. 그래서 Dockerfile과 `render.yaml`은 저메모리 모드를 기본값으로 둡니다.

```env
RAG_STARTUP_INDEX=0
RAG_ENABLE_NGRAM_INDEX=0
RAG_ENABLE_LEGACY_INDEX=0
EMBEDDING_BACKEND=none
```

이 모드에서는 앱 시작 시 전체 인덱스를 만들지 않고, 검색 요청 때 Supabase DB에 직접 질의합니다. 폴더 목록, 문서 CRUD, 검색 UI는 그대로 동작합니다.

사양별 권장값:

| 서버 사양 | 설정 |
|---|---|
| Render free / 512Mi | `RAG_STARTUP_INDEX=0`, `RAG_ENABLE_NGRAM_INDEX=0`, `RAG_ENABLE_LEGACY_INDEX=0`, `EMBEDDING_BACKEND=none` |
| 일반 서버 / 1-2GB | `RAG_STARTUP_INDEX=1`, `RAG_ENABLE_NGRAM_INDEX=0`, `RAG_ENABLE_LEGACY_INDEX=0`, `EMBEDDING_BACKEND=none` |
| 고사양 서버 / 2GB+ | `RAG_STARTUP_INDEX=1`, `RAG_ENABLE_NGRAM_INDEX=1`, `RAG_ENABLE_LEGACY_INDEX=1`, `EMBEDDING_BACKEND=none` |
| semantic 실험 / 4GB+ | `RAG_STARTUP_INDEX=1`, `RAG_ENABLE_NGRAM_INDEX=1`, `RAG_ENABLE_LEGACY_INDEX=1`, `EMBEDDING_BACKEND=sentence-transformers` |

semantic embedding 모드는 추가 패키지가 필요합니다.

```powershell
pip install -r backend\requirements-embeddings.txt
```

## Docker 배포

Dockerfile 기본값은 저메모리 모드입니다.

```bash
docker build -t hk-maintenance-rag .
docker run -p 8080:8080 \
  -e DOC_STORAGE=supabase \
  -e SUPABASE_PROFILE=main \
  -e SUPABASE_PROFILE_STRICT=1 \
  -e SUPABASE_DB_URL_MAIN=postgresql://... \
  hk-maintenance-rag
```

더 큰 서버에서 startup index를 켜려면:

```bash
docker run -p 8080:8080 \
  -e DOC_STORAGE=supabase \
  -e SUPABASE_PROFILE=main \
  -e SUPABASE_PROFILE_STRICT=1 \
  -e SUPABASE_DB_URL_MAIN=postgresql://... \
  -e RAG_STARTUP_INDEX=1 \
  -e RAG_ENABLE_NGRAM_INDEX=1 \
  -e RAG_ENABLE_LEGACY_INDEX=1 \
  hk-maintenance-rag
```

## 주요 API

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/api/meta` | 앱 상태, storage, profile, doc count |
| `GET` | `/api/docs` | 문서/폴더 목록 |
| `GET` | `/api/doc?source=...` | 문서 조회 |
| `POST` | `/api/doc` | 문서 생성 |
| `PUT` | `/api/doc` | 문서 수정 |
| `DELETE` | `/api/doc` | 문서 휴지통 이동 |
| `GET` | `/api/search?q=...` | RAG 검색 |
| `POST` | `/api/chat` | 검색 기반 LLM 질문 |
| `POST` | `/api/search-index/rebuild` | 검색 인덱스 재생성 |
| `GET` | `/api/maintenance-requests/search?q=...` | 구조화 접수내역 검색 |
| `POST` | `/api/folder/parse` | 서버 로컬 폴더 import |
| `GET` | `/api/trash` | 휴지통 목록 |
| `POST` | `/api/trash/restore` | 휴지통 복원 |
| `DELETE` | `/api/trash` | 영구 삭제 |

## LLM API 설정

UI의 API 관리에서 여러 LLM provider를 등록할 수 있습니다.

지원 형태:

- Claude
- OpenAI-compatible
- Groq
- Ollama
- LM Studio
- Luxia

Render 같은 외부 서버는 로컬 PC의 Ollama 또는 Tailscale 사설 주소에 접근하지 못할 수 있습니다. Ollama를 쓰려면 앱도 로컬에서 실행하거나, Render에서 접근 가능한 공개 API를 사용해야 합니다.

## 테스트

```powershell
python -m unittest backend.test_hybrid_search
```

검색 품질 케이스:

```powershell
python backend/eval_hybrid_search.py
```

## 보안 주의사항

- `.env`는 git에 커밋하지 않습니다.
- Supabase DB URL이나 비밀번호가 노출되면 Supabase에서 password를 rotate/reset하고 Render Secret Env Var를 새 값으로 교체합니다.
- 유지보수 문서에는 계정, 서버, 경로 정보가 포함될 수 있으므로 저장소와 Supabase 프로젝트 접근 권한을 제한합니다.
- Render Dashboard env 값이 Dockerfile 기본값보다 우선합니다. free tier에서 `RAG_STARTUP_INDEX=1`이 남아 있으면 다시 OOM이 날 수 있습니다.
