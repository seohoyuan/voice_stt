# Voice2Spec Desktop MVP

이제 개발 우선순위는 노트북 Python MVP입니다. Android APK는 녹음/STT/모델 포팅 단계에서 다시 얇게 붙입니다.

## 목표 흐름

```text
노트북 마이크 녹음
-> 16kHz mono WAV 저장
-> whisper.cpp STT
-> OpenAI/Claude API 또는 rule provider로 명세 생성
-> Markdown/JSON 저장
```

## 1. Python 의존성 설치

```powershell
cd C:\Users\FSC22-06\cprojects\idea
python -m pip install -r requirements.txt
```

## 2. whisper 모델

폴드4와 노트북 실험 기본 모델은 `ggml-small-q5_1.bin`입니다.

```text
models/ggml-small-q5_1.bin
```

이 파일은 약 190MB라 Git에는 올리지 않습니다.

## 3. whisper 실행 파일

노트북에서는 PC용 `whisper-cli.exe`가 필요합니다.

권장 위치:

```text
bin/whisper-cli.exe
```

Android용 `bin/whisper-cli`와 PC용 `bin/whisper-cli.exe`는 서로 다릅니다.

## 4. 텍스트만 먼저 명세 생성

API 없이 rule provider:

```powershell
python -m voice2spec.cli spec "회의 내용을 말하면 결정사항과 할 일을 정리하는 앱"
```

OpenAI/Codex 계열:

```powershell
$env:OPENAI_API_KEY="..."
python -m voice2spec.cli --provider openai spec "회의 내용을 말하면 결정사항과 할 일을 정리하는 앱"
```

Claude:

```powershell
$env:ANTHROPIC_API_KEY="..."
python -m voice2spec.cli --provider claude spec "회의 내용을 말하면 결정사항과 할 일을 정리하는 앱"
```

## 5. 노트북 마이크로 전체 실행

```powershell
python -m voice2spec.cli `
  --whisper-bin .\bin\whisper-cli.exe `
  --whisper-model .\models\ggml-small-q5_1.bin `
  --provider openai `
  desktop-run --duration 10
```

Claude를 쓰려면 `--provider claude`로 바꿉니다.

## 6. Android 포팅 원칙

노트북에서 아래가 안정화된 뒤 Android로 옮깁니다.

- 프롬프트 품질
- STT 결과 품질
- Markdown 저장 포맷
- 실패 로그 형식

Android에서 바꿀 부분은 아래 두 곳으로 제한합니다.

- 마이크 입력: 노트북 `sounddevice` -> Android `AudioRecord`
- STT 실행: PC `whisper-cli.exe` -> Android arm64 `whisper-cli` 또는 온디바이스 런타임

명세 생성 프롬프트와 저장 구조는 그대로 가져갑니다.
