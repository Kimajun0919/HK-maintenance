# HK Maintenance macOS App

SwiftUI + WKWebView 기반의 macOS 앱 골격입니다. 현재는 로컬 서버(`http://127.0.0.1:7860`)를 앱 창에서 여는 방식입니다.

## 실행 전 준비

루트에서 로컬 서버를 먼저 실행합니다.

```bash
chmod +x start-local.command stop-local.command
./start-local.command
```

## Xcode에서 열기

1. Xcode에서 `apps/macos/HKMaintenanceMacApp` 폴더를 새 macOS App 프로젝트로 만들거나 엽니다.
2. `Sources/HKMaintenanceMacApp/HKMaintenanceMacApp.swift` 내용을 앱 타깃에 추가합니다.
3. 실행하면 로컬 웹 UI가 앱 창에 표시됩니다.

## 다음 확장 포인트

- 앱 시작 시 `start-local.command` 자동 실행
- macOS `NSOpenPanel`로 폴더 선택
- 선택 경로를 `/api/folder/parse`에 전달
- 앱 종료 시 `stop-local.command` 호출
