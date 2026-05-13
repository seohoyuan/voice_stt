from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .models import RefinedIdea, SpecDocument, TranscriptResult, ValidationResult


def default_output_root() -> Path:
    return Path(__file__).resolve().parents[1] / "output"


def default_ideas_dir() -> Path:
    return default_output_root() / "ideas"


def default_trash_dir() -> Path:
    return default_output_root() / "trash"


def save_idea(
    output_dir: Path,
    transcript: TranscriptResult,
    idea: RefinedIdea,
    spec: SpecDocument,
    validation: ValidationResult,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    idea_id = str(uuid4())
    created_at = datetime.now().astimezone().isoformat()
    stem = f"{datetime.fromisoformat(created_at):%Y-%m-%d_%H%M%S}_{idea_id}"

    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    _write_idea_files(markdown_path, json_path, idea_id, created_at, None, transcript, idea, spec, validation)
    return markdown_path, json_path


def update_idea(
    markdown_path: Path,
    json_path: Path,
    transcript: TranscriptResult,
    idea: RefinedIdea,
    spec: SpecDocument,
    validation: ValidationResult,
) -> tuple[Path, Path]:
    data = _read_json(json_path)
    idea_id = data.get("id") or json_path.stem.split("_")[-1]
    created_at = data.get("created_at") or datetime.now().astimezone().isoformat()
    updated_at = datetime.now().astimezone().isoformat()
    _write_idea_files(markdown_path, json_path, idea_id, created_at, updated_at, transcript, idea, spec, validation)
    return markdown_path, json_path


def list_ideas(output_dir: Path) -> list[dict]:
    return _list_from_dir(output_dir)


def list_deleted_ideas(trash_dir: Path) -> list[dict]:
    return _list_from_dir(trash_dir)


def find_idea(output_dir: Path, query: str) -> dict | None:
    return _find_in_list(list_ideas(output_dir), query)


def find_deleted_idea(trash_dir: Path, query: str) -> dict | None:
    return _find_in_list(list_deleted_ideas(trash_dir), query)


def soft_delete_idea(output_dir: Path, trash_dir: Path, query: str) -> dict | None:
    idea = find_idea(output_dir, query)
    if idea is None:
        return None

    trash_dir.mkdir(parents=True, exist_ok=True)
    moved = _move_pair(idea["markdown_path"], idea["json_path"], trash_dir)
    moved["title"] = idea["title"]
    moved["id"] = idea["id"]
    return moved


def restore_idea(trash_dir: Path, output_dir: Path, query: str) -> dict | None:
    idea = find_deleted_idea(trash_dir, query)
    if idea is None:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    moved = _move_pair(idea["markdown_path"], idea["json_path"], output_dir)
    moved["title"] = idea["title"]
    moved["id"] = idea["id"]
    return moved


def render_markdown(
    idea_id: str,
    created_at: str,
    transcript: TranscriptResult,
    idea: RefinedIdea,
    spec: SpecDocument,
    validation: ValidationResult,
    updated_at: str | None = None,
) -> str:
    screens = "\n\n".join(_render_screen(index, screen) for index, screen in enumerate(spec.screens, start=1))
    stories = "\n".join(f"- {story}" for story in spec.user_stories)
    data_model = "\n".join(f"- {item}" for item in spec.data_model)
    tech_hints = "\n".join(f"- {item}" for item in spec.tech_hints)
    ambiguities = "\n".join(f"- {item}" for item in idea.ambiguities)
    assumptions = "\n".join(f"- {item}" for item in idea.assumptions)
    followups = "\n".join(f"- {item}" for item in validation.suggested_followups)
    updated_line = f"updated_at: {updated_at}\n" if updated_at else ""

    return f"""---
id: {idea_id}
created_at: {created_at}
{updated_line}language: {transcript.language}
tags: [prototype, voice2spec]
---

# {spec.title}

## 한 줄 요약
{spec.summary}

## 정제된 핵심
{idea.core}

## 사용자 스토리
{stories}

## 화면
{screens}

## 데이터 모델
{data_model}

## 구현 힌트
{tech_hints}

## 모호한 점
{ambiguities}

## 가정
{assumptions}

## 후속 질문
{followups or "- 없음"}

---
## 부록: 원본 transcript
{transcript.text}
"""


def _render_screen(index: int, screen) -> str:
    actions = "\n".join(f"- {action}" for action in screen.actions)
    return f"""### {index}. {screen.name}
목적: {screen.purpose}

```text
{screen.wireframe}
```

액션:
{actions}
"""


def _write_idea_files(
    markdown_path: Path,
    json_path: Path,
    idea_id: str,
    created_at: str,
    updated_at: str | None,
    transcript: TranscriptResult,
    idea: RefinedIdea,
    spec: SpecDocument,
    validation: ValidationResult,
) -> None:
    payload = {
        "id": idea_id,
        "created_at": created_at,
        "transcript": asdict(transcript),
        "refined_idea": asdict(idea),
        "spec_document": asdict(spec),
        "validation": asdict(validation),
    }
    if updated_at:
        payload["updated_at"] = updated_at

    _atomic_write(
        markdown_path,
        render_markdown(idea_id, created_at, transcript, idea, spec, validation, updated_at),
    )
    _atomic_write(json_path, json.dumps(payload, ensure_ascii=False, indent=2))


def _list_from_dir(directory: Path) -> list[dict]:
    if not directory.exists():
        return []

    ideas = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            data = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue

        spec = data.get("spec_document", {})
        transcript = data.get("transcript", {})
        ideas.append(
            {
                "id": data.get("id", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "title": spec.get("title", "(제목 없음)"),
                "summary": spec.get("summary", ""),
                "transcript": transcript.get("text", ""),
                "json_path": path,
                "markdown_path": path.with_suffix(".md"),
            },
        )

    return ideas


def _find_in_list(ideas: list[dict], query: str) -> dict | None:
    if not ideas:
        return None

    if query.isdigit():
        index = int(query) - 1
        if 0 <= index < len(ideas):
            return ideas[index]

    query_lower = query.lower()
    for idea in ideas:
        if idea["id"].lower().startswith(query_lower):
            return idea
        if query_lower in idea["title"].lower():
            return idea

    return None


def _move_pair(markdown_path: Path, json_path: Path, destination_dir: Path) -> dict:
    target_json = _unique_path(destination_dir / json_path.name)
    target_markdown = target_json.with_suffix(".md")

    if markdown_path.exists():
        markdown_path.replace(target_markdown)
    if json_path.exists():
        json_path.replace(target_json)

    return {
        "markdown_path": target_markdown,
        "json_path": target_json,
    }


def _unique_path(path: Path) -> Path:
    if not path.exists() and not path.with_suffix(".md").exists():
        return path

    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists() and not candidate.with_suffix(".md").exists():
            return candidate

    raise RuntimeError(f"Could not create a unique path for {path}")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, content: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)
