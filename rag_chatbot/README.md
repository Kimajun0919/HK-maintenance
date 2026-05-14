# HK Maintenance RAG Chatbot

`organized_maintenance_docs_simple` 문서를 대상으로 동작하는 경량 로컬 LLM RAG 챗봇입니다.

## 권장 배포

무료 배포는 Hugging Face Spaces의 Gradio Space를 권장합니다.

- 기본 문서 경로: `../organized_maintenance_docs_simple`
- 기본 LLM: `HuggingFaceTB/SmolLM2-135M-Instruct`
- 검색 방식: 순수 Python 문자 n-gram 검색
- 응답 방식: 검색 근거를 먼저 즉시 표시하고, LLM 답변이 준비되면 같은 답변 영역에 추가 표시
- LLM 로딩 실패 시: 검색된 근거 기반 답변만 유지

## 로컬 실행

가장 가벼운 테스트는 LLM 없이 검색 RAG만 실행하는 방식입니다. 문서 검색과 Gradio UI를 먼저 확인할 때 사용합니다.

```powershell
cd rag_chatbot
.\start_local.ps1
```

실행 후 브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:7860
```

검색 파이프라인만 빠르게 확인하려면 아래 명령을 실행합니다.

```powershell
.\smoke_test.ps1
```

로컬 LLM까지 설치해서 실행하려면 아래 명령을 사용합니다. Torch와 모델 파일을 내려받기 때문에 시간이 오래 걸릴 수 있습니다.

```powershell
.\start_local_llm.ps1
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
| `LOCAL_LLM_MODEL` | `HuggingFaceTB/SmolLM2-135M-Instruct` | 사용할 로컬 LLM |
| `USE_LLM` | `1` | `0`이면 LLM 없이 근거 기반 검색 답변만 사용 |
| `MAX_NEW_TOKENS` | `180` | 생성 답변 최대 토큰 |

## 로컬 테스트 완료 상태

- 검색 스모크 테스트: 통과
- 로컬 Gradio UI: `http://127.0.0.1:7860` 응답 확인
- 기본 로컬 빠른 실행 모드: `USE_LLM=0`
- Space 기본 동작: 검색 답변 먼저 표시 후 LLM 답변 지연 업데이트

## 주의사항

- 첫 실행 시 모델 다운로드 때문에 시간이 걸릴 수 있습니다.
- 무료 CPU 환경에서는 답변 생성이 느릴 수 있습니다.
- 문서에 계정, 서버, 경로 정보가 포함되어 있으므로 Space 공개 범위를 반드시 확인해야 합니다.
