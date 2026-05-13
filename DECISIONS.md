# DECISIONS.md - Voice2Spec 결정 기록

## 2026-05-12

- D1: 현재 작업 폴더는 빈 상태에서 시작했다. 명세의 "첫 작업 우선순위"에 따라 문서와 M1 골격을 먼저 생성한다.
- D2: 로컬 PATH 및 일반 설치 경로에서 Android SDK, Gradle, Java를 찾지 못했다. 따라서 이 환경에서는 M1 빌드/스크린샷 게이트를 직접 통과시킬 수 없으며, 프로젝트 파일 생성 후 검증 시도 결과를 보고한다.
- D3: 네트워크 프라이버시 기본값을 지키기 위해 앱 매니페스트에는 `INTERNET` 권한을 추가하지 않는다. 모델 다운로드 화면은 M4에서 사용자 동의 플로우와 함께 별도 설계한다.
- D4: M1에서는 실제 녹음/STT/LLM 구현 대신 각 에이전트의 독립 테스트가 가능한 인터페이스와 데이터 모델을 먼저 둔다. 실제 구현은 M2-M5에서 교체한다.
- D5: Gradle 버전 카탈로그는 오프라인 생성 가능한 표준 Android/Compose 조합으로 둔다. 실제 빌드 환경에서 SDK/Gradle 호환성 문제가 확인되면 이 파일을 우선 조정한다.
- D6: `gradle :app:assembleDebug` 검증을 시도했지만 `gradle` 실행 파일이 없어 실패했다. Android SDK/JDK/Gradle이 있는 환경에서 M1 빌드와 스크린샷 게이트를 재실행해야 한다.
- D7: 사용자는 Python에 익숙하고 Kotlin을 배우며 진행하기로 했다. 구현은 Kotlin + Compose로 유지하고, 설명은 Python식 의사코드와 Kotlin 실제 코드를 함께 연결해서 제공한다.
- D8: 설치 부담을 줄이기 위해 우선 Python 프로토타입을 만든 뒤, 필요해지는 시점에 Kivy/Buildozer 또는 Android 네이티브로 APK 전환을 검토한다. 기존 Kotlin 골격은 삭제하지 않고 참고 구현으로 보존한다.
- D9: Python 프로토타입의 다음 성장 단계는 외부 의존성 없이 CLI를 개인 도구처럼 쓰는 것이다. `new`, `list`, `show` 명령을 추가하고, Markdown/JSON 저장소를 목록/검색 가능하게 확장했다.
- D10: LLM 연결 전에도 결과 품질을 올리기 위해 규칙 기반 도메인 템플릿을 추가했다. 현재 독서 기록, 지역 배달/주문, 회의 정리, 일반 아이디어를 감지해 서로 다른 화면/데이터 모델/사용자 스토리를 생성한다.
- D11: 아이디어 관리는 영구 삭제 대신 soft delete를 기본으로 한다. `delete`는 Markdown/JSON 파일을 `output/trash/`로 옮기고, `restore`로 복구할 수 있게 한다.
- D12: Recorder 단계는 Python에서 `sounddevice`를 선택 의존성으로 사용한다. 기본 출력은 STT 준비에 맞춘 16kHz mono WAV이며, STT 자체는 아직 mock으로 남긴다.
- D13: 실제 목표 기기는 Galaxy Fold4 Android APK다. PC `sounddevice` 녹음은 개발용 보조 경로로만 두고, 모바일 앱 녹음은 `android.media.AudioRecord`를 PyJNIus로 호출하는 `AndroidWavRecorder`를 기준으로 한다.
- D14: STT는 `WhisperCppTranscriber` 어댑터로 연결한다. 앱 코드는 `bin/whisper-cli`와 `models/whisper-small-q5_1.bin`을 찾고, 파일이 없으면 녹음 파일은 보존한 채 STT 설정 필요 메시지를 보여준다.
- D15: 로컬 설치 부담을 줄이기 위해 APK 빌드는 GitHub Actions + Buildozer로 먼저 시도한다. `.github/workflows/build-apk.yml`은 debug APK를 만들고 artifact로 업로드한다.
- D16: 첫 GitHub Actions APK 빌드는 Android SDK 라이선스 미수락으로 `build-tools;37.0.0` 설치가 스킵되어 `Aidl not found`로 실패했다. `android.accept_sdk_license = True`와 `yes | buildozer android debug`로 자동 수락을 명시한다.
- D17: Galaxy Fold4 첫 실행 화면에서 한글이 네모로 깨졌고 기본 Kivy 레이아웃이 앱처럼 보이지 않았다. APK 빌드 시 Noto Sans CJK KR 폰트를 받아 포함하고, Kivy UI를 모바일용 색상/간격/버튼 레이아웃으로 재작성한다.
- D18: 녹음 파일은 Kivy `user_data_dir/output/recordings/` 아래 앱 내부 저장소에 저장한다. 일반 파일 앱에서 보이지 않을 수 있으므로, 화면에 "최근 녹음" 경로를 상시 표시하고 `output/latest_recording.txt`에도 마지막 WAV 경로를 기록한다.
