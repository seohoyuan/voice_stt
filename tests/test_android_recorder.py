from __future__ import annotations

import io
import wave
import unittest

from voice2spec.android_recorder import _rewrite_wav_header, _wav_header_placeholder


class AndroidRecorderHeaderTests(unittest.TestCase):
    def test_rewrite_wav_header_produces_readable_wav(self) -> None:
        audio_data = b"\x00\x00" * 160
        wav_file = io.BytesIO()
        wav_file.write(_wav_header_placeholder())
        wav_file.write(audio_data)

        _rewrite_wav_header(wav_file, data_size=len(audio_data), sample_rate=16_000, channels=1)

        wav_file.seek(0)
        with wave.open(wav_file, "rb") as parsed:
            self.assertEqual(parsed.getnchannels(), 1)
            self.assertEqual(parsed.getframerate(), 16_000)
            self.assertEqual(parsed.getsampwidth(), 2)
            self.assertEqual(parsed.getnframes(), 160)


if __name__ == "__main__":
    unittest.main()
