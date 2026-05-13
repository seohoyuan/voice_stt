from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from voice2spec.agents import run_pipeline
from voice2spec.android_recorder import (
    AndroidRecorderError,
    AndroidWavRecorder,
    export_file_to_downloads,
    export_wav_to_downloads,
    has_record_audio_permission,
    request_record_audio_permission,
)
from voice2spec.recorder import inspect_wav
from voice2spec.storage import save_idea
from voice2spec.stt import SttConfig, SttError, SttNotConfiguredError, WhisperCppTranscriber


try:
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.core.text import LabelBase
    from kivy.core.window import Window
    from kivy.graphics import Color, Rectangle
    from kivy.metrics import dp, sp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup
    from kivy.uix.textinput import TextInput
except ImportError as exc:  # Allows CLI/tests to run without Kivy installed.
    raise SystemExit("Kivy is required for the mobile APK build.") from exc


FONT_NAME = "Roboto"
APP_BUILD_LABEL = "record-diagnostics-v7"


def register_korean_font() -> str:
    candidates = [
        Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSansCJKkr-Regular.otf",
        Path("/system/fonts/NotoSansCJK-Regular.ttc"),
        Path("/system/fonts/NotoSansCJKkr-Regular.otf"),
        Path("/system/fonts/SamsungOneKorean-400.ttf"),
        Path("/system/fonts/DroidSansFallback.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            LabelBase.register(name="Voice2SpecKR", fn_regular=str(font_path))
            return "Voice2SpecKR"
    return "Roboto"


class Panel(BoxLayout):
    def __init__(self, background=(1, 1, 1, 1), **kwargs) -> None:
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*background)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_rect, size=self._sync_rect)

    def _sync_rect(self, *_args) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size


class AppButton(Button):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            font_name=FONT_NAME,
            font_size=sp(16),
            size_hint_y=None,
            height=dp(52),
            background_normal="",
            background_down="",
            color=(1, 1, 1, 1),
            **kwargs,
        )


class Voice2SpecRoot(BoxLayout):
    def __init__(self, app: "Voice2SpecApp", **kwargs) -> None:
        super().__init__(orientation="vertical", spacing=dp(12), padding=dp(16), **kwargs)
        self.app = app

        with self.canvas.before:
            Color(0.07, 0.09, 0.10, 1)
            self._background = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_background, size=self._sync_background)

        self.title = Label(
            text="Voice2Spec",
            font_name=FONT_NAME,
            font_size=sp(24),
            bold=True,
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(42),
        )
        self.status = Label(
            text="아이디어를 입력하거나 녹음하세요.",
            font_name=FONT_NAME,
            font_size=sp(14),
            color=(0.78, 0.86, 0.88, 1),
            size_hint_y=None,
            height=dp(32),
        )
        self.build_label = Label(
            text=f"빌드: {APP_BUILD_LABEL}",
            font_name=FONT_NAME,
            font_size=sp(11),
            color=(0.58, 0.70, 0.72, 1),
            size_hint_y=None,
            height=dp(22),
        )
        self.path_label = Label(
            text="최근 녹음: 아직 없음",
            font_name=FONT_NAME,
            font_size=sp(12),
            color=(0.68, 0.78, 0.80, 1),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(46),
        )
        self.path_label.bind(
            width=lambda instance, value: setattr(instance, "text_size", (value, None)),
        )
        self.recording_state = Label(
            text="녹음 상태: 대기",
            font_name=FONT_NAME,
            font_size=sp(13),
            color=(0.95, 0.88, 0.62, 1),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(30),
        )
        self.recording_state.bind(
            width=lambda instance, value: setattr(instance, "text_size", (value, None)),
        )
        self.input = TextInput(
            hint_text="예: 회의 내용을 입력하면 결정사항과 할 일을 정리하는 앱",
            font_name=FONT_NAME,
            font_size=sp(16),
            multiline=True,
            size_hint_y=0.32,
            padding=(dp(12), dp(12), dp(12), dp(12)),
            background_color=(0.97, 0.98, 0.98, 1),
            foreground_color=(0.05, 0.07, 0.08, 1),
            cursor_color=(0.00, 0.42, 0.40, 1),
        )

        button_panel = Panel(
            orientation="vertical",
            spacing=dp(8),
            padding=0,
            size_hint_y=None,
            height=dp(164),
            background=(0.07, 0.09, 0.10, 1),
        )
        self.record_button = AppButton(text="녹음 시작", background_color=(0.00, 0.42, 0.40, 1))
        self.stop_button = AppButton(text="녹음 중지", background_color=(0.58, 0.20, 0.18, 1), disabled=True)
        self.generate_button = AppButton(text="텍스트로 명세 생성", background_color=(0.22, 0.38, 0.56, 1))
        button_panel.add_widget(self.record_button)
        button_panel.add_widget(self.stop_button)
        button_panel.add_widget(self.generate_button)

        self.result = TextInput(
            text=(
                f"결과가 여기에 표시됩니다.\n\n"
                f"현재 APK 빌드: {APP_BUILD_LABEL}\n"
                "녹음 중에는 수신 KB가 증가하는지 화면에 표시됩니다.\n"
                "모든 단계는 voice2spec_diagnostics.log에 기록됩니다."
            ),
            readonly=True,
            multiline=True,
            font_name=FONT_NAME,
            font_size=sp(15),
            size_hint_y=0.68,
            padding=(dp(12), dp(12), dp(12), dp(12)),
            background_color=(0.97, 0.98, 0.98, 1),
            foreground_color=(0.05, 0.07, 0.08, 1),
        )

        self.record_button.bind(on_press=lambda _: app.start_recording())
        self.stop_button.bind(on_press=lambda _: app.stop_recording())
        self.generate_button.bind(on_press=lambda _: app.generate_from_text(self.input.text))

        self.add_widget(self.title)
        self.add_widget(self.status)
        self.add_widget(self.build_label)
        self.add_widget(self.path_label)
        self.add_widget(self.recording_state)
        self.add_widget(self.input)
        self.add_widget(button_panel)
        self.add_widget(self.result)

    def _sync_background(self, *_args) -> None:
        self._background.pos = self.pos
        self._background.size = self.size

    def set_recording(self, recording: bool) -> None:
        self.record_button.disabled = recording
        self.stop_button.disabled = not recording
        self.record_button.opacity = 0.45 if recording else 1
        self.stop_button.opacity = 1 if recording else 0.45

    def set_status(self, text: str) -> None:
        self.status.text = text

    def set_result(self, text: str) -> None:
        self.result.text = text

    def set_recording_path(self, path: Path | None) -> None:
        if path is None:
            self.path_label.text = "최근 녹음: 아직 없음"
        else:
            self.path_label.text = f"최근 녹음: {path}"

    def set_recording_state(self, text: str) -> None:
        self.recording_state.text = text


class Voice2SpecApp(App):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.root_widget: Voice2SpecRoot | None = None
        self.recorder = AndroidWavRecorder(event_logger=self._log_event)
        self._recording_started_at: datetime | None = None
        self._recording_tick_event = None
        self._recording_runtime_error_shown = False

    def build(self):
        global FONT_NAME
        FONT_NAME = register_korean_font()
        Window.clearcolor = (0.07, 0.09, 0.10, 1)
        self._log_event(f"app.build started build={APP_BUILD_LABEL}")

        try:
            request_record_audio_permission()
            self._log_event("record audio permission requested")
        except AndroidRecorderError as exc:
            self._log_event(f"record audio permission request skipped/failed: {exc}")

        self.root_widget = Voice2SpecRoot(self)
        self.root_widget.set_result(
            f"현재 APK 빌드: {APP_BUILD_LABEL}\n\n"
            "진단 로그가 켜져 있습니다.\n"
            f"앱 내부 로그:\n{self._diagnostics_log_path()}\n\n"
            "녹음 시작을 누르면 상태 줄에 녹음 시간과 수신 KB가 표시됩니다."
        )
        return self.root_widget

    def start_recording(self) -> None:
        if self.root_widget is None:
            return

        path = self._recordings_dir() / f"{datetime.now():%Y-%m-%d_%H%M%S}_{uuid4()}.wav"
        self._log_event(f"ui.start_recording tapped target={path}")
        self.root_widget.set_recording_state("녹음 상태: 시작 요청 중...")
        try:
            permission_granted = has_record_audio_permission()
            self._log_event(f"record audio permission granted={permission_granted}")
            if not permission_granted:
                request_record_audio_permission()
                raise AndroidRecorderError(
                    "마이크 권한이 아직 허용되지 않았습니다. 권한 팝업에서 허용한 뒤 다시 녹음 시작을 누르세요."
                )
        except AndroidRecorderError as exc:
            self._log_event(f"record audio permission check failed: {exc}")
            log_location = self._export_log_for_user()
            message = (
                "녹음 시작 전 권한 확인 실패\n\n"
                f"{exc}\n\n"
                f"진단 로그:\n{log_location}"
            )
            self.root_widget.set_status("마이크 권한 필요")
            self.root_widget.set_recording_state("녹음 상태: 권한 필요")
            self.root_widget.set_result(message)
            self._notify_user("마이크 권한 필요", message)
            return

        try:
            self.recorder.start(path)
        except AndroidRecorderError as exc:
            self._log_event(f"ui.start_recording failed: {exc}")
            log_location = self._export_log_for_user()
            message = (
                "녹음 시작 실패\n\n"
                f"{exc}\n\n"
                "마이크 권한을 허용했는지 확인한 뒤 다시 시도하세요.\n\n"
                f"진단 로그:\n{log_location}"
            )
            self.root_widget.set_status("녹음 시작 실패")
            self.root_widget.set_recording_state("녹음 상태: 시작 실패")
            self.root_widget.set_result(message)
            self._notify_user("녹음 시작 실패", message)
            return

        self.root_widget.set_recording(True)
        self._recording_started_at = datetime.now()
        self._recording_runtime_error_shown = False
        self._start_recording_monitor()
        self._log_event("ui.start_recording succeeded")
        self.root_widget.set_status("녹음 중입니다. 말을 마치면 중지를 누르세요.")
        self.root_widget.set_result(
            "녹음 중입니다.\n\n"
            f"예상 저장 위치:\n{path}\n\n"
            "아래 녹음 상태 줄에서 시간이 흐르고 수신 KB가 증가해야 합니다.\n"
            f"진단 로그:\n{self._diagnostics_log_path()}"
        )
        self._show_android_toast("녹음 시작됨\n화면에서 수신 KB가 증가하는지 확인하세요.")

    def stop_recording(self) -> None:
        if self.root_widget is None:
            return

        self._log_event("ui.stop_recording tapped")
        try:
            path = self.recorder.stop()
        except AndroidRecorderError as exc:
            self.root_widget.set_recording(False)
            self._stop_recording_monitor()
            self._log_event(f"ui.stop_recording failed: {exc}")
            log_location = self._export_log_for_user()
            message = (
                "녹음 종료 실패\n\n"
                f"{exc}\n\n"
                "이 메시지가 보이면 팝업 기능은 들어간 APK입니다. "
                "녹음 스레드나 Android 권한 쪽에서 실패한 것입니다.\n\n"
                f"수신 바이트: {self.recorder.bytes_written}\n"
                f"진단 로그:\n{log_location}"
            )
            self.root_widget.set_status("녹음 종료 실패")
            self.root_widget.set_recording_state(
                f"녹음 상태: 종료 실패 | 수신 {self.recorder.bytes_written / 1024:.1f} KB"
            )
            self.root_widget.set_result(message)
            self._notify_user("녹음 종료 실패", message)
            return

        self.root_widget.set_recording(False)
        self._stop_recording_monitor()
        self._log_event(f"ui.stop_recording succeeded path={path} bytes={self.recorder.bytes_written}")
        self._remember_latest_recording(path)
        self.root_widget.set_recording_path(path)
        recording_ok, recording_info = self._describe_recording(path)
        public_location = self._export_recording_for_user(path)
        log_location = self._export_log_for_user()
        popup_text = self._recording_popup_text(
            recording_ok,
            recording_info,
            path,
            public_location,
            log_location,
        )
        self.root_widget.set_status(f"녹음 저장: {path.name}")
        self.root_widget.set_recording_state(
            f"녹음 상태: 중지됨 | 최종 수신 {self.recorder.bytes_written / 1024:.1f} KB"
        )
        self.root_widget.set_result(
            "녹음 파일이 저장되었습니다.\n\n"
            f"{recording_info}\n\n"
            f"앱 내부 경로:\n{path}\n\n"
            f"확인 가능한 위치:\n{public_location}\n\n"
            f"진단 로그:\n{log_location}\n\n"
            "STT 처리 중..."
        )
        self._notify_user("Voice2Spec", popup_text)
        threading.Thread(target=self._generate_from_wav, args=(path,), daemon=True).start()

    def generate_from_text(self, text: str) -> None:
        if self.root_widget is None:
            return
        if not text.strip():
            self.root_widget.set_status("텍스트를 먼저 입력하세요.")
            return

        transcript, idea, spec, validation = run_pipeline(text)
        markdown_path, _ = save_idea(self._ideas_dir(), transcript, idea, spec, validation)
        self.root_widget.set_status(f"저장 완료: {markdown_path.name}")
        self.root_widget.set_result(self._format_spec_result(spec.title, spec.summary, spec.screens))

    def _generate_from_wav(self, wav_path: Path) -> None:
        self._log_event(f"stt.pipeline started wav={wav_path}")
        try:
            transcriber = WhisperCppTranscriber(self._stt_config())
            transcript, idea, spec, validation = run_pipeline(wav_path, transcriber=transcriber)
            markdown_path, _ = save_idea(self._ideas_dir(), transcript, idea, spec, validation)
        except SttNotConfiguredError as exc:
            self._log_event(f"stt.not_configured: {exc}")
            self._schedule_result(
                status="STT 설정 필요",
                text=(
                    f"녹음 파일은 저장되었습니다.\n\n{wav_path}\n\n"
                    f"{exc}\n\n"
                    "whisper.cpp Android 파일과 모델을 넣으면 이 녹음이 텍스트로 변환됩니다.\n\n"
                    f"진단 로그:\n{self._diagnostics_log_path()}"
                ),
            )
            return
        except SttError as exc:
            self._log_event(f"stt.failed: {exc}")
            self._schedule_result(
                status="STT 실패",
                text=(
                    f"녹음 파일은 저장되었습니다.\n\n{wav_path}\n\n"
                    f"STT 실패: {exc}\n\n"
                    f"진단 로그:\n{self._diagnostics_log_path()}"
                ),
            )
            return

        self._log_event(f"stt.pipeline succeeded markdown={markdown_path}")
        self._schedule_result(
            status=f"저장 완료: {markdown_path.name}",
            text=f"STT 결과:\n{transcript.text}\n\n{self._format_spec_result(spec.title, spec.summary, spec.screens)}",
        )

    def _format_spec_result(self, title: str, summary: str, screens) -> str:
        screen_text = "\n\n".join(f"[{screen.name}]\n{screen.wireframe}" for screen in screens)
        return f"# {title}\n\n{summary}\n\n## 화면\n{screen_text}"

    def _schedule_result(self, status: str, text: str) -> None:
        def update_ui(_dt) -> None:
            if self.root_widget is None:
                return
            self.root_widget.set_status(status)
            self.root_widget.set_result(text)

        Clock.schedule_once(update_ui, 0)

    def _stt_config(self) -> SttConfig:
        return SttConfig(
            binary_path=self._first_existing(
                self._app_output_dir() / "bin" / "whisper-cli",
                Path(__file__).resolve().parent / "bin" / "whisper-cli",
            ),
            model_path=self._first_existing(
                self._app_output_dir() / "models" / "whisper-small-q5_1.bin",
                Path(__file__).resolve().parent / "models" / "whisper-small-q5_1.bin",
            ),
            language="ko",
        )

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]

    def _app_output_dir(self) -> Path:
        return Path(self.user_data_dir) / "output"

    def _ideas_dir(self) -> Path:
        path = self._app_output_dir() / "ideas"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _recordings_dir(self) -> Path:
        path = self._app_output_dir() / "recordings"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _remember_latest_recording(self, path: Path) -> None:
        marker_path = self._app_output_dir() / "latest_recording.txt"
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(str(path), encoding="utf-8")
        self._log_event(f"latest recording marker written path={marker_path}")

    def _describe_recording(self, path: Path) -> tuple[bool, str]:
        try:
            result = inspect_wav(path)
            size_kb = path.stat().st_size / 1024
            ok = path.exists() and path.stat().st_size > 44 and result.duration_sec >= 0.5
            status = "녹음 파일 생성 확인됨" if ok else "녹음 파일이 너무 작거나 짧습니다"
            self._log_event(
                "recording inspected "
                f"ok={ok} size_kb={size_kb:.1f} duration={result.duration_sec:.2f} "
                f"sample_rate={result.sample_rate}"
            )
            return ok, (
                f"{status}\n"
                f"파일 크기: {size_kb:.1f} KB\n"
                f"길이: {result.duration_sec:.2f}초\n"
                f"형식: {result.sample_rate}Hz mono WAV"
            )
        except Exception as exc:
            self._log_event(f"recording inspection failed: {exc}")
            return False, f"파일 정보 확인 실패: {exc}"

    def _export_recording_for_user(self, path: Path) -> str:
        try:
            self._log_event(f"recording public export started path={path}")
            location = export_wav_to_downloads(path)
            self._log_event(f"recording public export succeeded location={location}")
            return f"공개 폴더 복사 성공: {location}"
        except Exception as exc:
            self._log_event(f"recording public export failed: {exc}")
            return f"공개 폴더 복사 실패: {exc}"

    def _export_log_for_user(self) -> str:
        log_path = self._diagnostics_log_path()
        try:
            self._log_event(f"diagnostics public export started path={log_path}")
            location = export_file_to_downloads(log_path, mime_type="text/plain")
            self._log_event(f"diagnostics public export succeeded location={location}")
            return f"공개 로그 복사 성공: {location}"
        except Exception as exc:
            self._log_event(f"diagnostics public export failed: {exc}")
            return f"공개 로그 복사 실패: {exc}\n앱 내부 로그: {log_path}"

    def _recording_popup_text(
        self,
        recording_ok: bool,
        recording_info: str,
        path: Path,
        public_location: str,
        log_location: str,
    ) -> str:
        title = "녹음 확인 완료" if recording_ok else "녹음 확인 실패"
        return (
            f"{title}\n\n"
            f"{recording_info}\n\n"
            f"앱 내부 경로:\n{path}\n\n"
            f"{public_location}\n\n"
            f"{log_location}"
        )

    def _start_recording_monitor(self) -> None:
        self._stop_recording_monitor()
        self._recording_tick_event = Clock.schedule_interval(self._update_recording_monitor, 0.5)

    def _stop_recording_monitor(self) -> None:
        if self._recording_tick_event is not None:
            self._recording_tick_event.cancel()
            self._recording_tick_event = None

    def _update_recording_monitor(self, _dt) -> bool:
        if self.root_widget is None or self._recording_started_at is None:
            return False

        elapsed = int((datetime.now() - self._recording_started_at).total_seconds())
        kb = self.recorder.bytes_written / 1024
        if self.recorder.error_message:
            self.root_widget.set_recording_state(f"녹음 상태: 오류 | {elapsed}초 | 수신 {kb:.1f} KB")
            if not self._recording_runtime_error_shown:
                self._recording_runtime_error_shown = True
                self._log_event(f"recording runtime error visible: {self.recorder.error_message}")
                message = (
                    "녹음 중 오류 발생\n\n"
                    f"{self.recorder.error_message}\n\n"
                    f"수신 바이트: {self.recorder.bytes_written}\n"
                    f"진단 로그:\n{self._diagnostics_log_path()}"
                )
                self.root_widget.set_status("녹음 중 오류")
                self.root_widget.set_result(message)
                self._notify_user("녹음 중 오류", message)
            return True

        if self.recorder.is_recording:
            self.root_widget.set_recording_state(f"● 녹음 중 | {elapsed}초 | 수신 {kb:.1f} KB")
            return True

        self.root_widget.set_recording_state(f"녹음 상태: 스레드 중지됨 | {elapsed}초 | 수신 {kb:.1f} KB")
        return True

    def _diagnostics_log_path(self) -> Path:
        return self._app_output_dir() / "voice2spec_diagnostics.log"

    def _log_event(self, message: str) -> None:
        try:
            log_path = self._diagnostics_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat(timespec="seconds")
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{timestamp} [{APP_BUILD_LABEL}] {message}\n")
        except Exception:
            pass

    def _show_popup(self, title: str, text: str) -> None:
        def open_popup(_dt) -> None:
            content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))
            message = Label(
                text=text,
                font_name=FONT_NAME,
                font_size=sp(14),
                color=(0.05, 0.07, 0.08, 1),
                halign="left",
                valign="top",
            )
            message.bind(
                width=lambda instance, value: setattr(instance, "text_size", (value, None)),
            )
            close_button = AppButton(text="확인", background_color=(0.00, 0.42, 0.40, 1))
            content.add_widget(message)
            content.add_widget(close_button)
            popup = Popup(
                title=title,
                content=content,
                size_hint=(0.92, 0.62),
                auto_dismiss=True,
            )
            close_button.bind(on_press=lambda *_args: popup.dismiss())
            popup.open()

        Clock.schedule_once(open_popup, 0)

    def _notify_user(self, title: str, text: str) -> None:
        self._show_android_toast(f"{title}\n{text}")
        self._show_popup(title, text)

    def _show_android_toast(self, text: str) -> None:
        try:
            from android.runnable import run_on_ui_thread
            from jnius import autoclass

            Toast = autoclass("android.widget.Toast")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            toast_text = text.replace("\n\n", "\n")[:900]

            @run_on_ui_thread
            def show_toast() -> None:
                Toast.makeText(PythonActivity.mActivity, toast_text, Toast.LENGTH_LONG).show()

            show_toast()
        except Exception as exc:
            self._log_event(f"android toast failed/skipped: {exc}")


if __name__ == "__main__":
    Voice2SpecApp().run()
