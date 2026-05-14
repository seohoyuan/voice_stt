from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from voice2spec.recorder import RecordingConfig, RecordingValidationError, inspect_wav, record_wav, validate_recording


class RecorderTests(unittest.TestCase):
    def test_inspect_and_validate_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "sample.wav"
            _write_test_wav(wav_path, duration_sec=1.0)

            result = inspect_wav(wav_path)

            self.assertEqual(result.sample_rate, 16_000)
            self.assertEqual(result.channels, 1)
            self.assertAlmostEqual(result.duration_sec, 1.0, places=2)
            validate_recording(result)

    def test_reject_short_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "short.wav"
            _write_test_wav(wav_path, duration_sec=0.1)

            result = inspect_wav(wav_path)

            with self.assertRaises(RecordingValidationError):
                validate_recording(result)

    def test_reject_quiet_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "quiet.wav"
            _write_test_wav(wav_path, duration_sec=1.0, amplitude=1)

            result = inspect_wav(wav_path)

            with self.assertRaises(RecordingValidationError):
                validate_recording(result)

    def test_reject_invalid_config(self) -> None:
        with self.assertRaises(ValueError):
            record_wav(RecordingConfig(duration_sec=0.1))


def _write_test_wav(path: Path, duration_sec: float, amplitude: int = 1200) -> None:
    sample_rate = 16_000
    frames = int(sample_rate * duration_sec)
    samples = []
    for index in range(frames):
        value = amplitude if index % 2 == 0 else -amplitude
        samples.append(int(value).to_bytes(2, byteorder="little", signed=True))

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(samples))


if __name__ == "__main__":
    unittest.main()
