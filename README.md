# HK-maintenance

기업별 유지보수 매뉴얼, 유지보수 팁, 운영 참고자료를 보존형으로 정리한 문서 저장소입니다.

가장 중요한 기준은 원본 내용 누락 금지입니다. 원본 파일은 직접 수정하지 않고 `original_backup`에 보존했으며, AI/RAG/업무 인수인계용 정리본은 `organized_maintenance_docs_simple`을 기본 사용본으로 생성했습니다.

## 현재 산출물

| 경로 | 설명 |
|---|---|
| `original_backup/` | 원본 md 및 이미지 파일을 기존 경로 그대로 복사한 백업 |
| `organized_maintenance_docs_simple/` | 실제 사용을 위한 간소화 정리본 |
| `organized_maintenance_docs_simple/README.md` | 간소화 정리본 사용 안내 |
| `organized_maintenance_docs_simple/SIMPLIFY_CHANGELOG.md` | 간소화 이동/복사 내역 |
| `organized_maintenance_docs_simple/SIMPLIFY_VALIDATION_REPORT.md` | 간소화본 검증 결과 |
| `organized_maintenance_docs/` | 최초 생성한 표준형 정리본 |
| `organized_maintenance_docs/FILE_INVENTORY.md` | 전체 원본 파일 인벤토리 |
| `organized_maintenance_docs/CHANGELOG.md` | 표준형 정리본 파일별 변경/복사 내역 |
| `organized_maintenance_docs/VALIDATION_REPORT.md` | 표준형 정리본 누락 검증 및 이미지 연결 검증 결과 |
| `organize_maintenance_docs.py` | 표준형 정리본 재생성용 스크립트 |
| `simplify_maintenance_docs.py` | 간소화 정리본 재생성용 스크립트 |
| `integrate_hk_customer_info.py` | HK 공통매뉴얼의 고객사별 정보 분리 스크립트 |
| `rag_chatbot/` | 경량 로컬 LLM RAG 챗봇 |

## 정리 결과 요약

| 항목 | 수량 | 비고 |
|---|---:|---|
| 원본 md 파일 | 83 | 정리 md에 원문 전체 보존 |
| 원본 이미지 파일 | 61 | 정리본 이미지 자료 폴더에 모두 복사 |
| 간소화본 md 파일 | 133 | 유지보수 문서 83개 + HK 고객사별 추가 문서 46개 + 관리 문서 4개 |
| 간소화본 이미지 파일 | 61 | 원본 이미지 수와 동일 |
| 간소화본 빈 폴더 | 0 | 실제 내용이 있는 폴더만 생성 |
| 기업/분류 폴더 | 59 | `99_기타_미분류` 포함, `공통자료` 제외 |
| 공통자료 하위 폴더 | 3 | `보고서`, `링크모음`, `대량메일_레몬메일` |
| 확인 필요 항목 | 48 | 분류 불확실 또는 이미지 자동 매칭 없음 |
| HK 공통매뉴얼 반영 고객사 | 46 | `HK_CUSTOMER_INFO_INDEX.md` 기준 |

## 정리본 폴더 구조

기본 사용본은 빈 섹션 폴더를 제거한 간소화 구조입니다.

```text
organized_maintenance_docs_simple/
  기업명/
    기업명_주제_20260514.md
    images/
  공통자료/
    보고서/
    링크모음/
    대량메일_레몬메일/
  99_기타_미분류/
```

`organized_maintenance_docs/`에는 요청 당시의 표준형 구조도 보존되어 있습니다. 표준형은 모든 기업에 `01_기본정보`부터 `99_기타_미분류`까지 같은 섹션 폴더를 만든 버전입니다.

## 문서 사용 방법

1. 기업별 유지보수 문서는 `organized_maintenance_docs_simple/기업명`에서 바로 확인합니다.
2. 관련 이미지는 같은 기업 폴더의 `images/`에서 확인합니다.
3. 보고서, 링크 모음, 대량메일 자료는 `organized_maintenance_docs_simple/공통자료`에서 확인합니다.
4. 분류가 불확실한 문서는 `organized_maintenance_docs_simple/99_기타_미분류`를 확인합니다.
5. 각 정리 md의 `## 8. 원본 보존 내용`에는 원본 md 전체가 보존되어 있습니다.
6. `HK_유지보수팀_매뉴얼.md`에서 고객사별로 추가 추출한 내용은 각 기업 폴더의 `고객사_HK공통매뉴얼_추가정보_20260514.md`에서 확인합니다.

## 보존 및 검증 원칙

- 원본 파일은 `original_backup`에 보존되어 있습니다.
- 정리본은 원본을 삭제하거나 요약으로 대체하지 않고, 원본 본문 전체를 포함합니다.
- 각 정리 md에는 원본 경로, 원본 파일명, 원본 SHA-256을 기록했습니다.
- 이미지 파일은 삭제하지 않고 모두 복사했습니다.
- 간소화본에서는 이미지를 기업별 `images/` 폴더에 모았습니다.
- 이미지가 md와 자동 매칭되지 않은 경우에도 보존하고 검증 보고서에 확인 필요로 남겼습니다.

## 주의사항

- 계정 정보, 서버 정보, 경로, URL이 포함되어 있으므로 저장소 공개 범위를 주의해야 합니다.
- 자동 분류 결과는 검토용입니다. 의미가 불분명한 항목은 반드시 `VALIDATION_REPORT.md`의 확인 필요 사항을 확인해야 합니다.
- 표준형 정리본을 재생성하면 `organized_maintenance_docs`와 `original_backup`이 다시 만들어집니다.
- 간소화 정리본을 재생성하면 `organized_maintenance_docs_simple`이 다시 만들어집니다.

## 재생성

표준형 정리본을 다시 생성해야 할 때는 프로젝트 루트에서 아래 명령을 실행합니다.

```powershell
python organize_maintenance_docs.py
```

간소화 정리본을 다시 생성해야 할 때는 아래 명령을 실행합니다.

```powershell
python simplify_maintenance_docs.py
```

HK 공통매뉴얼의 고객사별 추가 정보를 다시 반영해야 할 때는 아래 명령을 실행합니다.

```powershell
python integrate_hk_customer_info.py
```

## RAG 챗봇

`rag_chatbot/`에는 `organized_maintenance_docs_simple`을 대상으로 동작하는 경량 RAG 챗봇이 있습니다.

- 권장 배포: Hugging Face Spaces Gradio
- 기본 LLM: `Qwen/Qwen2.5-0.5B-Instruct`
- 검색 방식: 순수 Python 문자 n-gram 검색
- LLM 로딩 실패 시: 검색 근거 기반 답변으로 자동 fallback

로컬 실행:

```powershell
cd rag_chatbot
pip install -r requirements.txt
python app.py
```

LLM 없이 검색 파이프라인만 확인:

```powershell
$env:USE_LLM='0'
python app.py
```
