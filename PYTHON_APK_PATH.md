# PYTHON_APK_PATH.md - Python 우선 개발 후 APK 전환 경로

## 결론

지금은 Python으로 Voice2Spec의 핵심 파이프라인을 먼저 만듭니다. 나중에 APK가 필요해지면 UI를 Kivy로 감싸고 Buildozer 또는 GitHub Actions/Linux 환경에서 APK를 빌드합니다.

## 왜 이 순서인가

- 지금 당장 설치할 것이 적습니다.
- Python으로 Recorder → Transcriber → Refiner → Specifier → Validator 구조를 빠르게 검증할 수 있습니다.
- 앱의 핵심 가치는 Android UI보다 "음성 아이디어가 명세서가 되는 파이프라인"에 있습니다.
- 나중에 APK 전환 시에도 Python 핵심 로직을 최대한 유지할 수 있습니다.

## 단계

### P1. Python CLI 프로토타입

- 텍스트 입력 또는 WAV 경로 입력
- Mock STT/LLM으로 파이프라인 구조 검증
- Markdown + JSON 저장
- 외부 의존성 최소화

### P2. 실제 STT/LLM 연결

선택지:

- PC에서 실행: `faster-whisper`, `llama-cpp-python`, Ollama
- 폰 단독 APK: Kivy + 네이티브 바이너리 연동 검토

### P3. Kivy UI

- 홈 화면
- 녹음 화면
- 결과 화면
- 저장된 아이디어 목록

### P4. APK 빌드

- Windows에서 직접 빌드하기보다 WSL/Linux 또는 GitHub Actions 권장
- Buildozer로 APK 생성
- 실제 폰에 사이드로드 설치

## 주의할 점

Python 앱을 APK로 만들 수는 있지만, Android 안에서 대형 STT/LLM을 완전 오프라인으로 돌리는 부분은 여전히 까다롭습니다. 그래서 먼저 Python으로 제품 경험을 확정하고, 무거운 모바일 최적화는 마지막에 다루는 전략이 안전합니다.
