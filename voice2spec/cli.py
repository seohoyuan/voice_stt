from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agents import run_pipeline
from .desktop_pipeline import DesktopPipelineConfig, generate_spec_from_text, run_desktop_pipeline
from .llm_specifier import LlmSpecError
from .recorder import (
    RecordingConfig,
    RecordingDependencyError,
    RecordingValidationError,
    default_recordings_dir,
    record_wav,
)
from .storage import (
    default_ideas_dir,
    default_trash_dir,
    find_idea,
    list_deleted_ideas,
    list_ideas,
    restore_idea,
    save_idea,
    soft_delete_idea,
    update_idea,
)
from .stt import SttConfig, SttError, WhisperCppTranscriber


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _configure_stdout()

    parser = argparse.ArgumentParser(description="Voice2Spec Python prototype")
    parser.add_argument(
        "--output-dir",
        default=str(default_ideas_dir()),
        help="Markdown/JSON 결과 저장 폴더",
    )
    parser.add_argument(
        "--trash-dir",
        default=str(default_trash_dir()),
        help="삭제된 아이디어를 보관할 휴지통 폴더",
    )
    parser.add_argument(
        "--recordings-dir",
        default=str(default_recordings_dir()),
        help="녹음 WAV 파일 저장 폴더",
    )
    parser.add_argument("--whisper-bin", help="whisper.cpp 실행 파일 경로")
    parser.add_argument("--whisper-model", help="whisper.cpp 모델 파일 경로")
    parser.add_argument("--stt-language", default="ko", help="STT 언어 코드, 기본 ko")
    parser.add_argument(
        "--provider",
        default="rule",
        choices=["rule", "openai", "codex", "claude", "anthropic"],
        help="명세 생성 provider. 기본 rule, API는 openai/codex/claude",
    )

    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser("new", help="새 아이디어를 명세서로 변환")
    new_parser.add_argument("input", nargs="*", help="아이디어 텍스트 또는 WAV 파일 경로")
    new_parser.add_argument("--stdin", action="store_true", help="표준 입력에서 아이디어 텍스트 읽기")

    transcribe_parser = subparsers.add_parser("transcribe", help="WAV 파일을 whisper.cpp로 텍스트화")
    transcribe_parser.add_argument("wav_path", help="녹음 WAV 파일 경로")

    record_parser = subparsers.add_parser("record", help="마이크로 WAV 파일 녹음")
    record_parser.add_argument("--duration", type=float, default=10.0, help="녹음 길이(초), 기본 10초")
    record_parser.add_argument("--generate", action="store_true", help="녹음 후 현재 mock STT 파이프라인으로 명세 생성")

    desktop_parser = subparsers.add_parser(
        "desktop-run",
        help="노트북 마이크 녹음 -> whisper STT -> API/rule 명세 생성 -> 저장",
    )
    desktop_parser.add_argument("--duration", type=float, default=10.0, help="녹음 길이(초), 기본 10초")

    spec_parser = subparsers.add_parser("spec", help="텍스트를 API/rule provider로 명세서로 변환")
    spec_parser.add_argument("input", nargs="*", help="아이디어 텍스트")
    spec_parser.add_argument("--stdin", action="store_true", help="표준 입력에서 아이디어 텍스트 읽기")

    subparsers.add_parser("list", help="저장된 아이디어 목록 보기")

    show_parser = subparsers.add_parser("show", help="저장된 아이디어 열람")
    show_parser.add_argument("query", help="목록 번호, ID 앞부분, 또는 제목 일부")

    edit_parser = subparsers.add_parser("edit", help="아이디어 Markdown 열기 또는 텍스트 교체")
    edit_parser.add_argument("query", help="목록 번호, ID 앞부분, 또는 제목 일부")
    edit_parser.add_argument("--text", nargs="*", help="새 원본 텍스트로 명세서 재생성")
    edit_parser.add_argument("--stdin", action="store_true", help="표준 입력에서 새 원본 텍스트 읽기")

    delete_parser = subparsers.add_parser("delete", help="아이디어를 휴지통으로 이동")
    delete_parser.add_argument("query", help="목록 번호, ID 앞부분, 또는 제목 일부")

    subparsers.add_parser("trash", help="휴지통 목록 보기")

    restore_parser = subparsers.add_parser("restore", help="휴지통에서 아이디어 복구")
    restore_parser.add_argument("query", help="휴지통 목록 번호, ID 앞부분, 또는 제목 일부")

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    trash_dir = Path(args.trash_dir)
    recordings_dir = Path(args.recordings_dir)
    stt_config = _stt_config_from_args(args)

    if args.command == "list":
        _list_command(output_dir)
        return

    if args.command == "show":
        _show_command(output_dir, args.query)
        return

    if args.command == "new":
        text = _read_text_input(args.input, args.stdin, "아이디어를 입력하세요: ")
        _new_command(output_dir, text, stt_config)
        return

    if args.command == "transcribe":
        _transcribe_command(args.wav_path, stt_config)
        return

    if args.command == "record":
        _record_command(recordings_dir, output_dir, args.duration, args.generate, stt_config)
        return

    if args.command == "desktop-run":
        _desktop_run_command(recordings_dir, output_dir, args.duration, stt_config, args.provider)
        return

    if args.command == "spec":
        text = _read_text_input(args.input, args.stdin, "아이디어를 입력하세요: ")
        _spec_command(output_dir, text, args.provider)
        return

    if args.command == "edit":
        _edit_command(output_dir, args.query, args.text, args.stdin)
        return

    if args.command == "delete":
        _delete_command(output_dir, trash_dir, args.query)
        return

    if args.command == "trash":
        _trash_command(trash_dir)
        return

    if args.command == "restore":
        _restore_command(trash_dir, output_dir, args.query)
        return

    if args.command is None:
        parser.print_help()


def _read_text_input(parts: list[str] | None, read_stdin: bool, prompt: str) -> str:
    if read_stdin:
        return input(prompt).strip()

    text = " ".join(parts or []).strip()
    if text:
        return text

    return input(prompt).strip()


def _stt_config_from_args(args) -> SttConfig | None:
    if not args.whisper_bin and not args.whisper_model:
        return None
    return SttConfig(
        binary_path=Path(args.whisper_bin) if args.whisper_bin else None,
        model_path=Path(args.whisper_model) if args.whisper_model else None,
        language=args.stt_language,
    )


def _new_command(output_dir: Path, text_or_wav: str, stt_config: SttConfig | None = None) -> None:
    transcriber = None
    if Path(text_or_wav).suffix.lower() == ".wav" and stt_config is not None:
        transcriber = WhisperCppTranscriber(stt_config)

    transcript, idea, spec, validation = run_pipeline(text_or_wav, transcriber=transcriber)
    markdown_path, json_path = save_idea(
        output_dir=output_dir,
        transcript=transcript,
        idea=idea,
        spec=spec,
        validation=validation,
    )

    print(f"제목: {spec.title}")
    print(f"요약: {spec.summary}")
    print(f"검증 통과: {validation.passed}")
    print(f"Markdown: {markdown_path}")
    print(f"JSON: {json_path}")


def _transcribe_command(wav_path: str, stt_config: SttConfig | None) -> None:
    try:
        transcriber = WhisperCppTranscriber(stt_config)
        transcript = transcriber.transcribe(wav_path)
    except SttError as exc:
        print(f"STT 실패: {exc}")
        return

    print(transcript.text)


def _record_command(
    recordings_dir: Path,
    output_dir: Path,
    duration: float,
    generate: bool,
    stt_config: SttConfig | None = None,
) -> None:
    print(f"녹음 시작: {duration:.1f}초")
    try:
        result = record_wav(
            RecordingConfig(
                duration_sec=duration,
                output_dir=recordings_dir,
            ),
        )
    except RecordingDependencyError as exc:
        print(str(exc))
        return
    except (RecordingValidationError, ValueError) as exc:
        print(f"녹음 실패: {exc}")
        return

    print(f"녹음 완료: {result.wav_path}")
    print(f"길이: {result.duration_sec:.2f}초")
    print(f"평균 진폭: {result.average_amplitude:.4f}")

    if generate:
        print("명세 생성: whisper.cpp 설정이 있으면 실제 STT를 사용합니다.")
        _new_command(output_dir, str(result.wav_path), stt_config)


def _desktop_run_command(
    recordings_dir: Path,
    output_dir: Path,
    duration: float,
    stt_config: SttConfig | None,
    provider: str,
) -> None:
    try:
        result = run_desktop_pipeline(
            DesktopPipelineConfig(
                recordings_dir=recordings_dir,
                ideas_dir=output_dir,
                duration_sec=duration,
                stt_config=stt_config,
                spec_provider=provider,
            ),
            logger=lambda message: print(f"[desktop] {message}"),
        )
    except (RecordingDependencyError, RecordingValidationError, SttError, LlmSpecError, ValueError) as exc:
        print(f"desktop-run 실패: {exc}")
        return

    print("\n완료")
    print(f"WAV: {result.recording.wav_path}")
    print(f"Transcript: {result.transcript.text}")
    print(f"Title: {result.spec.title}")
    print(f"Markdown: {result.markdown_path}")
    print(f"JSON: {result.json_path}")


def _spec_command(output_dir: Path, text: str, provider: str) -> None:
    try:
        _transcript, _idea, spec, validation, markdown_path, json_path = generate_spec_from_text(
            text=text,
            ideas_dir=output_dir,
            spec_provider=provider,
            logger=lambda message: print(f"[spec] {message}"),
        )
    except LlmSpecError as exc:
        print(f"명세 생성 실패: {exc}")
        return

    print(f"Title: {spec.title}")
    print(f"Summary: {spec.summary}")
    print(f"Validation: {validation.passed}")
    print(f"Markdown: {markdown_path}")
    print(f"JSON: {json_path}")


def _list_command(output_dir: Path) -> None:
    ideas = list_ideas(output_dir)
    if not ideas:
        print("저장된 아이디어가 아직 없습니다.")
        return

    _print_idea_list(ideas)


def _show_command(output_dir: Path, query: str) -> None:
    idea = find_idea(output_dir, query)
    if idea is None:
        print("해당 아이디어를 찾지 못했습니다.")
        return

    markdown_path = idea["markdown_path"]
    if not markdown_path.exists():
        print(f"Markdown 파일이 없습니다: {markdown_path}")
        return

    print(markdown_path.read_text(encoding="utf-8"))


def _edit_command(output_dir: Path, query: str, text_parts: list[str] | None, read_stdin: bool) -> None:
    idea = find_idea(output_dir, query)
    if idea is None:
        print("해당 아이디어를 찾지 못했습니다.")
        return

    if text_parts is not None or read_stdin:
        replacement = _read_text_input(text_parts, read_stdin, "새 원본 텍스트를 입력하세요: ")
        transcript, refined, spec, validation = run_pipeline(replacement)
        markdown_path, json_path = update_idea(
            markdown_path=idea["markdown_path"],
            json_path=idea["json_path"],
            transcript=transcript,
            idea=refined,
            spec=spec,
            validation=validation,
        )
        print(f"수정 완료: {spec.title}")
        print(f"Markdown: {markdown_path}")
        print(f"JSON: {json_path}")
        return

    markdown_path = idea["markdown_path"]
    if not markdown_path.exists():
        print(f"Markdown 파일이 없습니다: {markdown_path}")
        return

    print(f"편집할 파일: {markdown_path}")
    if hasattr(os, "startfile"):
        os.startfile(markdown_path)
    else:
        print("이 환경에서는 자동으로 편집기를 열 수 없습니다. 위 파일을 직접 열어주세요.")


def _delete_command(output_dir: Path, trash_dir: Path, query: str) -> None:
    moved = soft_delete_idea(output_dir, trash_dir, query)
    if moved is None:
        print("해당 아이디어를 찾지 못했습니다.")
        return

    print(f"휴지통으로 이동: {moved['title']}")
    print(f"Markdown: {moved['markdown_path']}")
    print(f"JSON: {moved['json_path']}")


def _trash_command(trash_dir: Path) -> None:
    ideas = list_deleted_ideas(trash_dir)
    if not ideas:
        print("휴지통이 비어 있습니다.")
        return

    _print_idea_list(ideas)


def _restore_command(trash_dir: Path, output_dir: Path, query: str) -> None:
    moved = restore_idea(trash_dir, output_dir, query)
    if moved is None:
        print("휴지통에서 해당 아이디어를 찾지 못했습니다.")
        return

    print(f"복구 완료: {moved['title']}")
    print(f"Markdown: {moved['markdown_path']}")
    print(f"JSON: {moved['json_path']}")


def _print_idea_list(ideas: list[dict]) -> None:
    for index, idea in enumerate(ideas, start=1):
        created_at = idea["created_at"][:19].replace("T", " ")
        updated_at = idea.get("updated_at", "")[:19].replace("T", " ")
        suffix = f" | 수정 {updated_at}" if updated_at else ""
        print(f"{index}. {idea['title']} | {created_at}{suffix}")
        if idea["summary"]:
            print(f"   {idea['summary']}")


if __name__ == "__main__":
    main()
