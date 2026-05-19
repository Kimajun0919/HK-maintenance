# Link Download Release Guide

## Security Notes

- `HK-maintenance-local-<version>.zip` redacts document lines that look like credentials by default.
- Do not publish the original maintenance document folders directly. They may contain real account, server, VPN, or password data.
- `/api/folder/parse` is local-only by default. Remote folder parsing requires explicit `APP_ALLOW_REMOTE_FOLDER_PARSE=1`.

스토어에 올리지 않고 링크로 배포하는 방식입니다.

## 권장 배포 산출물

| 파일 | 대상 | 설명 |
|---|---|---|
| `HK-maintenance-local-<version>.zip` | Windows/macOS 공통 | 백엔드, 프론트엔드, 문서, 실행 스크립트 포함 |
| `HKMaintenance-Windows-<version>.zip` | Windows | WebView2 Windows 앱 |
| `HKMaintenance-macOS-<version>.zip` | macOS | 로컬 서버 URL을 여는 macOS 앱 런처 |
| `HKMaintenance-Android-<version>-debug.apk` | Android | 서버 URL을 여는 Android WebView 앱 |

## 다운로드 링크 운영

가장 쉬운 방법은 GitHub Releases입니다.

1. GitHub에 태그를 만듭니다.
2. `package-apps.yml` workflow가 산출물을 만듭니다.
3. 태그 실행이면 GitHub Release에 zip/apk 파일이 첨부됩니다.
4. 사용자에게 Release 링크를 전달합니다.

## 사용자가 해야 할 일

1. `HK-maintenance-local-<version>.zip`을 내려받아 압축 해제
2. Windows는 `start-local.bat`, macOS는 `start-local.command` 실행
3. Windows/macOS/Android 앱을 열어 서버에 접속

Android 실기기는 PC와 같은 네트워크에 있어야 하며, 앱 기본 주소는 에뮬레이터용 `http://10.0.2.2:7860`입니다. 실기기용 서버 주소 설정 UI는 다음 단계에서 추가할 수 있습니다.
