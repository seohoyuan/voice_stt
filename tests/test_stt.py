from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from voice2spec.stt import (
    SttConfig,
    SttNotConfiguredError,
    WhisperCppTranscriber,
    clean_whisper_output,
    find_default_whisper_binary,
    find_default_whisper_model,
)


class SttTests(unittest.TestCase):
    def test_clean_whisper_output_removes_logs_and_timestamps(self) -> None:
        output = """
        whisper_init_from_file: loading model
        [00:00:00.000 --> 00:00:02.000] 안녕하세요
        [00:00:02.000 --> 00:00:04.000] 아이디어 앱입니다
        print_timings: done
        """

        self.assertEqual(clean_whisper_output(output), "안녕하세요 아이디어 앱입니다")

    def test_missing_config_raises_clear_error(self) -> None:
        transcriber = WhisperCppTranscriber(SttConfig())

        with self.assertRaises(SttNotConfiguredError):
            transcriber.transcribe("missing.wav")

    def test_default_whisper_assets_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "bin" / "whisper-bin-x64" / "Release" / "whisper-cli.exe"
            model = root / "models" / "ggml-small-q5_1.bin"
            binary.parent.mkdir(parents=True)
            model.parent.mkdir(parents=True)
            binary.write_text("fake", encoding="utf-8")
            model.write_text("fake", encoding="utf-8")

            self.assertEqual(find_default_whisper_binary(root), binary)
            self.assertEqual(find_default_whisper_model(root), model)

    def test_transcribe_with_fake_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "whisper-cli"
            model = root / "model.bin"
            wav = root / "audio.wav"
            binary.write_text("fake", encoding="utf-8")
            model.write_text("fake", encoding="utf-8")
            _write_test_wav(wav)

            def fake_runner(command: list[str], timeout_sec: int) -> str:
                self.assertIn(str(model), command)
                self.assertIn(str(wav), command)
                self.assertIn("-t", command)
                self.assertIn("4", command)
                self.assertEqual(timeout_sec, 180)
                return "[00:00:00.000 --> 00:00:01.000] 테스트 음성입니다"

            transcriber = WhisperCppTranscriber(
                SttConfig(binary_path=binary, model_path=model),
                runner=fake_runner,
            )

            result = transcriber.transcribe(wav)

            self.assertEqual(result.text, "테스트 음성입니다")
            self.assertEqual(result.language, "ko")


def _write_test_wav(path: Path) -> None:
    sample_rate = 16_000
    frames = sample_rate
    samples = []
    for index in range(frames):
        value = 1200 if index % 2 == 0 else -1200
        samples.append(int(value).to_bytes(2, byteorder="little", signed=True))

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(samples))


if __name__ == "__main__":
    unittest.main()
