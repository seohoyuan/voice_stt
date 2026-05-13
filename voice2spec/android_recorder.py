from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class AndroidRecorderError(RuntimeError):
    pass


EventLogger = Callable[[str], None]


@dataclass(frozen=True)
class AndroidRecordingConfig:
    sample_rate: int = 16_000
    channels: int = 1


class AndroidWavRecorder:
    """Android AudioRecord wrapper.

    This class is imported safely on desktop, but it only runs inside a
    python-for-android/Kivy APK where PyJNIus and Android classes exist.
    """

    def __init__(
        self,
        config: AndroidRecordingConfig | None = None,
        event_logger: EventLogger | None = None,
    ) -> None:
        self.config = config or AndroidRecordingConfig()
        self._event_logger = event_logger
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

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    @property
    def error_message(self) -> str | None:
        return str(self._error) if self._error is not None else None

    def start(self, output_path: Path) -> None:
        self._log(f"recorder.start requested path={output_path}")
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
        self._log("recorder.start prepared output directory")

        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        self._log("recorder thread started")

    def stop(self) -> Path:
        self._log("recorder.stop requested")
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

        self._log(f"recorder.stop completed path={self._output_path} bytes={self._bytes_written}")
        return self._output_path

    def _record_loop(self) -> None:
        try:
            self._log("record loop entered")
            self._record_loop_android()
        except Exception as exc:  # pragma: no cover - exercised on Android device.
            self._error = exc
            self._log(f"record loop error: {exc}")

    def _record_loop_android(self) -> None:
        if self._output_path is None:
            raise AndroidRecorderError("녹음 파일 경로가 없습니다.")

        try:
            from jnius import autoclass
        except ImportError as exc:
            raise AndroidRecorderError(
                "PyJNIus autoclass를 불러오지 못했습니다. APK 빌드에 pyjnius가 포함됐는지 확인해야 합니다. "
                f"원인: {exc}"
            ) from exc
        self._log("PyJNIus Android classes import ready")

        AudioFormat = autoclass("android.media.AudioFormat")
        AudioRecord = autoclass("android.media.AudioRecord")
        AudioSource = autoclass("android.media.MediaRecorder$AudioSource")
        JavaByte = autoclass("java.lang.Byte")
        JavaArray = autoclass("java.lang.reflect.Array")

        channel_config = AudioFormat.CHANNEL_IN_MONO
        audio_format = AudioFormat.ENCODING_PCM_16BIT
        min_buffer_bytes = AudioRecord.getMinBufferSize(
            self.config.sample_rate,
            channel_config,
            audio_format,
        )
        if min_buffer_bytes <= 0:
            raise AndroidRecorderError("Android AudioRecord buffer 크기를 얻지 못했습니다.")
        self._log(f"AudioRecord min_buffer_bytes={min_buffer_bytes}")

        buffer_bytes = max(2048, min_buffer_bytes)
        audio_source = AudioSource.MIC
        self._log(f"AudioRecord source=MIC({audio_source}) buffer_bytes={buffer_bytes}")
        audio_record = AudioRecord(
            audio_source,
            self.config.sample_rate,
            channel_config,
            audio_format,
            max(min_buffer_bytes, buffer_bytes),
        )
        state = audio_record.getState()
        self._log(f"AudioRecord state={state}")
        if state != AudioRecord.STATE_INITIALIZED:
            audio_record.release()
            raise AndroidRecorderError(
                "AudioRecord 초기화 실패. 마이크 권한이 없거나 다른 앱이 마이크를 사용 중일 수 있습니다. "
                f"state={state}"
            )

        byte_buffer = JavaArray.newInstance(JavaByte.TYPE, buffer_bytes)

        with self._output_path.open("wb") as wav_file:
            wav_file.write(_wav_header_placeholder())
            recording_started = False
            chunks_read = 0
            last_report_bytes = 0
            try:
                audio_record.startRecording()
                recording_state = audio_record.getRecordingState()
                self._log(f"AudioRecord.startRecording called recording_state={recording_state}")
                if recording_state != AudioRecord.RECORDSTATE_RECORDING:
                    raise AndroidRecorderError(
                        "AudioRecord 녹음 시작 실패. 마이크 권한 허용 여부와 다른 녹음 앱 실행 여부를 확인하세요. "
                        f"recording_state={recording_state}"
                    )
                recording_started = True

                while not self._stop_event.is_set():
                    read_count = audio_record.read(byte_buffer, 0, buffer_bytes)
                    if read_count > 0:
                        chunk = bytes(int(byte_buffer[index]) & 0xFF for index in range(read_count))
                        wav_file.write(chunk)
                        self._bytes_written += read_count
                        chunks_read += 1
                        if chunks_read == 1 or self._bytes_written - last_report_bytes >= 64 * 1024:
                            self._log(
                                "AudioRecord.read ok "
                                f"chunks={chunks_read} bytes={self._bytes_written}"
                            )
                            last_report_bytes = self._bytes_written
                    elif read_count < 0:
                        raise AndroidRecorderError(f"AudioRecord.read 실패 code={read_count}")
            finally:
                try:
                    if recording_started and audio_record.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING:
                        audio_record.stop()
                finally:
                    audio_record.release()
                    _rewrite_wav_header(
                        wav_file,
                        data_size=self._bytes_written,
                        sample_rate=self.config.sample_rate,
                        channels=self.config.channels,
                    )
                    self._log(f"WAV header written bytes={self._bytes_written}")

    def _log(self, message: str) -> None:
        if self._event_logger is None:
            return
        try:
            self._event_logger(message)
        except Exception:
            pass


def request_record_audio_permission() -> None:
    try:
        from android.permissions import Permission, request_permissions
    except ImportError as exc:
        raise AndroidRecorderError("권한 요청은 Android APK 내부에서만 가능합니다.") from exc

    request_permissions([Permission.RECORD_AUDIO])


def has_record_audio_permission() -> bool:
    try:
        from android.permissions import Permission, check_permission
    except ImportError as exc:
        raise AndroidRecorderError("권한 확인은 Android APK 내부에서만 가능합니다.") from exc

    return bool(check_permission(Permission.RECORD_AUDIO))


def export_file_to_downloads(
    file_path: Path,
    mime_type: str = "application/octet-stream",
    folder_name: str = "Voice2Spec",
) -> str:
    """Copy a file to public Downloads/Voice2Spec on Android.

    Returns a human-readable public location. This is intentionally separate
    from recording, because app-private storage is hard for users to verify.
    """

    if not file_path.exists():
        raise AndroidRecorderError(f"내보낼 파일을 찾지 못했습니다: {file_path}")

    try:
        from jnius import autoclass
    except ImportError as exc:
        raise AndroidRecorderError("공개 다운로드 폴더 내보내기는 Android APK 내부에서만 가능합니다.") from exc

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    MediaColumns = autoclass("android.provider.MediaStore$MediaColumns")
    Downloads = autoclass("android.provider.MediaStore$Downloads")
    ContentValues = autoclass("android.content.ContentValues")
    Environment = autoclass("android.os.Environment")

    activity = PythonActivity.mActivity
    resolver = activity.getContentResolver()
    values = ContentValues()
    display_name = file_path.name

    values.put(MediaColumns.DISPLAY_NAME, display_name)
    values.put(MediaColumns.MIME_TYPE, mime_type)
    values.put(
        MediaColumns.RELATIVE_PATH,
        Environment.DIRECTORY_DOWNLOADS + "/" + folder_name,
    )

    uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise AndroidRecorderError("다운로드 폴더에 WAV 파일을 만들지 못했습니다.")

    output_stream = resolver.openOutputStream(uri)
    if output_stream is None:
        raise AndroidRecorderError("다운로드 출력 스트림을 열지 못했습니다.")

    try:
        with file_path.open("rb") as source:
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                output_stream.write(chunk)
        output_stream.flush()
    finally:
        output_stream.close()

    return f"Download/{folder_name}/{display_name}"


def export_wav_to_downloads(wav_path: Path, folder_name: str = "Voice2Spec") -> str:
    """Copy a WAV file to public Downloads/Voice2Spec on Android."""

    return export_file_to_downloads(wav_path, mime_type="audio/wav", folder_name=folder_name)


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
