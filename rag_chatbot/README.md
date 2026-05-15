# HK Maintenance RAG Chatbot

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
cd rag_chatbot
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
python ../deploy_hf_space.py
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

## 주요 API

| 메서드 | 경로 | 기능 |
|---|---|---|
| GET | `/api/docs` | 문서·폴더 목록 |
| POST | `/api/doc` | 문서 생성 |
| PUT | `/api/doc` | 문서 수정 |
| DELETE | `/api/doc` | 휴지통 이동 |
| POST | `/api/asset` | 이미지 업로드 |
| POST | `/api/convert` | .docx/.pdf → Markdown 변환 |
| GET | `/api/trash` | 휴지통 목록 |
| POST | `/api/trash/restore` | 복원 |
| DELETE | `/api/trash` | 영구 삭제 |
| POST | `/api/chat` | LLM 질문 |
| GET | `/api/search` | RAG 검색 |

## 의존성 설치

```powershell
pip install -r requirements.txt
```
