from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PipelineStage(str, Enum):
    RECORDER = "recorder"
    TRANSCRIBER = "transcriber"
    REFINER = "refiner"
    SPECIFIER = "specifier"
    VALIDATOR = "validator"
    STORAGE = "storage"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    language: str = "ko"
    confidence: float = 1.0
    segments: list[Segment] = field(default_factory=list)


@dataclass(frozen=True)
class RefinedIdea:
    core: str
    ambiguities: list[str]
    assumptions: list[str]


@dataclass(frozen=True)
class ScreenWireframeText:
    name: str
    purpose: str
    wireframe: str
    actions: list[str]


@dataclass(frozen=True)
class SpecDocument:
    title: str
    summary: str
    user_stories: list[str]
    screens: list[ScreenWireframeText]
    data_model: list[str]
    tech_hints: list[str]


@dataclass(frozen=True)
class Issue:
    severity: IssueSeverity
    message: str
    section: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    issues: list[Issue]
    suggested_followups: list[str]
