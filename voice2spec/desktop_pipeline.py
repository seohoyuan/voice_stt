from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agents import BasicValidator, RuleBasedRefiner, RuleBasedSpecifier
from .llm_specifier import ApiSpecifier, LlmSpecError, provider_from_name
from .models import RefinedIdea, SpecDocument, TranscriptResult, ValidationResult
from .recorder import RecordingConfig, RecordingResult, record_wav
from .storage import save_idea
from .stt import SttConfig, WhisperCppTranscriber


PipelineLogger = Callable[[str], None]


@dataclass(frozen=True)
class DesktopPipelineConfig:
    recordings_dir: Path
    ideas_dir: Path
    duration_sec: float = 10.0
    stt_config: SttConfig | None = None
    spec_provider: str = "rule"


@dataclass(frozen=True)
class DesktopPipelineResult:
    recording: RecordingResult
    transcript: TranscriptResult
    idea: RefinedIdea
    spec: SpecDocument
    validation: ValidationResult
    markdown_path: Path
    json_path: Path


def run_desktop_pipeline(
    config: DesktopPipelineConfig,
    logger: PipelineLogger | None = None,
) -> DesktopPipelineResult:
    _log(logger, f"record.start duration={config.duration_sec}s")
    recording = record_wav(
        RecordingConfig(
            duration_sec=config.duration_sec,
            output_dir=config.recordings_dir,
        )
    )
    _log(
        logger,
        "record.done "
        f"path={recording.wav_path} duration={recording.duration_sec:.2f}s "
        f"avg_amp={recording.average_amplitude:.4f}",
    )

    if config.stt_config is None:
        raise ValueError("노트북 MVP에서 STT를 실행하려면 --whisper-bin 과 --whisper-model 이 필요합니다.")

    _log(logger, "stt.start")
    transcript = WhisperCppTranscriber(config.stt_config, event_logger=logger).transcribe(recording.wav_path)
    _log(logger, f"stt.done chars={len(transcript.text)}")

    refiner = RuleBasedRefiner()
    idea = refiner.refine(transcript)
    _log(logger, f"refine.done core_chars={len(idea.core)}")

    specifier = _specifier_for(config.spec_provider)
    _log(logger, f"spec.start provider={config.spec_provider}")
    spec = specifier.specify(idea)
    _log(logger, f"spec.done title={spec.title!r} screens={len(spec.screens)}")

    validator = BasicValidator()
    validation = validator.validate(idea, spec)
    _log(logger, f"validate.done passed={validation.passed} issues={len(validation.issues)}")

    markdown_path, json_path = save_idea(config.ideas_dir, transcript, idea, spec, validation)
    _log(logger, f"save.done markdown={markdown_path} json={json_path}")

    return DesktopPipelineResult(
        recording=recording,
        transcript=transcript,
        idea=idea,
        spec=spec,
        validation=validation,
        markdown_path=markdown_path,
        json_path=json_path,
    )


def generate_spec_from_text(
    text: str,
    ideas_dir: Path,
    spec_provider: str = "rule",
    logger: PipelineLogger | None = None,
) -> tuple[TranscriptResult, RefinedIdea, SpecDocument, ValidationResult, Path, Path]:
    transcript = TranscriptResult(text=text, language="ko", confidence=1.0)
    idea = RuleBasedRefiner().refine(transcript)
    _log(logger, f"refine.done core_chars={len(idea.core)}")
    spec = _specifier_for(spec_provider).specify(idea)
    _log(logger, f"spec.done title={spec.title!r} screens={len(spec.screens)}")
    validation = BasicValidator().validate(idea, spec)
    markdown_path, json_path = save_idea(ideas_dir, transcript, idea, spec, validation)
    _log(logger, f"save.done markdown={markdown_path} json={json_path}")
    return transcript, idea, spec, validation, markdown_path, json_path


def _specifier_for(provider: str):
    normalized = provider.strip().lower()
    if normalized == "rule":
        return RuleBasedSpecifier()
    try:
        return ApiSpecifier(provider_from_name(normalized))
    except LlmSpecError:
        raise


def _log(logger: PipelineLogger | None, message: str) -> None:
    if logger is not None:
        logger(message)
