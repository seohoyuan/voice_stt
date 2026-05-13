# APK_BUILD.md - GitHub Actions로 APK 만들기

이 프로젝트는 로컬 PC에 Android Studio, SDK, NDK를 직접 설치하지 않고도 GitHub Actions에서 APK를 만들 수 있게 준비되어 있습니다.

## 1. 한 번만 할 일

1. GitHub에 새 저장소를 만듭니다.
2. `C:\Users\FSC22-06\cprojects\idea` 프로젝트를 그 저장소에 올립니다.
3. GitHub 저장소의 `Actions` 탭으로 갑니다.
4. `Build Android APK` 워크플로우를 선택합니다.
5. `Run workflow`를 누릅니다.

## 2. APK 받기

빌드가 끝나면 workflow run 페이지 아래쪽의 `Artifacts`에 다음 파일이 생깁니다.

```text
voice2spec-debug-apk
```

이 artifact를 다운로드해서 압축을 풀면 `*.apk` 파일이 있습니다.

## 3. 갤럭시 폴드4에 설치

1. APK 파일을 폴드4로 옮깁니다.
2. 파일 앱에서 APK를 누릅니다.
3. "알 수 없는 앱 설치" 권한을 허용합니다.
4. 앱을 설치합니다.
5. 앱 실행 후 마이크 권한을 허용합니다.

## 4. 첫 번째 검증 목표

먼저 STT까지 욕심내지 말고 아래만 확인합니다.

```text
앱 실행
-> 녹음 시작
-> 녹음 중지
-> WAV 파일 저장 경로가 화면에 표시됨
```

저장 위치는 앱 내부 저장소입니다.

```text
<user_data_dir>/output/recordings/<timestamp>_<uuid>.wav
<user_data_dir>/output/latest_recording.txt
```

갤럭시 폴드4에서는 대체로 아래와 같은 private 경로입니다.

```text
/data/user/0/org.voice2spec.voice2spec/files/app/output/recordings/
```

이 경로는 일반 파일 앱에서 바로 보이지 않을 수 있습니다. 그래서 앱 화면의 "최근 녹음" 줄과 결과창에 마지막 WAV 경로를 표시합니다.

사용자가 직접 확인할 수 있도록 녹음이 끝나면 public 다운로드 폴더에도 WAV 복사본을 만듭니다.

```text
Download/Voice2Spec/<timestamp>_<uuid>.wav
```

갤럭시 폴드4에서는 "내 파일" 앱에서 `다운로드 > Voice2Spec` 폴더를 확인합니다.

## 5. STT 파일 준비

STT까지 확인하려면 APK 안에 다음 파일이 필요합니다.

```text
bin/whisper-cli
models/whisper-small-q5_1.bin
```

주의: Windows/PC용 `whisper-cli.exe`는 Android APK 안에서 실행되지 않습니다. 갤럭시 폴드4는 Android arm64 기기이므로 Android arm64용 whisper.cpp 실행 파일 또는 라이브러리가 필요합니다.

## 6. 지금 상태

현재 GitHub Actions workflow는 APK 빌드 파이프라인을 준비합니다.

```text
녹음 APK 빌드: 준비됨
Android RECORD_AUDIO 권한: 준비됨
WAV 저장: 코드 준비됨
STT 어댑터: 코드 준비됨
Android용 whisper 바이너리/모델 포함: 아직
```
