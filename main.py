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
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.textinput import TextInput
except ImportError as exc:  # Allows CLI/tests to run without Kivy installed.
    raise SystemExit("Kivy가 필요합니다. APK 빌드에서는 buildozer.spec의 requirements로 설치됩니다.") from exc


class Voice2SpecRoot(BoxLayout):
    def __init__(self, app: "Voice2SpecApp", **kwargs) -> None:
        super().__init__(orientation="vertical", spacing=12, padding=16, **kwargs)
        self.app = app

        self.status = Label(text="Voice2Spec", size_hint_y=None, height=48)
        self.input = TextInput(
            hint_text="아이디어를 입력하거나 녹음하세요",
            multiline=True,
            size_hint_y=1,
        )
        self.record_button = Button(text="녹음 시작", size_hint_y=None, height=56)
        self.stop_button = Button(text="녹음 중지", size_hint_y=None, height=56, disabled=True)
        self.generate_button = Button(text="텍스트로 명세 생성", size_hint_y=None, height=56)
        self.result = TextInput(readonly=True, multiline=True, size_hint_y=1)

        self.record_button.bind(on_press=lambda _: app.start_recording())
        self.stop_button.bind(on_press=lambda _: app.stop_recording())
        self.generate_button.bind(on_press=lambda _: app.generate_from_text(self.input.text))

        self.add_widget(self.status)
        self.add_widget(self.input)
        self.add_widget(self.record_button)
        self.add_widget(self.stop_button)
        self.add_widget(self.generate_button)
        self.add_widget(self.result)

    def set_recording(self, recording: bool) -> None:
        self.record_button.disabled = recording
        self.stop_button.disabled = not recording

    def set_status(self, text: str) -> None:
        self.status.text = text

    def set_result(self, text: str) -> None:
        self.result.text = text


class Voice2SpecApp(App):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.root_widget: Voice2SpecRoot | None = None
        self.recorder = AndroidWavRecorder()

    def build(self):
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
        self.root_widget.set_status("녹음 중...")

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
        self.root_widget.set_status(f"녹음 저장: {path.name}")
        self.root_widget.set_result(f"녹음 파일이 저장되었습니다.\n{path}\n\nSTT 처리 중...")
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
        self.root_widget.set_result(
            f"# {spec.title}\n\n"
            f"{spec.summary}\n\n"
            "## 화면\n"
            + "\n\n".join(f"{screen.name}\n{screen.wireframe}" for screen in spec.screens)
        )

    def _generate_from_wav(self, wav_path: Path) -> None:
        try:
            transcriber = WhisperCppTranscriber(self._stt_config())
            transcript, idea, spec, validation = run_pipeline(wav_path, transcriber=transcriber)
            markdown_path, _ = save_idea(self._ideas_dir(), transcript, idea, spec, validation)
        except SttNotConfiguredError as exc:
            self._schedule_result(
                status="STT 설정 필요",
                text=(
                    f"녹음 파일은 저장되었습니다.\n{wav_path}\n\n"
                    f"{exc}\n\n"
                    "모델 파일과 whisper.cpp 실행 파일을 앱에 넣으면 이 단계가 실제 음성 인식으로 바뀝니다."
                ),
            )
            return
        except SttError as exc:
            self._schedule_result(
                status="STT 실패",
                text=f"녹음 파일은 저장되었습니다.\n{wav_path}\n\nSTT 실패: {exc}",
            )
            return

        self._schedule_result(
            status=f"저장 완료: {markdown_path.name}",
            text=(
                f"STT 결과:\n{transcript.text}\n\n"
                f"# {spec.title}\n\n"
                f"{spec.summary}\n\n"
                "## 화면\n"
                + "\n\n".join(f"{screen.name}\n{screen.wireframe}" for screen in spec.screens)
            ),
        )

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


if __name__ == "__main__":
    Voice2SpecApp().run()
