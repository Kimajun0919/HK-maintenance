# HK Maintenance RAG Chatbot

`organized_maintenance_docs_simple` 문서를 대상으로 동작하는 경량 로컬 LLM RAG 챗봇입니다.

## 권장 배포

무료 배포는 Hugging Face Spaces의 Gradio Space를 권장합니다.

- 기본 문서 경로: `../organized_maintenance_docs_simple`
- 기본 LLM: `Qwen/Qwen2.5-0.5B-Instruct`
- 검색 방식: 순수 Python 문자 n-gram 검색
- LLM 로딩 실패 시: 검색된 근거 기반 답변으로 자동 fallback

## 로컬 실행

```powershell
cd rag_chatbot
pip install -r requirements.txt
python app.py
```

## Hugging Face Spaces 배포

1. Hugging Face에서 새 Space 생성
2. SDK는 `Gradio` 선택
3. 이 폴더의 `app.py`, `requirements.txt`와 상위 문서 폴더 `organized_maintenance_docs_simple`를 함께 업로드
4. Space 실행

## 환경 변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DOCS_DIR` | `../organized_maintenance_docs_simple` | RAG 대상 문서 폴더 |
| `LOCAL_LLM_MODEL` | `Qwen/Qwen2.5-0.5B-Instruct` | 사용할 로컬 LLM |
| `USE_LLM` | `1` | `0`이면 LLM 없이 근거 기반 검색 답변만 사용 |
| `MAX_NEW_TOKENS` | `320` | 생성 답변 최대 토큰 |

## 주의사항

- 첫 실행 시 모델 다운로드 때문에 시간이 걸릴 수 있습니다.
- 무료 CPU 환경에서는 답변 생성이 느릴 수 있습니다.
- 문서에 계정, 서버, 경로 정보가 포함되어 있으므로 Space 공개 범위를 반드시 확인해야 합니다.
