# HK Maintenance RAG / Search Architecture

이 문서는 현재 HK-maintenance 프로젝트의 검색/RAG 구조를 설명합니다. 이 프로젝트의 검색은 크게 두 가지 모드로 동작합니다.

- `RAG_STARTUP_INDEX=0`: Render free tier처럼 메모리가 작은 서버용입니다. 시작 시 전체 청크 인덱스를 만들지 않고, Supabase DB에서 문서 레코드를 직접 검색합니다.
- `RAG_STARTUP_INDEX=1`: 메모리가 충분한 서버용입니다. 시작 시 문서를 청크로 읽고 BM25, 문자 n-gram, 선택적 임베딩을 사용해 하이브리드 검색을 수행합니다.

`GET /api/search`는 검색 결과를 반환하는 API입니다. 자연어 답변 생성은 `POST /api/chat`에서 선택적으로 수행합니다.

## 현재 데이터 구조

Supabase에는 문서형 검색 데이터와 CSV 접수내역 구조화 데이터가 함께 들어갑니다.

| 테이블 | 역할 |
|---|---|
| `maintenance_docs` | Markdown 문서 원문과 폴더 메타데이터 |
| `maintenance_docs_folders` | 앱에서 쓰는 폴더 구조 |
| `maintenance_docs_assets` | 문서 첨부/이미지 자산 |
| `maintenance_docs_chunks` | 청크, 검색용 정규화 필드, 선택적 임베딩 |
| `maintenance_requests` | `유지보수 접수내역.csv` 30개 컬럼을 보존한 구조화 테이블 |
| `maintenance_requests_imports` | CSV import 이력 |

CSV import 시에는 두 종류의 데이터가 생성됩니다.

1. `maintenance_requests`에 원본 CSV 컬럼 구조를 유지한 구조화 레코드가 저장됩니다.
2. `maintenance_docs`에는 검색/RAG에 쓰기 쉬운 Markdown 문서가 `유지보수_접수내역/접수_{번호}.md` 형식으로 저장됩니다.

이렇게 분리한 이유는 현재 앱 검색은 문서형 RAG에 맞춰져 있고, 향후 외부 DB나 업무 DB와 연결할 때는 `maintenance_requests` 같은 구조화 테이블을 기준으로 안정적으로 매핑할 수 있기 때문입니다.

## Supabase 프로필

한 코드베이스에서 여러 Supabase DB를 분리해서 쓸 수 있습니다. DB 선택은 사용자 화면에서 바꾸는 방식이 아니라, 배포 인스턴스별 환경변수로 고정하는 방식입니다.

```env
SUPABASE_PROFILE=main
SUPABASE_PROFILE_STRICT=1
SUPABASE_DB_URL_MAIN=postgresql://...
```

```env
SUPABASE_PROFILE=fresh
SUPABASE_PROFILE_STRICT=1
SUPABASE_DB_URL_FRESH=postgresql://...
```

설정 로딩 규칙은 [config.py](./config.py)에 있습니다.

- `SUPABASE_PROFILE=main`이면 `SUPABASE_DB_URL_MAIN`을 우선 사용합니다.
- `SUPABASE_PROFILE=fresh`이면 `SUPABASE_DB_URL_FRESH`를 우선 사용합니다.
- `SUPABASE_PROFILE_STRICT=1`이면 프로필 URL이 없을 때 기존 `SUPABASE_DB_URL`로 fallback하지 않습니다.

운영에서는 `SUPABASE_PROFILE_STRICT=1`을 권장합니다. 잘못된 DB에 접속하는 사고를 막기 위한 설정입니다.

## 저메모리 모드

Render free tier는 메모리가 512Mi라서 전체 청크 인덱스, n-gram 인덱스, 임베딩 모델을 한 번에 올리기 어렵습니다. 이 프로젝트의 기본 Docker/Render 설정은 아래처럼 맞춰져 있습니다.

```env
RAG_STARTUP_INDEX=0
RAG_ENABLE_NGRAM_INDEX=0
RAG_ENABLE_LEGACY_INDEX=0
EMBEDDING_BACKEND=none
```

이 모드의 동작은 다음과 같습니다.

- 앱 시작 시 `load_chunks()`를 실행하지 않습니다.
- `/api/meta`의 `chunkCount`가 `0`으로 보일 수 있습니다. 이는 정상입니다.
- `/api/search`는 `maintenance_docs`를 DB에서 직접 조회해 결과를 만듭니다.
- `/api/chat`도 검색 컨텍스트를 DB 기반 검색 결과에서 가져옵니다.
- `/api/search-index/rebuild`는 청크 인덱스를 메모리에 재생성하지 않고 no-op에 가깝게 처리됩니다.

즉, `chunkCount=0`이어도 문서 검색이 DB 기반으로 동작하면 정상 상태입니다.

## 일반 서버 모드

메모리가 1GB 이상인 서버에서는 시작 시 인메모리 검색 인덱스를 만들 수 있습니다.

```env
RAG_STARTUP_INDEX=1
RAG_ENABLE_NGRAM_INDEX=0
RAG_ENABLE_LEGACY_INDEX=0
EMBEDDING_BACKEND=none
```

2GB 이상이면 문자 n-gram 인덱스까지 켤 수 있습니다.

```env
RAG_STARTUP_INDEX=1
RAG_ENABLE_NGRAM_INDEX=1
RAG_ENABLE_LEGACY_INDEX=1
EMBEDDING_BACKEND=none
```

semantic embedding 실험은 더 많은 메모리가 필요합니다.

```env
RAG_STARTUP_INDEX=1
RAG_ENABLE_NGRAM_INDEX=1
RAG_ENABLE_LEGACY_INDEX=1
EMBEDDING_BACKEND=sentence-transformers
```

`sentence-transformers`를 쓰려면 추가 의존성이 필요합니다.

```powershell
pip install -r backend/requirements-embeddings.txt
```

Render free tier에서는 이 설정을 권장하지 않습니다.

## 검색 파이프라인

### DB 기반 검색

`RAG_STARTUP_INDEX=0`일 때의 경로입니다.

```mermaid
flowchart LR
    U[사용자 검색어] --> N[검색어 정규화]
    N --> DB[Supabase maintenance_docs 조회]
    DB --> S[문서 제목/폴더/본문 점수화]
    S --> C[대표 matched_text 생성]
    C --> R[문서 단위 검색 결과 반환]
```

주요 구현 위치:

| 파일 | 역할 |
|---|---|
| [storage.py](./storage.py) | DB 문서 조회, DB 기반 검색 |
| [rag.py](./rag.py) | low-memory retrieval fallback |
| [app.py](./app.py) | `/api/search`, `/api/chat`, `/api/meta` |

### 인메모리 하이브리드 검색

`RAG_STARTUP_INDEX=1`일 때의 경로입니다.

```mermaid
flowchart LR
    U[사용자 검색어] --> N[검색어 정규화]
    N --> B[BM25]
    N --> G[문자 n-gram]
    B --> C[후보 청크 선택]
    G --> C
    C --> E[선택적 임베딩 재순위화]
    E --> D[문서 단위 그룹화]
    D --> R[검색 결과 반환]
```

검색 단위는 청크이지만, API 응답은 문서 단위로 그룹화됩니다. 같은 문서에서 여러 청크가 매칭되면 가장 높은 점수의 청크가 대표 결과가 되고 나머지는 `related_chunks`에 들어갑니다.

## 정규화와 청크

정규화 함수는 [rag.py](./rag.py)의 `normalize_search_text`에 있습니다.

| 입력 특징 | 처리 |
|---|---|
| 영문 대소문자 | 소문자로 변환 |
| `A/S`, `AS`, `a.s`, `에이에스` | `as`로 통일 |
| 특수문자 | 검색에 불필요한 문자는 공백 처리 |
| 다중 공백 | 단일 공백으로 축약 |
| 한국어/영문/숫자 | 유지 |
| 원본 문서 | 수정하지 않음 |

청크 분할은 [rag.py](./rag.py)의 `split_markdown`에서 수행합니다.

1. Markdown heading을 기준으로 섹션을 나눕니다.
2. 긴 섹션은 최대 길이 기준으로 다시 나눕니다.
3. 각 청크에 원본 문서 메타데이터를 붙입니다.
4. 검색용 `normalized_body`, `compact_body`를 별도로 만듭니다.

## 점수 계산

인메모리 검색의 기본 점수는 [settings.json](./settings.json)의 `search.weights`에서 조정합니다.

```txt
final_score =
  bm25_score * bm25_weight
+ ngram_score * ngram_weight
+ embedding_score * embedding_weight
+ field_boost
+ exact_match_boost
+ recency_boost
```

주요 설정:

| 설정 | 설명 |
|---|---|
| `candidate_limit` | BM25/n-gram으로 먼저 고르는 후보 수 |
| `weights.bm25` | 키워드 점수 비중 |
| `weights.ngram` | 문자 부분 일치 점수 비중 |
| `weights.embedding` | 임베딩 재순위화 점수 비중 |
| `field_boosts` | 제목, 파일명, 폴더, heading 매칭 가산점 |
| `synonyms` | 선택적 검색어 확장 사전 |

동의어가 없어도 검색은 원본 검색어로 정상 동작합니다.

## 임베딩과 벡터 인덱스

임베딩은 답변 생성용이 아니라 후보 청크 재순위화용입니다.

| 설정 | 동작 |
|---|---|
| `EMBEDDING_BACKEND=none` | 임베딩 비활성화 |
| `EMBEDDING_BACKEND=hash` | 테스트용 deterministic embedding |
| `EMBEDDING_BACKEND=sentence-transformers` | 다국어 sentence-transformers 모델 사용 |

청크 벡터를 Supabase에 다시 만들려면 다음 명령을 사용합니다.

```powershell
python scripts/rebuild_vector_index.py
```

서버 실행 중에는 아래 API도 사용할 수 있습니다.

```txt
POST /api/search-index/rebuild
```

저메모리 모드에서는 이 API가 전체 인메모리 인덱스를 재생성하지 않습니다. Render free tier에서 OOM을 피하기 위한 동작입니다.

## 주요 API

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/api/meta` | 현재 프로필, 문서 수, 청크 수 등 상태 |
| `GET` | `/api/search?q=...` | 문서 검색 |
| `POST` | `/api/chat` | 검색 결과 기반 선택적 답변 생성 |
| `POST` | `/api/search-index/rebuild` | 검색 인덱스 재생성 |
| `GET` | `/api/folders` | 폴더 목록 |
| `GET` | `/api/docs` | 문서 목록 |
| `GET` | `/api/maintenance-requests/search?q=...` | 구조화 접수내역 검색 |

`/api/search` 응답 예시:

```json
{
  "query": "에어컨 냄새",
  "answer": "",
  "results": [
    {
      "document_id": "doc_id",
      "title": "접수_75",
      "filename": "접수_75.md",
      "folder": "유지보수_접수내역",
      "matched_heading": "접수 정보",
      "matched_text": "접수 내용 일부...",
      "score": 0.87,
      "score_detail": {
        "bm25": 0.72,
        "ngram": 0.64,
        "embedding": 0.0,
        "field_boost": 0.25,
        "exact_match_boost": 0.03,
        "recency_boost": 0.0
      },
      "related_chunks": []
    }
  ]
}
```

## CSV 접수내역 import

새 CSV를 넣을 때는 구조를 유지한 채 import합니다.

```powershell
python scripts/import_maintenance_requests_csv.py "유지보수 접수내역.csv"
```

dry run:

```powershell
python scripts/import_maintenance_requests_csv.py "유지보수 접수내역.csv" --dry-run
```

새 Supabase DB를 처음 만들 때:

```powershell
python scripts/bootstrap_fresh_supabase.py --profile fresh
```

CSV까지 바로 넣을 때:

```powershell
python scripts/bootstrap_fresh_supabase.py --profile fresh --csv "유지보수 접수내역.csv"
```

## 테스트

검색 단위 테스트:

```powershell
python -m unittest backend.test_hybrid_search
```

검색 품질 평가:

```powershell
python backend/eval_hybrid_search.py
```

API 디버깅:

```txt
GET /api/search?q=물이 새요&debug=true
```

debug 응답에는 정규화 검색어, 확장어, 후보 수, 임베딩 사용 여부, 최종 점수와 세부 점수가 포함됩니다.

## 운영 체크리스트

- Render free tier에서는 `RAG_STARTUP_INDEX=0`, `EMBEDDING_BACKEND=none`을 유지합니다.
- `chunkCount=0`은 저메모리 모드에서 정상일 수 있습니다. `docCount`와 검색 결과를 함께 확인합니다.
- DB별 앱을 따로 띄울 때는 Render 서비스를 두 개 만들고 `SUPABASE_PROFILE`과 프로필별 URL만 다르게 넣습니다.
- `SUPABASE_PROFILE_STRICT=1`을 유지해 다른 DB로 fallback되는 것을 막습니다.
- Supabase 접속 문자열, service role key, DB 비밀번호는 README나 git에 넣지 않습니다.

## 핵심 파일

| 파일 | 역할 |
|---|---|
| [rag.py](./rag.py) | 정규화, 청크 분할, 검색, RAG fallback |
| [storage.py](./storage.py) | Supabase 문서 저장/조회, DB 기반 검색 |
| [maintenance_requests.py](./maintenance_requests.py) | CSV 접수내역 구조화 import/search |
| [config.py](./config.py) | Supabase 프로필과 RAG 환경변수 |
| [app.py](./app.py) | API 엔드포인트 |
| [settings.json](./settings.json) | 검색 가중치와 동의어 설정 |
| [test_hybrid_search.py](./test_hybrid_search.py) | 검색 단위 테스트 |
