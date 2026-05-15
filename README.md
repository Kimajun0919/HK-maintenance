# HK-maintenance

기업별 유지보수 매뉴얼, 운영 참고자료를 보존·관리하고 RAG 기반으로 검색·질문할 수 있는 웹 포털입니다.

## 구조

| 경로 | 설명 |
|---|---|
| `rag_chatbot/` | FastAPI 백엔드 + 웹 포털 (RAG 검색·질문, 문서 CRUD) |
| `organized_maintenance_docs_simple/` | 기본 문서 정리본 (Supabase 미사용 시 파일 소스) |
| `original_backup/` | 원본 md 및 이미지 파일 백업 |
| `deploy_hf_space.py` | Hugging Face Spaces 배포 번들 생성 스크립트 |
| `Dockerfile` | Render.com / 컨테이너 배포용 |
| `render.yaml` | Render.com Blueprint 설정 |
| `.github/workflows/deploy.yml` | GitHub Actions 자동 배포 (Render.com) |

## 주요 기능

- **문서 관리**: 폴더·파일 CRUD, 이름 변경, 드래그 정렬, 고정 핀
- **첨부 변환**: `.md` / `.docx` / `.pdf` 업로드 시 Markdown 자동 변환
- **이미지 관리**: 에디터 내 이미지 업로드, 첨부 이미지 삭제
- **휴지통**: 삭제 후 30일 보관, 복원·영구 삭제
- **RAG 검색**: 문자 n-gram 기반 문서 검색
- **LLM 질문**: 외부 API 연동 (Claude, OpenAI-compatible, Groq, Ollama, Luxia 등)
- **API 관리**: 여러 LLM API 등록·선택 (인증 헤더·엔드포인트 커스텀)
- **폴더 관리 모달**: Windows 탐색기 스타일, 그리드/리스트 전환

## 배포

### Render.com (권장)

GitHub 연동 자동 배포. 카드 불필요, 무료 티어 사용 가능.

1. [render.com](https://render.com) → New → Blueprint → 이 레포 연결
2. `SUPABASE_DB_URL` 환경변수 직접 입력
3. `main` 브랜치 푸시 시 자동 재배포

### Hugging Face Spaces (보조)

```powershell
# .env에 HF_TOKEN, HF_SPACE_ID, HF_DEPLOY=1 설정 후
python scripts/deploy_hf_space.py
```

HuggingFace Space 시크릿에 `SUPABASE_DB_URL`, `SUPABASE_SEED_FROM_FILES=0` 추가 필요.

## 로컬 실행

```powershell
cd rag_chatbot
python app.py
# http://127.0.0.1:7860
```

### 필수 환경변수 (.env)

```env
SUPABASE_DB_URL=postgresql://...
DOC_STORAGE=supabase
SUPABASE_SEED_FROM_FILES=0
```

## 주의사항

- 계정·서버·경로 정보가 문서에 포함되어 있으므로 저장소를 **Private**으로 유지하세요.
- `.env` 파일은 `.gitignore`에 포함되어 커밋되지 않습니다.
