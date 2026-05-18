# HK Maintenance Windows App

WPF + WebView2 기반 Windows 앱 골격입니다. 현재는 로컬 서버(`http://127.0.0.1:7860`)를 앱 창에서 여는 방식입니다.

## 실행 전 준비

루트에서 로컬 서버를 먼저 실행합니다.

```powershell
.\start-local.bat
```

## Visual Studio에서 실행

1. Visual Studio 2022 이상을 설치합니다.
2. `.NET Desktop Development` 워크로드가 필요합니다.
3. `apps/windows/HKMaintenanceWindowsApp/HKMaintenanceWindowsApp.csproj`를 엽니다.
4. 실행하면 로컬 웹 UI가 Windows 앱 창에 표시됩니다.

## 필요 런타임

WebView2 Runtime이 필요합니다. 최신 Windows 10/11에는 대부분 기본 설치되어 있습니다.

## 다음 확장 포인트

- 앱 시작 시 루트의 `start-local.bat` 자동 실행
- 앱 종료 시 `stop-local.bat` 호출
- Windows Folder Picker로 폴더 선택
- 선택 경로를 `/api/folder/parse`에 전달
