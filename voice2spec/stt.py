from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agents import Transcriber
from .models import Segment, TranscriptResult
from .recorder import MIN_AVERAGE_AMPLITUDE, inspect_wav


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WHISPER_BIN_PATTERNS = (
    "bin/whisper-cli.exe",
    "bin/**/whisper-cli.exe",
    "bin/main.exe",
    "bin/**/main.exe",
)
DEFAULT_WHISPER_MODEL_PATTERNS = (
    "models/ggml-small-q5_1.bin",
    "models/ggml-base-q5_1.bin",
    "models/*.bin",
)


class SttError(RuntimeError):
    pass


class SttNotConfiguredError(SttError):
    pass


@dataclass(frozen=True)
class SttConfig:
    binary_path: Path | None = None
    model_path: Path | None = None
    language: str = "ko"
    timeout_sec: int = 180
    threads: int = 4

    @classmethod
    def from_env(cls, language_override: str | None = None) -> "SttConfig":
        binary = os.environ.get("VOICE2SPEC_WHISPER_BIN")
        model = os.environ.get("VOICE2SPEC_WHISPER_MODEL")
        language = language_override or os.environ.get("VOICE2SPEC_STT_LANGUAGE", "ko")
        return cls(
            binary_path=Path(binary) if binary else find_default_whisper_binary(),
            model_path=Path(model) if model else find_default_whisper_model(),
            language=language,
        )


CommandRunner = Callable[[list[str], int], str]
EventLogger = Callable[[str], None]


class WhisperCppTranscriber(Transcriber):
    """Transcriber adapter for whisper.cpp CLI.

    Expected command shape:
        whisper-cli -m <model> -f <wav> -l ko -nt

    The binary/model are not bundled yet. On mobile they should be placed in
    app storage or packaged assets, then passed through SttConfig.
    """

    def __init__(
        self,
        config: SttConfig | None = None,
        runner: CommandRunner | None = None,
        event_logger: EventLogger | None = None,
    ) -> None:
        self.config = config or SttConfig.from_env()
        self.runner = runner or run_whisper_command
        self.event_logger = event_logger

    def transcribe(self, source: str | Path) -> TranscriptResult:
        wav_path = Path(source)
        self._log(f"stt.validate started wav={wav_path}")
        self._validate(wav_path)
        self._log("stt.validate completed")

        command = self.build_command(wav_path)
        self._log(f"stt.command built: {redact_command(command)}")
        started_at = time.monotonic()
        output = self.runner(command, self.config.timeout_sec)
        elapsed = time.monotonic() - started_at
        self._log(f"stt.command completed elapsed={elapsed:.1f}s output_chars={len(output)}")
        text = clean_whisper_output(output)
        if not text:
            self._log("stt.output empty after cleanup")
            raise SttError("STT 결과가 비어 있습니다.")
        self._log(f"stt.output cleaned chars={len(text)}")

        return TranscriptResult(
            text=text,
            language=self.config.language,
            confidence=0.8,
            segments=[
                Segment(
                    start_ms=0,
                    end_ms=0,
                    text=text,
                    confidence=0.8,
                ),
            ],
        )

    def build_command(self, wav_path: Path) -> list[str]:
        assert self.config.binary_path is not None
        assert self.config.model_path is not None
        return [
            str(self.config.binary_path),
            "-m",
            str(self.config.model_path),
            "-f",
            str(wav_path),
            "-l",
            self.config.language,
            "-t",
            str(self.config.threads),
            "-nt",
        ]

    def _validate(self, wav_path: Path) -> None:
        if self.config.binary_path is None:
            raise SttNotConfiguredError("whisper.cpp 실행 파일 경로가 설정되지 않았습니다.")
        if self.config.model_path is None:
            raise SttNotConfiguredError("whisper.cpp 모델 파일 경로가 설정되지 않았습니다.")
        if not wav_path.exists():
            raise SttError(f"WAV 파일을 찾지 못했습니다: {wav_path}")
        if not self.config.model_path.exists():
            raise SttNotConfiguredError(f"whisper.cpp 모델 파일을 찾지 못했습니다: {self.config.model_path}")
        if not self.config.binary_path.exists():
            raise SttNotConfiguredError(f"whisper.cpp 실행 파일을 찾지 못했습니다: {self.config.binary_path}")
        try:
            recording = inspect_wav(wav_path)
            if recording.duration_sec < 0.5:
                raise SttError("STT 전에 녹음 검증 실패: 녹음 길이가 0.5초보다 짧습니다.")
            if recording.average_amplitude < MIN_AVERAGE_AMPLITUDE:
                raise SttError(
                    "STT 전에 녹음 검증 실패: 녹음 소리가 너무 작습니다. "
                    "마이크 입력을 확인하고 조금 더 크게 말해주세요."
                )
        except Exception as exc:
            if isinstance(exc, SttError):
                raise
            raise SttError(f"STT 전에 WAV 파일을 읽지 못했습니다: {exc}") from exc
        self._log(
            "stt.files found "
            f"binary={self.config.binary_path} binary_size={self.config.binary_path.stat().st_size} "
            f"model={self.config.model_path} model_size={self.config.model_path.stat().st_size} "
            f"wav_size={wav_path.stat().st_size} "
            f"wav_duration={recording.duration_sec:.2f} wav_amplitude={recording.average_amplitude:.4f}"
        )
        try:
            mode = self.config.binary_path.stat().st_mode
            self.config.binary_path.chmod(mode | 0o111)
            self._log(f"stt.binary chmod ok mode={oct(self.config.binary_path.stat().st_mode)}")
        except OSError as exc:
            raise SttNotConfiguredError(f"whisper.cpp 실행 권한 설정 실패: {exc}") from exc

    def _log(self, message: str) -> None:
        if self.event_logger is None:
            return
        try:
            self.event_logger(message)
        except Exception:
            pass


def clean_whisper_output(output: str) -> str:
    lines = []
    ignored_prefixes = (
        "whisper_",
        "main:",
        "system_info:",
        "ggml_",
        "print_timings:",
    )

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(ignored_prefixes):
            continue
        if line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].strip()
        if line:
            lines.append(line)

    return " ".join(lines).strip()


def redact_command(command: list[str]) -> str:
    return " ".join(command)


def run_whisper_command(command: list[str], timeout_sec: int) -> str:
    try:
        started_at = time.monotonic()
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise SttError(f"STT 실행 시간이 {timeout_sec}초를 초과했습니다.") from exc

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0:
        elapsed = time.monotonic() - started_at
        raise SttError(
            f"STT 실행 실패(returncode={completed.returncode}, elapsed={elapsed:.1f}s): {output.strip()}"
        )
    return output


def _run_command(command: list[str], timeout_sec: int) -> str:
    return run_whisper_command(command, timeout_sec)


def find_default_whisper_binary(root: Path = PROJECT_ROOT) -> Path | None:
    return _first_existing(root, DEFAULT_WHISPER_BIN_PATTERNS)


def find_default_whisper_model(root: Path = PROJECT_ROOT) -> Path | None:
    return _first_existing(root, DEFAULT_WHISPER_MODEL_PATTERNS)


def _first_existing(root: Path, patterns: tuple[str, ...]) -> Path | None:
    for pattern in patterns:
        matches = sorted(path for path in root.glob(pattern) if path.is_file())
        if matches:
            return matches[0]
    return None
