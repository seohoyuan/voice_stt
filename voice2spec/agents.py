from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .models import (
    Issue,
    IssueSeverity,
    RefinedIdea,
    ScreenWireframeText,
    SpecDocument,
    TranscriptResult,
    ValidationResult,
)


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, source: str | Path) -> TranscriptResult:
        raise NotImplementedError


class Refiner(ABC):
    @abstractmethod
    def refine(self, transcript: TranscriptResult) -> RefinedIdea:
        raise NotImplementedError


class Specifier(ABC):
    @abstractmethod
    def specify(self, idea: RefinedIdea) -> SpecDocument:
        raise NotImplementedError


class Validator(ABC):
    @abstractmethod
    def validate(self, idea: RefinedIdea, spec: SpecDocument) -> ValidationResult:
        raise NotImplementedError


class MockTranscriber(Transcriber):
    def transcribe(self, source: str | Path) -> TranscriptResult:
        text = str(source).strip()
        if Path(text).suffix.lower() == ".wav":
            text = "WAV 입력이 들어왔습니다. 실제 STT 엔진은 다음 단계에서 연결합니다."

        return TranscriptResult(
            text=text,
            language="ko",
            confidence=0.95,
        )


class RuleBasedRefiner(Refiner):
    def refine(self, transcript: TranscriptResult) -> RefinedIdea:
        cleaned = _remove_speech_fillers(transcript.text)
        if not cleaned:
            cleaned = "사용자가 아직 아이디어 내용을 입력하지 않았습니다."

        domain = detect_domain(cleaned)
        return RefinedIdea(
            core=cleaned[:180],
            ambiguities=[
                f"{domain.label}의 핵심 사용자가 아직 구체적이지 않습니다.",
                "첫 버전에 꼭 필요한 기능 범위가 아직 확정되지 않았습니다.",
            ],
            assumptions=[
                "개인용 MVP로 시작합니다.",
                f"{domain.label}에 맞는 3개 핵심 화면부터 구현합니다.",
            ],
        )


class RuleBasedSpecifier(Specifier):
    def specify(self, idea: RefinedIdea) -> SpecDocument:
        domain = detect_domain(idea.core)
        title = _make_title(idea.core, domain)
        summary = _make_summary(idea.core)

        return SpecDocument(
            title=title,
            summary=summary,
            user_stories=domain.user_stories,
            screens=domain.screens,
            data_model=domain.data_model,
            tech_hints=[
                "Python 프로토타입에서는 dataclass와 파일 저장으로 먼저 검증합니다.",
                domain.tech_hint,
                "APK 전환 시 CLI 흐름을 Kivy 화면으로 감싸는 방식이 가장 단순합니다.",
            ],
        )


class BasicValidator(Validator):
    def validate(self, idea: RefinedIdea, spec: SpecDocument) -> ValidationResult:
        issues: list[Issue] = []

        if not spec.title.strip():
            issues.append(Issue(IssueSeverity.ERROR, "제목이 비어 있습니다.", "title"))
        if not spec.summary.strip():
            issues.append(Issue(IssueSeverity.ERROR, "요약이 비어 있습니다.", "summary"))
        if len(spec.user_stories) < 3:
            issues.append(Issue(IssueSeverity.ERROR, "사용자 스토리는 최소 3개가 필요합니다.", "user_stories"))
        if not 1 <= len(spec.screens) <= 7:
            issues.append(Issue(IssueSeverity.ERROR, "화면 수는 1~7개여야 합니다.", "screens"))
        if any(not screen.wireframe.strip() for screen in spec.screens):
            issues.append(Issue(IssueSeverity.ERROR, "비어 있는 와이어프레임이 있습니다.", "screens"))
        if idea.core and idea.core[:8] not in spec.summary and idea.core[:8] not in spec.title:
            issues.append(Issue(IssueSeverity.WARNING, "명세서가 원본 핵심 아이디어를 충분히 반영하는지 확인이 필요합니다.", "summary"))

        followups = []
        if idea.ambiguities:
            followups.append("대상 사용자와 첫 버전 기능 범위를 정하면 명세 품질이 좋아집니다.")

        return ValidationResult(
            passed=not any(issue.severity == IssueSeverity.ERROR for issue in issues),
            issues=issues,
            suggested_followups=followups,
        )


def run_pipeline(
    text_or_wav: str | Path,
    transcriber: Transcriber | None = None,
) -> tuple[TranscriptResult, RefinedIdea, SpecDocument, ValidationResult]:
    transcriber = transcriber or MockTranscriber()
    refiner = RuleBasedRefiner()
    specifier = RuleBasedSpecifier()
    validator = BasicValidator()

    transcript = transcriber.transcribe(text_or_wav)
    idea = refiner.refine(transcript)
    spec = specifier.specify(idea)
    validation = validator.validate(idea, spec)
    return transcript, idea, spec, validation


@dataclass(frozen=True)
class DomainTemplate:
    key: str
    label: str
    keywords: tuple[str, ...]
    fallback_title: str
    user_stories: list[str]
    screens: list[ScreenWireframeText]
    data_model: list[str]
    tech_hint: str


def detect_domain(text: str) -> DomainTemplate:
    normalized = text.lower()
    scored = []
    for template in DOMAIN_TEMPLATES:
        score = sum(1 for keyword in template.keywords if keyword in normalized)
        scored.append((score, template))

    best_score, best_template = max(scored, key=lambda item: item[0])
    return best_template if best_score > 0 else GENERAL_TEMPLATE


def _make_summary(core: str) -> str:
    return f"{core[:45]}..." if len(core) > 45 else core


def _make_title(core: str, domain: DomainTemplate) -> str:
    words = core.replace(",", " ").replace(".", " ").split()
    if not words:
        return domain.fallback_title

    ignored = {"앱", "서비스", "도구", "만들고", "싶어", "만들어줘"}
    picked = [word for word in words if word not in ignored]
    title = "".join(picked[:2])[:10]
    return title or domain.fallback_title


def _remove_speech_fillers(text: str) -> str:
    fillers = {"어", "음", "아", "그", "그러니까", "뭐랄까"}
    words = []
    for word in text.split():
        stripped = word.strip(",.?! ")
        if stripped in fillers:
            continue
        words.append(word)
    return " ".join(words)


READING_TEMPLATE = DomainTemplate(
    key="reading",
    label="독서 기록",
    keywords=("책", "독서", "읽은", "서평", "문장", "요약", "질문"),
    fallback_title="독서기록",
    user_stories=[
        "책을 다 읽었을 때, 핵심 생각을 빠르게 남기고 싶다, 왜냐하면 읽은 직후의 감상이 가장 선명하기 때문이다.",
        "기록을 다시 볼 때, 책별 요약과 질문을 한눈에 보고 싶다, 왜냐하면 다음 독서나 글쓰기에 연결하고 싶기 때문이다.",
        "좋은 문장을 발견했을 때, 인용과 내 생각을 함께 저장하고 싶다, 왜냐하면 나중에 다시 활용해야 하기 때문이다.",
    ],
    screens=[
        ScreenWireframeText(
            name="책 목록",
            purpose="읽은 책과 최근 기록을 모아 보여줍니다.",
            wireframe=(
                "+----------------------+\n"
                "| 독서 기록       [추가]|\n"
                "+----------------------+\n"
                "| 검색: 책 제목/저자    |\n"
                "| [책 카드] 요약 3줄    |\n"
                "| [책 카드] 질문 2개    |\n"
                "+----------------------+"
            ),
            actions=["책 추가", "책 검색", "기록 상세 열기"],
        ),
        ScreenWireframeText(
            name="음성 기록",
            purpose="책에 대한 감상을 음성이나 텍스트로 입력합니다.",
            wireframe=(
                "+----------------------+\n"
                "| 기록 남기기           |\n"
                "+----------------------+\n"
                "| 책: [선택/입력]       |\n"
                "| [녹음] [텍스트 입력]  |\n"
                "| [요약 생성]           |\n"
                "+----------------------+"
            ),
            actions=["책 선택", "감상 녹음", "요약 생성"],
        ),
        ScreenWireframeText(
            name="요약 결과",
            purpose="감상 요약, 핵심 문장, 다음 질문을 보여줍니다.",
            wireframe=(
                "+----------------------+\n"
                "| 요약 | 질문 | 원본    |\n"
                "+----------------------+\n"
                "| 한 줄 요약            |\n"
                "| 기억할 문장           |\n"
                "| 다음 독서 질문        |\n"
                "+----------------------+"
            ),
            actions=["수정", "질문 추가", "Markdown 저장"],
        ),
    ],
    data_model=["Book", "ReadingNote", "FollowUpQuestion"],
    tech_hint="초기에는 책 제목, 원본 메모, 요약, 질문을 JSON/Markdown으로 저장하면 충분합니다.",
)


DELIVERY_TEMPLATE = DomainTemplate(
    key="delivery",
    label="지역 배달",
    keywords=("배달", "주문", "가게", "반찬", "음식", "메뉴", "동네"),
    fallback_title="동네배달",
    user_stories=[
        "퇴근길에 저녁거리를 고를 때, 가까운 가게의 메뉴를 한곳에서 보고 싶다, 왜냐하면 여러 가게를 따로 찾기 번거롭기 때문이다.",
        "바로 먹을 반찬이 필요할 때, 빠르게 받을 수 있는 메뉴만 보고 싶다, 왜냐하면 기다리는 시간을 줄이고 싶기 때문이다.",
        "마음에 든 가게가 있을 때, 지난 주문을 다시 반복하고 싶다, 왜냐하면 매번 같은 정보를 입력하고 싶지 않기 때문이다.",
    ],
    screens=[
        ScreenWireframeText(
            name="동네 홈",
            purpose="가까운 가게와 빠른 배달 메뉴를 보여줍니다.",
            wireframe=(
                "+----------------------+\n"
                "| 동네 반찬        [검색]|\n"
                "+----------------------+\n"
                "| 위치: 우리 동네       |\n"
                "| [빠른 배달 메뉴]      |\n"
                "| [가게 카드] [주문]    |\n"
                "+----------------------+"
            ),
            actions=["위치 변경", "메뉴 검색", "가게 상세 열기"],
        ),
        ScreenWireframeText(
            name="가게 상세",
            purpose="가게 정보와 주문 가능한 메뉴를 확인합니다.",
            wireframe=(
                "+----------------------+\n"
                "| 가게 이름             |\n"
                "+----------------------+\n"
                "| 배달 예상 30분        |\n"
                "| [메뉴] [수량] [+]     |\n"
                "| 장바구니 합계         |\n"
                "+----------------------+"
            ),
            actions=["메뉴 담기", "수량 변경", "장바구니 보기"],
        ),
        ScreenWireframeText(
            name="주문 확인",
            purpose="주문 내용과 배달 정보를 확인합니다.",
            wireframe=(
                "+----------------------+\n"
                "| 주문 확인             |\n"
                "+----------------------+\n"
                "| 메뉴 목록             |\n"
                "| 배달 주소             |\n"
                "| [주문 요청]           |\n"
                "+----------------------+"
            ),
            actions=["주소 수정", "요청사항 입력", "주문 요청"],
        ),
    ],
    data_model=["Store", "MenuItem", "Order"],
    tech_hint="개인 프로토타입에서는 실제 결제 없이 메뉴 탐색과 주문 요청 흐름만 먼저 검증합니다.",
)


MEETING_TEMPLATE = DomainTemplate(
    key="meeting",
    label="회의 정리",
    keywords=("회의", "미팅", "할 일", "액션", "결정", "회의록", "초안"),
    fallback_title="회의정리",
    user_stories=[
        "회의가 끝났을 때, 논의 내용을 바로 할 일로 정리하고 싶다, 왜냐하면 결정 사항을 놓치기 쉽기 때문이다.",
        "다음 회의를 준비할 때, 지난 결정과 미완료 작업을 보고 싶다, 왜냐하면 맥락을 빨리 회복해야 하기 때문이다.",
        "아이디어 회의 중에, 화면 초안을 바로 보고 싶다, 왜냐하면 말로 나온 기능을 구체화해야 하기 때문이다.",
    ],
    screens=[
        ScreenWireframeText(
            name="회의 목록",
            purpose="최근 회의와 미완료 작업을 보여줍니다.",
            wireframe=(
                "+----------------------+\n"
                "| 회의 정리       [추가]|\n"
                "+----------------------+\n"
                "| 오늘의 미완료 작업    |\n"
                "| [회의 카드] 결정 3개  |\n"
                "| [회의 카드] 할 일 5개 |\n"
                "+----------------------+"
            ),
            actions=["새 회의 시작", "회의 검색", "작업 열기"],
        ),
        ScreenWireframeText(
            name="회의 입력",
            purpose="회의 내용을 텍스트나 음성으로 입력합니다.",
            wireframe=(
                "+----------------------+\n"
                "| 회의 내용 입력        |\n"
                "+----------------------+\n"
                "| 참석자 / 주제         |\n"
                "| [원본 입력 영역]      |\n"
                "| [정리하기]            |\n"
                "+----------------------+"
            ),
            actions=["참석자 입력", "회의 내용 붙여넣기", "정리 생성"],
        ),
        ScreenWireframeText(
            name="정리 결과",
            purpose="결정 사항, 할 일, 화면 초안을 나눠 보여줍니다.",
            wireframe=(
                "+----------------------+\n"
                "| 결정 | 할 일 | 화면   |\n"
                "+----------------------+\n"
                "| 결정 사항 목록        |\n"
                "| 담당자별 할 일        |\n"
                "| 화면 초안             |\n"
                "+----------------------+"
            ),
            actions=["담당자 수정", "완료 체크", "Markdown 저장"],
        ),
    ],
    data_model=["Meeting", "Decision", "ActionItem"],
    tech_hint="할 일에는 담당자, 마감일, 상태 필드를 두면 나중에 검색과 필터링이 쉬워집니다.",
)


GENERAL_TEMPLATE = DomainTemplate(
    key="general",
    label="아이디어",
    keywords=(),
    fallback_title="새아이디어",
    user_stories=[
        "아이디어가 떠올랐을 때, 빠르게 기록하고 싶다, 왜냐하면 흐름을 놓치고 싶지 않기 때문이다.",
        "기록 후 바로 구체적인 화면 흐름을 보고 싶다, 왜냐하면 구현 가능성을 빨리 판단하고 싶기 때문이다.",
        "나중에 다시 열어보고 싶다, 왜냐하면 여러 아이디어를 비교해야 하기 때문이다.",
    ],
    screens=[
        ScreenWireframeText(
            name="홈",
            purpose="최근 아이디어와 새 입력 진입점을 보여줍니다.",
            wireframe=(
                "+----------------------+\n"
                "| Voice2Spec    [설정] |\n"
                "+----------------------+\n"
                "| [새 아이디어 말하기] |\n"
                "| 최근 아이디어 카드   |\n"
                "| 최근 아이디어 카드   |\n"
                "+----------------------+"
            ),
            actions=["새 아이디어 시작", "최근 결과 열기", "설정 열기"],
        ),
        ScreenWireframeText(
            name="입력",
            purpose="사용자의 아이디어를 텍스트나 음성으로 받습니다.",
            wireframe=(
                "+----------------------+\n"
                "| 아이디어 입력         |\n"
                "+----------------------+\n"
                "| [텍스트 입력 영역]    |\n"
                "| [녹음 시작] [생성]    |\n"
                "+----------------------+"
            ),
            actions=["텍스트 작성", "녹음 시작", "명세 생성"],
        ),
        ScreenWireframeText(
            name="결과",
            purpose="정제된 명세와 화면 흐름을 확인합니다.",
            wireframe=(
                "+----------------------+\n"
                "| 명세서 | 화면 | 원본 |\n"
                "+----------------------+\n"
                "| 제목과 요약           |\n"
                "| 사용자 스토리         |\n"
                "| 와이어프레임          |\n"
                "+----------------------+"
            ),
            actions=["편집", "다시 생성", "Markdown 저장"],
        ),
    ],
    data_model=["Idea", "Transcript", "SpecDocument"],
    tech_hint="초기에는 원본 입력, 정제 결과, 명세 문서를 한 묶음으로 저장합니다.",
)


DOMAIN_TEMPLATES = (
    READING_TEMPLATE,
    DELIVERY_TEMPLATE,
    MEETING_TEMPLATE,
    GENERAL_TEMPLATE,
)
