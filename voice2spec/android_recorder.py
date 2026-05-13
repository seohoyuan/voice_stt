from __future__ import annotations

import struct
import threading
from dataclasses import dataclass
from pathlib import Path


class AndroidRecorderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AndroidRecordingConfig:
    sample_rate: int = 16_000
    channels: int = 1


class AndroidWavRecorder:
    """Android AudioRecord wrapper.

    This class is imported safely on desktop, but it only runs inside a
    python-for-android/Kivy APK where PyJNIus and Android classes exist.
    """

    def __init__(self, config: AndroidRecordingConfig | None = None) -> None:
        self.config = config or AndroidRecordingConfig()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._output_path: Path | None = None
        self._bytes_written = 0
        self._error: Exception | None = None

    @property
    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def output_path(self) -> Path | None:
        return self._output_path

    def start(self, output_path: Path) -> None:
        if self.is_recording:
            raise AndroidRecorderError("이미 녹음 중입니다.")

        if self.config.sample_rate != 16_000:
            raise AndroidRecorderError("STT 준비용 녹음은 16kHz여야 합니다.")
        if self.config.channels != 1:
            raise AndroidRecorderError("STT 준비용 녹음은 mono여야 합니다.")

        self._output_path = output_path
        self._bytes_written = 0
        self._error = None
        self._stop_event.clear()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop(self) -> Path:
        if self._thread is None:
            raise AndroidRecorderError("녹음이 시작되지 않았습니다.")

        self._stop_event.set()
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise AndroidRecorderError("녹음을 정상 종료하지 못했습니다.")
        if self._error is not None:
            raise AndroidRecorderError(str(self._error)) from self._error
        if self._output_path is None:
            raise AndroidRecorderError("녹음 파일 경로가 없습니다.")

        return self._output_path

    def _record_loop(self) -> None:
        try:
            self._record_loop_android()
        except Exception as exc:  # pragma: no cover - exercised on Android device.
            self._error = exc

    def _record_loop_android(self) -> None:
        if self._output_path is None:
            raise AndroidRecorderError("녹음 파일 경로가 없습니다.")

        try:
            from jnius import autoclass, jarray
        except ImportError as exc:
            raise AndroidRecorderError(
                "Android 녹음은 APK 내부에서만 동작합니다. "
                "Kivy/python-for-android 환경에서 실행해주세요."
            ) from exc

        AudioFormat = autoclass("android.media.AudioFormat")
        AudioRecord = autoclass("android.media.AudioRecord")
        MediaRecorder = autoclass("android.media.MediaRecorder")

        channel_config = AudioFormat.CHANNEL_IN_MONO
        audio_format = AudioFormat.ENCODING_PCM_16BIT
        min_buffer_bytes = AudioRecord.getMinBufferSize(
            self.config.sample_rate,
            channel_config,
            audio_format,
        )
        if min_buffer_bytes <= 0:
            raise AndroidRecorderError("Android AudioRecord buffer 크기를 얻지 못했습니다.")

        buffer_shorts = max(1024, min_buffer_bytes // 2)
        audio_record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            self.config.sample_rate,
            channel_config,
            audio_format,
            min_buffer_bytes,
        )

        short_buffer = jarray("h")([0] * buffer_shorts)

        with self._output_path.open("wb") as wav_file:
            wav_file.write(_wav_header_placeholder())
            audio_record.startRecording()
            try:
                while not self._stop_event.is_set():
                    read_count = audio_record.read(short_buffer, 0, buffer_shorts)
                    if read_count > 0:
                        chunk = struct.pack("<" + "h" * read_count, *short_buffer[:read_count])
                        wav_file.write(chunk)
                        self._bytes_written += len(chunk)
            finally:
                audio_record.stop()
                audio_record.release()
                _rewrite_wav_header(
                    wav_file,
                    data_size=self._bytes_written,
                    sample_rate=self.config.sample_rate,
                    channels=self.config.channels,
                )


def request_record_audio_permission() -> None:
    try:
        from android.permissions import Permission, request_permissions
    except ImportError as exc:
        raise AndroidRecorderError("권한 요청은 Android APK 내부에서만 가능합니다.") from exc

    request_permissions([Permission.RECORD_AUDIO])


def export_wav_to_downloads(wav_path: Path, folder_name: str = "Voice2Spec") -> str:
    """Copy a WAV file to public Downloads/Voice2Spec on Android.

    Returns a human-readable public location. This is intentionally separate
    from recording, because app-private storage is hard for users to verify.
    """

    try:
        from jnius import autoclass
    except ImportError as exc:
        raise AndroidRecorderError("공개 다운로드 폴더 내보내기는 Android APK 내부에서만 가능합니다.") from exc

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    MediaStore = autoclass("android.provider.MediaStore")
    ContentValues = autoclass("android.content.ContentValues")
    Environment = autoclass("android.os.Environment")

    activity = PythonActivity.mActivity
    resolver = activity.getContentResolver()
    values = ContentValues()
    display_name = wav_path.name

    values.put(MediaStore.MediaColumns.DISPLAY_NAME, display_name)
    values.put(MediaStore.MediaColumns.MIME_TYPE, "audio/wav")
    values.put(
        MediaStore.MediaColumns.RELATIVE_PATH,
        Environment.DIRECTORY_DOWNLOADS + "/" + folder_name,
    )

    uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise AndroidRecorderError("다운로드 폴더에 WAV 파일을 만들지 못했습니다.")

    output_stream = resolver.openOutputStream(uri)
    if output_stream is None:
        raise AndroidRecorderError("다운로드 WAV 출력 스트림을 열지 못했습니다.")

    try:
        with wav_path.open("rb") as source:
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                output_stream.write(chunk)
        output_stream.flush()
    finally:
        output_stream.close()

    return f"Download/{folder_name}/{display_name}"


def _wav_header_placeholder() -> bytes:
    return b"\x00" * 44


def _rewrite_wav_header(file_obj, data_size: int, sample_rate: int, channels: int) -> None:
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    riff_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    file_obj.seek(0)
    file_obj.write(header)
