# Voice2Spec Python Mobile Prototype

Voice2Spec는 모바일에서 아이디어를 입력하거나 녹음하고, 이를 명세서와 화면 흐름 설명으로 바꾸는 개인용 앱 프로토타입입니다.

현재 프로젝트는 두 층으로 나뉩니다.

- `voice2spec/`: 앱의 핵심 파이프라인과 저장 로직
- `main.py`: APK에서 실행될 Kivy 모바일 앱 진입점

## 중요한 현재 상태

- 모바일 녹음: Android `AudioRecord` 기반 16kHz mono WAV 저장 구현
- STT 연결점: whisper.cpp CLI 어댑터 구현
- 모바일 한글 UI: Noto Sans CJK KR 폰트를 APK 빌드 시 포함
- 텍스트 입력 → 명세 생성: 구현
- Markdown/JSON 저장: 구현
- STT 음성 → 텍스트 변환: 어댑터 구현, 실제 바이너리/모델 필요
- LLM 명세 생성: 아직 rule 기반

즉, 갤럭시 폴드4에서 녹음 파일을 저장한 뒤 STT 어댑터로 넘기는 흐름까지 연결되어 있습니다. 실제 인식에는 whisper.cpp 실행 파일과 모델 파일이 필요합니다.

## PC에서 파이프라인 테스트

프로젝트 폴더로 이동합니다.

```powershell
cd C:\Users\FSC22-06\cprojects\idea
```

텍스트 아이디어를 명세서로 생성합니다.

```powershell
python -m voice2spec.cli new "동네 반찬가게를 모아서 빠르게 주문하는 앱을 만들고 싶어"
```

목록과 열람:

```powershell
python -m voice2spec.cli list
python -m voice2spec.cli show 1
```

## 모바일 APK 방향

APK 빌드는 `buildozer.spec`를 기준으로 합니다.

```text
requirements = python3,kivy,pyjnius
android.permissions = RECORD_AUDIO
android.minapi = 29
android.archs = arm64-v8a
```

whisper.cpp 파일 위치:

```text
bin/whisper-cli
models/whisper-small-q5_1.bin
```

위 파일들이 들어오면 `main.py`가 녹음 중지 후 자동으로 다음 흐름을 시도합니다.

```text
AudioRecord WAV 저장 -> WhisperCppTranscriber -> Refiner -> Specifier -> Markdown 저장
```

Windows에서 Buildozer를 바로 쓰기보다는 나중에 WSL/Linux 또는 GitHub Actions로 빌드하는 편이 좋습니다.

GitHub Actions 자동 빌드 설정은 이미 들어 있습니다.

```text
.github/workflows/build-apk.yml
```

사용 방법은 `APK_BUILD.md`를 확인합니다.

녹음 파일은 앱 내부 저장소의 Kivy `user_data_dir` 아래에 저장됩니다.

```text
<user_data_dir>/output/recordings/<timestamp>_<uuid>.wav
<user_data_dir>/output/latest_recording.txt
```

갤럭시 폴드4에서는 대체로 아래와 같은 private 경로입니다.

```text
/data/user/0/org.voice2spec.voice2spec/files/app/output/recordings/
```

일반 파일 앱에서는 이 경로가 바로 보이지 않을 수 있습니다. 앱 화면의 "최근 녹음" 줄과 결과창에서 마지막 WAV 경로를 확인합니다.

## 구조

```text
main.py                         # Kivy 모바일 앱 진입점
buildozer.spec                  # APK 빌드 설정
assets/fonts/                   # APK 빌드 시 한글 폰트 포함
voice2spec/
  android_recorder.py           # Android AudioRecord 기반 WAV 녹음
  agents.py                     # Transcriber, Refiner, Specifier, Validator
  models.py                     # Python dataclass 데이터 모델
  recorder.py                   # PC용 녹음 실험 모듈, 모바일 핵심 아님
  stt.py                        # whisper.cpp CLI STT 어댑터
  storage.py                    # Markdown/JSON 저장, 목록/열람/휴지통
  cli.py                        # PC용 CLI harness
tests/
  test_pipeline.py
  test_recorder.py
  test_stt.py
  test_storage_management.py
```

## 테스트

```powershell
python tools/check_mobile_project.py
python -m unittest discover -s tests
```

## 다음 핵심 작업

1. Android 녹음 파일을 실제 기기에서 저장 확인
2. whisper.cpp Android 바이너리와 모델 파일 배치
3. WAV → 텍스트 STT 실제 기기 테스트
4. Kivy 화면을 녹음/처리/결과 흐름으로 다듬기
