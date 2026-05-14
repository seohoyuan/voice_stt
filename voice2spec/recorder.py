from __future__ import annotations

import sys
import wave
from array import array
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


MIN_AVERAGE_AMPLITUDE = 0.001


class RecordingDependencyError(RuntimeError):
    pass


class RecordingValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordingConfig:
    duration_sec: float = 10.0
    sample_rate: int = 16_000
    channels: int = 1
    output_dir: Path = Path("output") / "recordings"


@dataclass(frozen=True)
class RecordingResult:
    wav_path: Path
    duration_sec: float
    sample_rate: int
    channels: int
    average_amplitude: float
    peak_amplitude: float = 0.0


def default_recordings_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "output" / "recordings"


def record_wav(config: RecordingConfig) -> RecordingResult:
    _validate_config(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    wav_path = config.output_dir / f"{datetime.now():%Y-%m-%d_%H%M%S}_{uuid4()}.wav"
    frame_count = int(config.duration_sec * config.sample_rate)

    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RecordingDependencyError(
            "마이크 녹음을 하려면 sounddevice와 numpy가 필요합니다. "
            "설치: python -m pip install -r requirements.txt"
        ) from exc

    try:
        audio = sd.rec(
            frame_count,
            samplerate=config.sample_rate,
            channels=config.channels,
            dtype="int16",
        )
        sd.wait()
    except ImportError as exc:
        raise RecordingDependencyError(
            "녹음 버퍼를 만들려면 numpy가 필요합니다. "
            "설치: python -m pip install -r requirements.txt"
        ) from exc

    _write_wav(
        path=wav_path,
        pcm_bytes=audio.tobytes(),
        sample_rate=config.sample_rate,
        channels=config.channels,
    )

    result = inspect_wav(wav_path)
    validate_recording(result)
    return result


def inspect_wav(path: Path) -> RecordingResult:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frames = wav.getnframes()
        pcm = wav.readframes(frames)

    duration_sec = frames / sample_rate if sample_rate else 0.0
    average_amplitude = _average_amplitude(pcm, sample_width)
    peak_amplitude = _peak_amplitude(pcm, sample_width)

    return RecordingResult(
        wav_path=path,
        duration_sec=duration_sec,
        sample_rate=sample_rate,
        channels=channels,
        average_amplitude=average_amplitude,
        peak_amplitude=peak_amplitude,
    )


def validate_recording(result: RecordingResult) -> None:
    if not result.wav_path.exists() or result.wav_path.stat().st_size == 0:
        raise RecordingValidationError("녹음 파일이 비어 있습니다.")
    if result.duration_sec < 0.5:
        raise RecordingValidationError("녹음 길이가 0.5초보다 짧습니다.")
    if result.peak_amplitude == 0.0:
        raise RecordingValidationError(
            "녹음 파일은 생성됐지만 오디오 샘플이 모두 0입니다. "
            "마이크 권한, Android 마이크 개인정보 토글, 또는 녹음 버퍼 읽기 방식을 확인해야 합니다."
        )
    if result.average_amplitude < MIN_AVERAGE_AMPLITUDE:
        raise RecordingValidationError(
            "녹음 소리가 너무 작습니다. 마이크 입력을 확인하고 조금 더 크게 말해주세요."
        )
    if result.sample_rate != 16_000:
        raise RecordingValidationError("녹음 샘플레이트는 16kHz여야 합니다.")
    if result.channels != 1:
        raise RecordingValidationError("녹음은 mono 채널이어야 합니다.")


def _validate_config(config: RecordingConfig) -> None:
    if config.duration_sec < 0.5:
        raise ValueError("duration_sec must be at least 0.5")
    if config.duration_sec > 300:
        raise ValueError("duration_sec must be 300 seconds or less")
    if config.sample_rate != 16_000:
        raise ValueError("sample_rate must be 16000 for STT-ready WAV files")
    if config.channels != 1:
        raise ValueError("channels must be 1 for mono WAV files")


def _write_wav(path: Path, pcm_bytes: bytes, sample_rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)


def _average_amplitude(pcm: bytes, sample_width: int) -> float:
    if not pcm or sample_width != 2:
        return 0.0

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()

    if not samples:
        return 0.0

    return sum(abs(sample) for sample in samples) / len(samples) / 32768.0


def _peak_amplitude(pcm: bytes, sample_width: int) -> float:
    if not pcm or sample_width != 2:
        return 0.0

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()

    if not samples:
        return 0.0

    return max(abs(sample) for sample in samples) / 32768.0
