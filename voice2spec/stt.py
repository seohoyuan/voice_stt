from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agents import Transcriber
from .models import Segment, TranscriptResult


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
    def from_env(cls) -> "SttConfig":
        binary = os.environ.get("VOICE2SPEC_WHISPER_BIN")
        model = os.environ.get("VOICE2SPEC_WHISPER_MODEL")
        language = os.environ.get("VOICE2SPEC_STT_LANGUAGE", "ko")
        return cls(
            binary_path=Path(binary) if binary else None,
            model_path=Path(model) if model else None,
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
        self._log(
            "stt.files found "
            f"binary={self.config.binary_path} binary_size={self.config.binary_path.stat().st_size} "
            f"model={self.config.model_path} model_size={self.config.model_path.stat().st_size} "
            f"wav_size={wav_path.stat().st_size}"
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
