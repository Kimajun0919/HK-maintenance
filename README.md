# HK-maintenance

기업별 유지보수 매뉴얼, 운영 참고자료를 보존·관리하고 RAG 기반으로 검색·질문할 수 있는 웹 포털입니다.

## 구조

| 경로 | 설명 |
|---|---|
| `backend/` | FastAPI 백엔드 (RAG 검색·질문, 문서 CRUD API) |
| `frontend/` | React 웹 포털 (CDN 기반, 빌드 없음) |
| `organized_maintenance_docs_simple/` | 기본 문서 정리본 (Supabase 미사용 시 파일 소스) |
| `original_backup/` | 원본 md 및 이미지 파일 백업 |
| `scripts/deploy_hf_space.py` | Hugging Face Spaces 배포 번들 생성 스크립트 |
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

### 더블클릭으로 실행하기

Windows에서는 루트 폴더의 `start-local.bat`을 더블클릭하면 로컬 서버를 실행하고 브라우저를 엽니다.

```text
start-local.bat
```

서버를 끄려면 실행 창에서 `Ctrl + C`를 누르거나, 루트 폴더의 `stop-local.bat`을 더블클릭합니다.

```text
stop-local.bat
```

`start-local.bat`은 다음 작업을 자동으로 처리합니다.

- `.venv` 가상환경이 없으면 생성
- `backend\requirements.txt` 패키지 설치
- `http://127.0.0.1:7860` 브라우저 열기
- `python backend\app.py` 서버 실행
- 이미 `7860` 포트에 서버가 떠 있으면 새로 띄우지 않고 브라우저만 열기

macOS에서는 루트 폴더의 `start-local.command`를 더블클릭하면 같은 방식으로 실행됩니다. 처음 한 번은 터미널에서 실행 권한을 부여해야 할 수 있습니다.

```bash
chmod +x start-local.command stop-local.command
```

이후에는 Finder에서 더블클릭으로 실행합니다.

```text
start-local.command
```

서버를 끄려면 실행 창에서 `Ctrl + C`를 누르거나, 루트 폴더의 `stop-local.command`를 더블클릭합니다.

```text
stop-local.command
```

아래는 수동 실행이 필요할 때 참고하는 절차입니다.

아래 절차는 Windows PowerShell 기준입니다. 프로젝트 폴더가 `C:\test\HK-maintenance`에 있다고 가정합니다.

### 1. 프로젝트 폴더로 이동

```powershell
cd C:\test\HK-maintenance
```

### 2. Python 버전 확인

```powershell
python --version
```

Python이 없다고 나오면 Python 3.11 이상을 설치한 뒤 PowerShell을 새로 열어 다시 확인합니다.

### 3. 가상환경 만들기

처음 한 번만 실행합니다.

```powershell
python -m venv .venv
```

가상환경을 켭니다.

```powershell
.\.venv\Scripts\Activate.ps1
```

PowerShell 실행 정책 때문에 막히면 아래 명령을 한 번 실행한 뒤 다시 활성화합니다.

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

정상적으로 켜지면 프롬프트 앞에 `(.venv)`가 붙습니다.

### 4. 패키지 설치

```powershell
pip install -r backend\requirements.txt
```

### 5. 환경변수 파일 준비

루트 폴더에 `.env` 파일이 있어야 합니다. 이미 있으면 그대로 사용합니다.

없으면 예시 파일을 복사합니다.

```powershell
Copy-Item .env.example .env
```

Supabase를 사용하는 경우 `.env`에 아래 값이 필요합니다.

```env
DOC_STORAGE=supabase
SUPABASE_DB_URL=postgresql://...
SUPABASE_SEED_FROM_FILES=0
```

Supabase 없이 로컬 파일만으로 테스트하려면 `SUPABASE_DB_URL`을 비워두거나 주석 처리하고, `DOC_STORAGE`도 비워둡니다.

### 6. 로컬 서버 실행

```powershell
python backend\app.py
```

정상 실행되면 브라우저에서 아래 주소로 접속합니다.

```text
http://127.0.0.1:7860
```

같은 네트워크의 다른 PC나 모바일에서 접속하려면 실행 중인 PC의 내부 IP를 사용합니다.

```text
http://내_PC_IP:7860
```

예를 들어 PC IP가 `192.168.0.10`이면 `http://192.168.0.10:7860`입니다.

### 7. 서버 상태 확인

다른 PowerShell 창에서 확인할 수 있습니다.

```powershell
Invoke-WebRequest http://127.0.0.1:7860/healthz -UseBasicParsing
```

`"ok": true`가 보이면 서버가 정상입니다.

### 8. Ollama로 AI 질문 사용하기

Render 같은 외부 서버에서는 로컬/Tailscale Ollama 주소에 접근하지 못할 수 있습니다. Ollama를 쓰려면 이 앱도 로컬에서 실행하는 것이 가장 단순합니다.

앱 화면에서 `API 관리`를 열고 새 API를 추가합니다.

| 항목 | 값 |
|---|---|
| 유형 | `OpenAI-compatible` |
| Base URL | `http://100.84.152.5:11434/v1` |
| API Key | 비워둠 |
| 인증 헤더 이름 | 비워둠 |
| 채팅 엔드포인트 경로 | 비워둠 또는 `/chat/completions` |
| 모델 | `hermes3:latest` 또는 `llama3.1:8b` 등 Ollama에 설치된 모델명 |

주의할 점:

- Base URL에 이미 `/v1`이 들어가 있으면 채팅 경로에 `/v1/chat/completions`를 넣지 않습니다.
- 모델명을 비워두면 기본값 `gpt-4o-mini`가 전송될 수 있고, Ollama에 없는 모델이라 실패합니다.
- Ollama 서버가 다른 PC에 있으면 방화벽에서 `11434` 포트 접근이 허용되어야 합니다.

Ollama 연결만 따로 확인하려면:

```powershell
Invoke-WebRequest http://100.84.152.5:11434/v1/models -UseBasicParsing
```

모델 목록이 JSON으로 나오면 연결은 정상입니다.

### 8-1. OpenAI-compatible / Luxia 등 다른 LLM API 설정

Claude를 제외한 대부분의 외부 LLM API는 `OpenAI-compatible` 유형으로 등록합니다. 공급자마다 Base URL, 인증 헤더, 채팅 경로만 다릅니다.

| 공급자 예시 | Base URL | 인증 헤더 이름 | 채팅 엔드포인트 경로 |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | 비워둠 | 비워둠 |
| Groq | `https://api.groq.com/openai/v1` | 비워둠 | 비워둠 |
| Ollama | `http://localhost:11434/v1` 또는 Tailscale 주소 | 비워둠 | 비워둠 |
| LM Studio | `http://localhost:1234/v1` | 비워둠 | 비워둠 |
| Luxia | `https://bridge.luxiacloud.com/luxia/v1` | `apikey` | `/chat` |

호환성 기준:

- 기본 경로는 `/chat/completions`입니다.
- 채팅 경로에 전체 URL을 넣어도 됩니다.
- Base URL이 `/v1`로 끝나는데 경로를 `/v1/chat/completions`로 넣어도 중복 `/v1/v1`이 생기지 않도록 처리합니다.
- 응답은 `choices[0].message.content`, `choices[0].text`, `answer`, `response`, `output_text`, `content`, `message`, `result` 형태를 모두 읽습니다.
- `apikey`처럼 Bearer가 아닌 인증은 `인증 헤더 이름`에 해당 헤더명을 넣고 API Key에 값을 넣습니다.
- 일반 Bearer 인증은 `인증 헤더 이름`을 비워두면 됩니다.

### 9. 서버 종료

서버를 실행한 PowerShell 창에서 `Ctrl + C`를 누릅니다.

백그라운드로 실행한 서버를 PID로 종료하려면:

```powershell
Stop-Process -Id 26156
```

PID는 실행할 때마다 바뀝니다. 현재 `7860` 포트를 사용하는 프로세스를 찾으려면:

```powershell
Get-NetTCPConnection -LocalPort 7860 | Select-Object LocalAddress,LocalPort,State,OwningProcess
```

### 자주 나는 문제

#### `address already in use` 또는 `10048` 오류

이미 `7860` 포트를 쓰는 서버가 떠 있는 상태입니다. 기존 서버를 종료하거나 다른 포트를 씁니다.

```powershell
$env:APP_PORT=7861
python backend\app.py
```

이 경우 접속 주소는 `http://127.0.0.1:7861`입니다.

#### 브라우저 콘솔에 `favicon.ico 404`가 보임

기능에는 영향이 없습니다. 현재 서버는 `/favicon.ico` 요청에 빈 응답을 주도록 처리되어 있습니다.

#### `A listener indicated an asynchronous response...` 콘솔 오류

대부분 Chrome 확장 프로그램에서 발생합니다. 시크릿 창에서 확장 프로그램을 끄고 접속해 확인합니다.

#### AI 질문은 안 되고 검색만 됨

API 관리에서 선택된 API가 있는지, 모델명이 Ollama에 실제로 있는 모델명인지 확인합니다.

```powershell
Invoke-WebRequest http://100.84.152.5:11434/v1/models -UseBasicParsing
```

#### Render에서는 Ollama가 안 됨

Render 서버는 사용자의 로컬 PC 또는 Tailscale 사설 IP `100.x.x.x` 대역에 접근하지 못할 수 있습니다. 이 경우 앱을 로컬에서 실행하거나, Render에서도 접근 가능한 공개 LLM API를 사용해야 합니다.

## 주의사항

- 계정·서버·경로 정보가 문서에 포함되어 있으므로 저장소를 **Private**으로 유지하세요.
- `.env` 파일은 `.gitignore`에 포함되어 커밋되지 않습니다.
