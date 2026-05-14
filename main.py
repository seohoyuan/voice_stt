from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from voice2spec.android_recorder import (
    AndroidRecorderError,
    AndroidWavRecorder,
    export_file_to_downloads,
    export_wav_to_downloads,
    has_record_audio_permission,
    request_record_audio_permission,
)
from voice2spec.desktop_pipeline import generate_spec_from_text, generate_spec_from_transcript
from voice2spec.env import load_env_file
from voice2spec.llm_specifier import LlmSpecError
from voice2spec.recorder import inspect_wav
from voice2spec.storage import find_idea, list_ideas, soft_delete_idea, update_idea
from voice2spec.stt import SttConfig, SttError, SttNotConfiguredError, WhisperCppTranscriber, run_whisper_command


try:
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.core.text import LabelBase
    from kivy.core.window import Window
    from kivy.graphics import Color, Rectangle
    from kivy.metrics import dp, sp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.textinput import TextInput
except ImportError as exc:
    raise SystemExit("Kivy is required for the mobile APK build.") from exc


FONT_NAME = "Roboto"
APP_BUILD_LABEL = "mobile-crud-claude-v3"
DEFAULT_PROVIDER = "claude"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-6"


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
            try:
                LabelBase.register(name="Voice2SpecKR", fn_regular=str(font_path))
                return "Voice2SpecKR"
            except Exception:
                continue
    return "Roboto"


class Surface(BoxLayout):
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
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", sp(15))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(48))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("color", (1, 1, 1, 1))
        super().__init__(**kwargs)


class SmallButton(AppButton):
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("font_size", sp(13))
        kwargs.setdefault("height", dp(42))
        super().__init__(**kwargs)


class BodyLabel(Label):
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", sp(14))
        kwargs.setdefault("color", (0.16, 0.20, 0.22, 1))
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "top")
        super().__init__(**kwargs)
        self.bind(width=lambda instance, value: setattr(instance, "text_size", (value, None)))


class Voice2SpecRoot(BoxLayout):
    def __init__(self, app: "Voice2SpecApp", **kwargs) -> None:
        super().__init__(orientation="vertical", spacing=dp(10), padding=dp(14), **kwargs)
        self.app = app
        self.content: BoxLayout | None = None

        with self.canvas.before:
            Color(0.94, 0.97, 0.96, 1)
            self._background = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_background, size=self._sync_background)

        self.title = Label(
            text="Voice2Spec",
            font_name=FONT_NAME,
            font_size=sp(28),
            bold=True,
            color=(0.05, 0.16, 0.16, 1),
            size_hint_y=None,
            height=dp(42),
        )
        self.status = Label(
            text="녹음, STT, Claude 명세 생성을 한 번에 처리합니다.",
            font_name=FONT_NAME,
            font_size=sp(13),
            color=(0.24, 0.38, 0.38, 1),
            size_hint_y=None,
            height=dp(34),
        )
        self.nav = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(44))
        self.create_button = SmallButton(text="생성", background_color=(0.00, 0.45, 0.40, 1))
        self.library_button = SmallButton(text="보관함", background_color=(0.18, 0.31, 0.46, 1))
        self.settings_button = SmallButton(text="설정", background_color=(0.28, 0.31, 0.35, 1))
        self.nav.add_widget(self.create_button)
        self.nav.add_widget(self.library_button)
        self.nav.add_widget(self.settings_button)

        self.create_button.bind(on_press=lambda *_args: app.show_create())
        self.library_button.bind(on_press=lambda *_args: app.show_library())
        self.settings_button.bind(on_press=lambda *_args: app.show_settings())

        self.add_widget(self.title)
        self.add_widget(self.status)
        self.add_widget(self.nav)
        self.set_content(BoxLayout())

    def _sync_background(self, *_args) -> None:
        self._background.pos = self.pos
        self._background.size = self.size

    def set_status(self, text: str) -> None:
        self.status.text = text

    def set_content(self, widget) -> None:
        if self.content is not None:
            self.remove_widget(self.content)
        self.content = BoxLayout(orientation="vertical", size_hint_y=1)
        self.content.add_widget(widget)
        self.add_widget(self.content)


class Voice2SpecApp(App):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.root_widget: Voice2SpecRoot | None = None
        self.recorder = AndroidWavRecorder(event_logger=self._log_event)
        self.result_box: TextInput | None = None
        self.record_button: Button | None = None
        self.stop_button: Button | None = None
        self.latest_recording: Path | None = None
        self.current_detail: dict | None = None
        self.settings = {
            "provider": DEFAULT_PROVIDER,
            "anthropic_model": DEFAULT_ANTHROPIC_MODEL,
            "anthropic_api_key": "",
        }

    def build(self):
        try:
            return self._build_app()
        except Exception as exc:
            self._write_startup_crash(exc)
            return self._build_crash_screen(exc)

    def _build_app(self):
        global FONT_NAME
        FONT_NAME = register_korean_font()
        Window.clearcolor = (0.94, 0.97, 0.96, 1)
        self.root_widget = Voice2SpecRoot(self)
        self.show_create()
        self._safe_startup_init()
        self._log_event(f"app.build started build={APP_BUILD_LABEL}")
        return self.root_widget

    def _safe_startup_init(self) -> None:
        startup_notes: list[str] = []
        try:
            load_env_file()
        except Exception as exc:
            startup_notes.append(f".env 로드 실패: {type(exc).__name__}: {exc}")
        try:
            self.settings.update(self._load_settings())
        except Exception as exc:
            startup_notes.append(f"설정 로드 실패: {type(exc).__name__}: {exc}")
        try:
            self._apply_settings_to_env()
        except Exception as exc:
            startup_notes.append(f"환경변수 적용 실패: {type(exc).__name__}: {exc}")

        if startup_notes:
            self._log_event("startup init warnings: " + " | ".join(startup_notes))
            self._set_result(
                "앱은 시작됐지만 초기 설정 중 경고가 있습니다.\n\n"
                + "\n".join(startup_notes)
                + f"\n\n진단 로그:\n{self._diagnostics_log_path()}"
            )

    def _build_crash_screen(self, exc: Exception):
        layout = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(16))
        with layout.canvas.before:
            Color(0.08, 0.10, 0.11, 1)
            background = Rectangle(pos=layout.pos, size=layout.size)
        layout.bind(pos=lambda *_args: setattr(background, "pos", layout.pos))
        layout.bind(size=lambda *_args: setattr(background, "size", layout.size))
        title = Label(
            text="Voice2Spec 시작 실패",
            font_name=FONT_NAME,
            font_size=sp(24),
            bold=True,
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(56),
        )
        body = TextInput(
            text=(
                "앱 시작 중 오류가 발생했습니다.\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                f"내부 로그:\n{self._diagnostics_log_path()}"
            ),
            readonly=True,
            multiline=True,
            font_name=FONT_NAME,
            font_size=sp(14),
            background_color=(1, 1, 1, 1),
            foreground_color=(0.05, 0.07, 0.08, 1),
        )
        copy_log = AppButton(text="진단 로그 복사", background_color=(0.00, 0.45, 0.40, 1))
        copy_log.bind(
            on_press=lambda *_args: setattr(
                body,
                "text",
                body.text + "\n\n" + self._export_log_for_user(),
            )
        )
        layout.add_widget(title)
        layout.add_widget(body)
        layout.add_widget(copy_log)
        return layout

    def show_create(self) -> None:
        if self.root_widget is None:
            return

        layout = BoxLayout(orientation="vertical", spacing=dp(10))
        hero = self._panel(orientation="vertical", spacing=dp(8), padding=dp(14), size_hint_y=None, height=dp(118))
        hero.add_widget(
            BodyLabel(
                text="말하거나 텍스트를 입력하면 STT와 Claude를 거쳐 명세서로 저장됩니다.",
                size_hint_y=None,
                height=dp(42),
            )
        )
        provider = self.settings.get("provider", DEFAULT_PROVIDER)
        model = self.settings.get("anthropic_model", DEFAULT_ANTHROPIC_MODEL)
        hero.add_widget(
            BodyLabel(
                text=f"현재 생성기: {provider} / {model if provider == 'claude' else 'local rule'}",
                size_hint_y=None,
                height=dp(32),
                color=(0.00, 0.42, 0.38, 1),
            )
        )

        input_box = TextInput(
            hint_text="예: 회의 내용을 말하면 결정사항과 할 일을 정리하는 앱",
            font_name=FONT_NAME,
            font_size=sp(15),
            multiline=True,
            size_hint_y=None,
            height=dp(118),
            padding=(dp(12), dp(10), dp(12), dp(10)),
            background_color=(1, 1, 1, 1),
            foreground_color=(0.06, 0.08, 0.09, 1),
        )

        controls = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(48))
        self.record_button = SmallButton(text="녹음 시작", background_color=(0.00, 0.45, 0.40, 1))
        self.stop_button = SmallButton(text="녹음 중지", background_color=(0.66, 0.22, 0.19, 1), disabled=True)
        generate_button = SmallButton(text="텍스트 생성", background_color=(0.18, 0.31, 0.46, 1))
        controls.add_widget(self.record_button)
        controls.add_widget(self.stop_button)
        controls.add_widget(generate_button)

        self.record_button.bind(on_press=lambda *_args: self.start_recording())
        self.stop_button.bind(on_press=lambda *_args: self.stop_recording())
        generate_button.bind(on_press=lambda *_args: self.generate_from_text(input_box.text))

        self.result_box = TextInput(
            text="결과가 여기에 표시됩니다.",
            readonly=True,
            multiline=True,
            font_name=FONT_NAME,
            font_size=sp(14),
            padding=(dp(12), dp(10), dp(12), dp(10)),
            background_color=(1, 1, 1, 1),
            foreground_color=(0.06, 0.08, 0.09, 1),
        )

        layout.add_widget(hero)
        layout.add_widget(input_box)
        layout.add_widget(controls)
        layout.add_widget(self.result_box)
        self.root_widget.set_status("새 아이디어를 녹음하거나 텍스트로 입력하세요.")
        self.root_widget.set_content(layout)

    def show_library(self) -> None:
        if self.root_widget is None:
            return

        ideas = list_ideas(self._ideas_dir())
        wrapper = BoxLayout(orientation="vertical", spacing=dp(10))
        header = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(44))
        refresh = SmallButton(text="새로고침", background_color=(0.28, 0.31, 0.35, 1))
        refresh.bind(on_press=lambda *_args: self.show_library())
        header.add_widget(BodyLabel(text=f"저장된 명세 {len(ideas)}개", size_hint_y=None, height=dp(42)))
        header.add_widget(refresh)
        wrapper.add_widget(header)

        scroll = ScrollView()
        list_box = GridLayout(cols=1, spacing=dp(8), size_hint_y=None)
        list_box.bind(minimum_height=list_box.setter("height"))
        if not ideas:
            empty = BodyLabel(text="아직 저장된 명세가 없습니다.", size_hint_y=None, height=dp(56))
            list_box.add_widget(empty)
        for index, idea in enumerate(ideas, start=1):
            button = Button(
                text=f"{index}. {idea['title']}\n{idea.get('summary', '')[:70]}",
                font_name=FONT_NAME,
                font_size=sp(14),
                halign="left",
                valign="middle",
                text_size=(Window.width - dp(48), None),
                size_hint_y=None,
                height=dp(72),
                background_normal="",
                background_down="",
                background_color=(1, 1, 1, 1),
                color=(0.06, 0.08, 0.09, 1),
            )
            button.bind(on_press=lambda _button, selected=idea: self.show_detail(selected))
            list_box.add_widget(button)
        scroll.add_widget(list_box)
        wrapper.add_widget(scroll)
        self.root_widget.set_status("보관함에서 읽기, 수정, 삭제를 할 수 있습니다.")
        self.root_widget.set_content(wrapper)

    def show_detail(self, idea: dict) -> None:
        if self.root_widget is None:
            return

        self.current_detail = idea
        markdown_path = idea["markdown_path"]
        markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else "Markdown 파일이 없습니다."
        transcript = idea.get("transcript", "")

        layout = BoxLayout(orientation="vertical", spacing=dp(10))
        actions = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(44))
        back = SmallButton(text="목록", background_color=(0.28, 0.31, 0.35, 1))
        save = SmallButton(text="수정 저장", background_color=(0.00, 0.45, 0.40, 1))
        delete = SmallButton(text="삭제", background_color=(0.66, 0.22, 0.19, 1))
        actions.add_widget(back)
        actions.add_widget(save)
        actions.add_widget(delete)

        edit_box = TextInput(
            text=transcript,
            hint_text="원본 transcript를 수정한 뒤 다시 생성할 수 있습니다.",
            font_name=FONT_NAME,
            font_size=sp(14),
            multiline=True,
            size_hint_y=None,
            height=dp(112),
            padding=(dp(12), dp(10), dp(12), dp(10)),
            background_color=(1, 1, 1, 1),
            foreground_color=(0.06, 0.08, 0.09, 1),
        )
        markdown_box = TextInput(
            text=markdown,
            readonly=True,
            multiline=True,
            font_name=FONT_NAME,
            font_size=sp(13),
            padding=(dp(12), dp(10), dp(12), dp(10)),
            background_color=(1, 1, 1, 1),
            foreground_color=(0.06, 0.08, 0.09, 1),
        )

        back.bind(on_press=lambda *_args: self.show_library())
        save.bind(on_press=lambda *_args: self.update_current_idea(edit_box.text))
        delete.bind(on_press=lambda *_args: self.delete_current_idea())

        layout.add_widget(actions)
        layout.add_widget(edit_box)
        layout.add_widget(markdown_box)
        self.root_widget.set_status(f"열람 중: {idea['title']}")
        self.root_widget.set_content(layout)

    def show_settings(self) -> None:
        if self.root_widget is None:
            return

        layout = BoxLayout(orientation="vertical", spacing=dp(10))
        info = self._panel(orientation="vertical", padding=dp(14), spacing=dp(8), size_hint_y=None, height=dp(112))
        info.add_widget(
            BodyLabel(
                text="Claude API 키는 이 기기 내부 저장소에만 저장됩니다. APK에 키를 넣지 않는 방식입니다.",
                size_hint_y=None,
                height=dp(44),
            )
        )
        info.add_widget(
            BodyLabel(
                text="provider를 rule로 바꾸면 네트워크 없이 기본 템플릿으로 생성합니다.",
                size_hint_y=None,
                height=dp(34),
                color=(0.00, 0.42, 0.38, 1),
            )
        )
        provider_input = self._settings_input(self.settings.get("provider", DEFAULT_PROVIDER), "provider: claude 또는 rule")
        model_input = self._settings_input(
            self.settings.get("anthropic_model", DEFAULT_ANTHROPIC_MODEL),
            "Claude 모델",
        )
        key_input = self._settings_input(
            self.settings.get("anthropic_api_key", ""),
            "ANTHROPIC_API_KEY",
            password=True,
        )
        save_button = AppButton(text="설정 저장", background_color=(0.00, 0.45, 0.40, 1))
        save_button.bind(
            on_press=lambda *_args: self.save_settings(
                provider_input.text,
                model_input.text,
                key_input.text,
            )
        )

        layout.add_widget(info)
        layout.add_widget(provider_input)
        layout.add_widget(model_input)
        layout.add_widget(key_input)
        layout.add_widget(save_button)
        layout.add_widget(BodyLabel(text=f"빌드: {APP_BUILD_LABEL}", size_hint_y=None, height=dp(38)))
        self.root_widget.set_status("Claude API와 생성 방식을 설정합니다.")
        self.root_widget.set_content(layout)

    def start_recording(self) -> None:
        if self.root_widget is None:
            return

        path = self._recordings_dir() / f"{datetime.now():%Y-%m-%d_%H%M%S}_{uuid4()}.wav"
        self._log_event(f"ui.start_recording target={path}")
        try:
            if not has_record_audio_permission():
                request_record_audio_permission()
                raise AndroidRecorderError("마이크 권한이 아직 허용되지 않았습니다.")
            self.recorder.start(path)
        except AndroidRecorderError as exc:
            self._set_result(f"녹음 시작 실패\n\n{exc}\n\n{self._export_log_for_user()}")
            self._notify_user("녹음 시작 실패", str(exc))
            return

        self.latest_recording = path
        if self.record_button is not None:
            self.record_button.disabled = True
        if self.stop_button is not None:
            self.stop_button.disabled = False
        self._set_status("녹음 중입니다. 말을 마치면 녹음 중지를 누르세요.")
        self._set_result(f"녹음 중...\n\n예상 저장 위치:\n{path}")

    def stop_recording(self) -> None:
        try:
            path = self.recorder.stop()
        except AndroidRecorderError as exc:
            self._set_record_buttons(False)
            self._set_result(f"녹음 종료 실패\n\n{exc}\n\n{self._export_log_for_user()}")
            self._notify_user("녹음 종료 실패", str(exc))
            return

        self._set_record_buttons(False)
        self.latest_recording = path
        public_location = self._export_recording_for_user(path)
        recording_ok, recording_info = self._describe_recording(path)
        self._set_result(
            f"{recording_info}\n\n{public_location}\n\nSTT와 명세 생성을 시작합니다."
        )
        if not recording_ok:
            return
        threading.Thread(target=self.generate_from_wav, args=(path,), daemon=True).start()

    def generate_from_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            self._set_status("텍스트를 먼저 입력하세요.")
            return
        threading.Thread(target=self._generate_text_worker, args=(text,), daemon=True).start()

    def generate_from_wav(self, wav_path: Path) -> None:
        self._log_event(f"pipeline.wav started wav={wav_path}")
        self._schedule_ui("STT 처리 중", f"WAV:\n{wav_path}\n\nwhisper.cpp로 텍스트 변환 중입니다.")
        try:
            transcript = WhisperCppTranscriber(
                self._stt_config(),
                runner=self._run_stt_command,
                event_logger=self._log_event,
            ).transcribe(wav_path)
            self._log_event(f"pipeline.wav stt done chars={len(transcript.text)}")
            self._apply_settings_to_env()
            provider = self.settings.get("provider", DEFAULT_PROVIDER)
            self._schedule_ui("Claude 명세 생성 중", f"STT 결과:\n{transcript.text}\n\nprovider={provider}")
            _transcript, _idea, spec, validation, markdown_path, json_path = generate_spec_from_transcript(
                transcript=transcript,
                ideas_dir=self._ideas_dir(),
                spec_provider=provider,
                logger=self._log_event,
            )
        except (SttNotConfiguredError, SttError, LlmSpecError, ValueError) as exc:
            self._log_event(f"pipeline.wav failed: {exc}")
            self._schedule_ui("생성 실패", f"{exc}\n\n{self._export_log_for_user()}")
            return

        self._schedule_ui(
            f"저장 완료: {spec.title}",
            self._format_saved_result(spec.title, spec.summary, validation.passed, markdown_path, json_path),
        )

    def update_current_idea(self, text: str) -> None:
        if self.current_detail is None:
            return
        text = text.strip()
        if not text:
            self._set_status("수정할 transcript가 비어 있습니다.")
            return
        threading.Thread(target=self._update_worker, args=(self.current_detail, text), daemon=True).start()

    def delete_current_idea(self) -> None:
        if self.current_detail is None:
            return
        idea_id = self.current_detail.get("id", "")
        moved = soft_delete_idea(self._ideas_dir(), self._trash_dir(), idea_id)
        if moved is None:
            self._set_status("삭제할 항목을 찾지 못했습니다.")
            return
        self._notify_user("삭제 완료", "보관함에서 휴지통으로 이동했습니다.")
        self.show_library()

    def save_settings(self, provider: str, model: str, api_key: str) -> None:
        provider = provider.strip().lower() or DEFAULT_PROVIDER
        self.settings["provider"] = provider
        self.settings["anthropic_model"] = model.strip() or DEFAULT_ANTHROPIC_MODEL
        self.settings["anthropic_api_key"] = api_key.strip()
        self._settings_path().write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self._apply_settings_to_env()
        self._set_status("설정을 저장했습니다.")
        self._notify_user("설정 저장", "Claude 설정이 저장되었습니다.")

    def _generate_text_worker(self, text: str) -> None:
        provider = self.settings.get("provider", DEFAULT_PROVIDER)
        self._schedule_ui("명세 생성 중", f"provider={provider}\n\n{text}")
        try:
            self._apply_settings_to_env()
            _transcript, _idea, spec, validation, markdown_path, json_path = generate_spec_from_text(
                text=text,
                ideas_dir=self._ideas_dir(),
                spec_provider=provider,
                logger=self._log_event,
            )
        except LlmSpecError as exc:
            self._schedule_ui("생성 실패", str(exc))
            return

        self._schedule_ui(
            f"저장 완료: {spec.title}",
            self._format_saved_result(spec.title, spec.summary, validation.passed, markdown_path, json_path),
        )

    def _update_worker(self, idea: dict, text: str) -> None:
        provider = self.settings.get("provider", DEFAULT_PROVIDER)
        self._schedule_ui("수정 저장 중", f"provider={provider}\n\n{text}")
        try:
            self._apply_settings_to_env()
            transcript, refined, spec, validation, _markdown_path, _json_path = generate_spec_from_text(
                text=text,
                ideas_dir=self._scratch_dir(),
                spec_provider=provider,
                logger=self._log_event,
            )
            markdown_path, json_path = update_idea(
                idea["markdown_path"],
                idea["json_path"],
                transcript,
                refined,
                spec,
                validation,
            )
        except LlmSpecError as exc:
            self._schedule_ui("수정 실패", str(exc))
            return

        def refresh(_dt) -> None:
            found = find_idea(self._ideas_dir(), idea.get("id", ""))
            if found:
                self.show_detail(found)
            else:
                self.show_library()
            self._notify_user("수정 저장 완료", f"{markdown_path.name}\n{json_path.name}")

        Clock.schedule_once(refresh, 0)

    def _set_record_buttons(self, recording: bool) -> None:
        if self.record_button is not None:
            self.record_button.disabled = recording
        if self.stop_button is not None:
            self.stop_button.disabled = not recording

    def _settings_input(self, text: str, hint: str, password: bool = False) -> TextInput:
        return TextInput(
            text=text,
            hint_text=hint,
            password=password,
            font_name=FONT_NAME,
            font_size=sp(14),
            multiline=False,
            size_hint_y=None,
            height=dp(48),
            padding=(dp(12), dp(10), dp(12), dp(10)),
            background_color=(1, 1, 1, 1),
            foreground_color=(0.06, 0.08, 0.09, 1),
        )

    def _panel(self, **kwargs) -> Surface:
        return Surface(background=(1, 1, 1, 1), **kwargs)

    def _format_saved_result(self, title: str, summary: str, passed: bool, markdown_path: Path, json_path: Path) -> str:
        return (
            f"# {title}\n\n"
            f"{summary}\n\n"
            f"검증 통과: {passed}\n\n"
            f"Markdown:\n{markdown_path}\n\n"
            f"JSON:\n{json_path}"
        )

    def _set_status(self, text: str) -> None:
        if self.root_widget is not None:
            self.root_widget.set_status(text)

    def _set_result(self, text: str) -> None:
        if self.result_box is not None:
            self.result_box.text = text

    def _schedule_ui(self, status: str, text: str) -> None:
        Clock.schedule_once(lambda _dt: (self._set_status(status), self._set_result(text)), 0)

    def _stt_config(self) -> SttConfig:
        return SttConfig(
            binary_path=self._first_existing(
                self._app_output_dir() / "bin" / "whisper-cli",
                Path(__file__).resolve().parent / "bin" / "whisper-cli",
            ),
            model_path=self._first_existing(
                self._app_output_dir() / "models" / "ggml-small-q5_1.bin",
                self._app_output_dir() / "models" / "whisper-small-q5_1.bin",
                Path(__file__).resolve().parent / "models" / "ggml-small-q5_1.bin",
                Path(__file__).resolve().parent / "models" / "whisper-small-q5_1.bin",
            ),
            language="ko",
            threads=4,
        )

    def _run_stt_command(self, command: list[str], timeout_sec: int) -> str:
        self._log_event(f"stt.subprocess starting timeout={timeout_sec}s")
        return run_whisper_command(command, timeout_sec)

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]

    def _apply_settings_to_env(self) -> None:
        key = self.settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        model = self.settings.get("anthropic_model") or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        os.environ["ANTHROPIC_MODEL"] = model

    def _load_settings(self) -> dict:
        path = self._settings_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _settings_path(self) -> Path:
        path = self._app_output_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _app_output_dir(self) -> Path:
        return Path(self.user_data_dir) / "output"

    def _ideas_dir(self) -> Path:
        path = self._app_output_dir() / "ideas"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _trash_dir(self) -> Path:
        path = self._app_output_dir() / "trash"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _scratch_dir(self) -> Path:
        path = self._app_output_dir() / "scratch"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _recordings_dir(self) -> Path:
        path = self._app_output_dir() / "recordings"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _describe_recording(self, path: Path) -> tuple[bool, str]:
        try:
            result = inspect_wav(path)
            size_kb = path.stat().st_size / 1024
            ok = path.exists() and path.stat().st_size > 44 and result.duration_sec >= 0.5
            return ok, (
                f"녹음 파일 확인: {'정상' if ok else '비정상'}\n"
                f"파일 크기: {size_kb:.1f} KB\n"
                f"길이: {result.duration_sec:.2f}초\n"
                f"평균 진폭: {result.average_amplitude:.5f}\n"
                f"최대 진폭: {result.peak_amplitude:.5f}\n"
                f"형식: {result.sample_rate}Hz mono WAV"
            )
        except Exception as exc:
            self._log_event(f"recording inspection failed: {exc}")
            return False, f"파일 정보 확인 실패: {exc}"

    def _export_recording_for_user(self, path: Path) -> str:
        try:
            location = export_wav_to_downloads(path)
            return f"다운로드 폴더 복사: {location}"
        except Exception as exc:
            self._log_event(f"recording public export failed: {exc}")
            return f"다운로드 폴더 복사 실패: {exc}"

    def _diagnostics_log_path(self) -> Path:
        return self._app_output_dir() / "voice2spec_diagnostics.log"

    def _export_log_for_user(self) -> str:
        log_path = self._diagnostics_log_path()
        try:
            location = export_file_to_downloads(log_path, mime_type="text/plain")
            return f"진단 로그: {location}"
        except Exception as exc:
            return f"진단 로그 복사 실패: {exc}\n내부 로그: {log_path}"

    def _log_event(self, message: str) -> None:
        try:
            log_path = self._diagnostics_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat(timespec="seconds")
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{timestamp} [{APP_BUILD_LABEL}] {message}\n")
        except Exception:
            pass

    def _write_startup_crash(self, exc: Exception) -> None:
        try:
            log_path = self._diagnostics_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat(timespec="seconds")
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(
                    f"{timestamp} [{APP_BUILD_LABEL}] startup crash: "
                    f"{type(exc).__name__}: {exc}\n"
                )
        except Exception:
            pass

    def _notify_user(self, title: str, text: str) -> None:
        self._show_android_toast(f"{title}\n{text}")
        self._show_popup(title, text)

    def _show_popup(self, title: str, text: str) -> None:
        def open_popup(_dt) -> None:
            content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))
            message = BodyLabel(text=text)
            close_button = AppButton(text="확인", background_color=(0.00, 0.45, 0.40, 1))
            content.add_widget(message)
            content.add_widget(close_button)
            popup = Popup(title=title, content=content, size_hint=(0.92, 0.62), auto_dismiss=True)
            close_button.bind(on_press=lambda *_args: popup.dismiss())
            popup.open()

        Clock.schedule_once(open_popup, 0)

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
