from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from voice2spec.agents import run_pipeline
from voice2spec.android_recorder import AndroidRecorderError, AndroidWavRecorder, request_record_audio_permission
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
    from kivy.uix.textinput import TextInput
except ImportError as exc:  # Allows CLI/tests to run without Kivy installed.
    raise SystemExit("Kivy is required for the mobile APK build.") from exc


FONT_NAME = "Roboto"


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
            text="결과가 여기에 표시됩니다.",
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
        self.add_widget(self.path_label)
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


class Voice2SpecApp(App):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.root_widget: Voice2SpecRoot | None = None
        self.recorder = AndroidWavRecorder()

    def build(self):
        global FONT_NAME
        FONT_NAME = register_korean_font()
        Window.clearcolor = (0.07, 0.09, 0.10, 1)

        try:
            request_record_audio_permission()
        except AndroidRecorderError:
            pass

        self.root_widget = Voice2SpecRoot(self)
        return self.root_widget

    def start_recording(self) -> None:
        if self.root_widget is None:
            return

        path = self._recordings_dir() / f"{datetime.now():%Y-%m-%d_%H%M%S}_{uuid4()}.wav"
        try:
            self.recorder.start(path)
        except AndroidRecorderError as exc:
            self.root_widget.set_status(f"녹음 시작 실패: {exc}")
            return

        self.root_widget.set_recording(True)
        self.root_widget.set_status("녹음 중입니다. 말을 마치면 중지를 누르세요.")

    def stop_recording(self) -> None:
        if self.root_widget is None:
            return

        try:
            path = self.recorder.stop()
        except AndroidRecorderError as exc:
            self.root_widget.set_status(f"녹음 종료 실패: {exc}")
            self.root_widget.set_recording(False)
            return

        self.root_widget.set_recording(False)
        self._remember_latest_recording(path)
        self.root_widget.set_recording_path(path)
        self.root_widget.set_status(f"녹음 저장: {path.name}")
        self.root_widget.set_result(f"녹음 파일이 저장되었습니다.\n\n{path}\n\nSTT 처리 중...")
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
        try:
            transcriber = WhisperCppTranscriber(self._stt_config())
            transcript, idea, spec, validation = run_pipeline(wav_path, transcriber=transcriber)
            markdown_path, _ = save_idea(self._ideas_dir(), transcript, idea, spec, validation)
        except SttNotConfiguredError as exc:
            self._schedule_result(
                status="STT 설정 필요",
                text=(
                    f"녹음 파일은 저장되었습니다.\n\n{wav_path}\n\n"
                    f"{exc}\n\n"
                    "whisper.cpp Android 파일과 모델을 넣으면 이 녹음이 텍스트로 변환됩니다."
                ),
            )
            return
        except SttError as exc:
            self._schedule_result(
                status="STT 실패",
                text=f"녹음 파일은 저장되었습니다.\n\n{wav_path}\n\nSTT 실패: {exc}",
            )
            return

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


if __name__ == "__main__":
    Voice2SpecApp().run()
