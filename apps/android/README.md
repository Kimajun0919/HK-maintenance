# HK Maintenance Android App

Kotlin WebView 기반 Android 앱 골격입니다. Android 기기에서 실행 중인 HK Maintenance 서버 URL을 열어 사용하는 구조입니다.

## 기본 주소

에뮬레이터에서 PC 로컬 서버에 접속할 때:

```text
http://10.0.2.2:7860
```

실기기에서 접속할 때는 PC와 같은 네트워크에 연결한 뒤 PC IP를 사용합니다.

```text
http://192.168.0.10:7860
```

## 구성

- `settings.gradle.kts`
- `build.gradle.kts`
- `app/build.gradle.kts`
- `app/src/main/AndroidManifest.xml`
- `app/src/main/java/com/hkmaintenance/MainActivity.kt`

Android Studio에서 `apps/android` 폴더를 열어 실행합니다.

## 폴더 파서 관련

현재 백엔드 폴더 파서는 서버가 접근 가능한 경로를 파싱합니다. Android 기기 내부 폴더를 직접 파싱하려면 다음 단계가 필요합니다.

- Android Storage Access Framework로 파일/폴더 선택
- 선택 파일을 서버로 업로드
- 서버에서 업로드 묶음을 `/api/folder/parse`와 같은 형태로 import

현재 골격은 서버 접속형 클라이언트입니다.
