from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

from .agents import Specifier
from .models import RefinedIdea, ScreenWireframeText, SpecDocument


class LlmSpecError(RuntimeError):
    pass


class ApiSpecProvider:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class OpenAiSpecProvider(ApiSpecProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        if not self.api_key:
            raise LlmSpecError("OPENAI_API_KEY가 설정되지 않았습니다.")

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": "You write concise Korean MVP specs as strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "text": {"format": {"type": "json_object"}},
        }
        response = _post_json(
            "https://api.openai.com/v1/responses",
            payload,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        return _extract_openai_text(response)


class AnthropicSpecProvider(ApiSpecProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
        if not self.api_key:
            raise LlmSpecError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 1800,
            "system": "You write concise Korean MVP specs as strict JSON only.",
            "messages": [{"role": "user", "content": prompt}],
        }
        response = _post_json(
            "https://api.anthropic.com/v1/messages",
            payload,
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        return _extract_anthropic_text(response)


class ApiSpecifier(Specifier):
    def __init__(self, provider: ApiSpecProvider) -> None:
        self.provider = provider

    def specify(self, idea: RefinedIdea) -> SpecDocument:
        response_text = self.provider.generate(build_spec_prompt(idea))
        data = _loads_json_object(response_text)
        return _spec_from_dict(data)


def provider_from_name(name: str) -> ApiSpecProvider:
    normalized = name.strip().lower()
    if normalized in {"openai", "codex"}:
        return OpenAiSpecProvider()
    if normalized in {"anthropic", "claude"}:
        return AnthropicSpecProvider()
    raise LlmSpecError(f"지원하지 않는 API provider입니다: {name}")


def build_spec_prompt(idea: RefinedIdea) -> str:
    return f"""
다음 정제된 아이디어를 바탕으로 개인용 MVP 명세서를 한국어 JSON으로 작성하세요.

입력:
{json.dumps(asdict(idea), ensure_ascii=False, indent=2)}

반드시 아래 JSON 구조만 출력하세요. 마크다운 코드블록은 쓰지 마세요.
{{
  "title": "10자 이내 제목",
  "summary": "50자 이내 한 줄 요약",
  "user_stories": [
    "~할 때, ~하고 싶다, 왜냐하면 ~",
    "~할 때, ~하고 싶다, 왜냐하면 ~",
    "~할 때, ~하고 싶다, 왜냐하면 ~"
  ],
  "screens": [
    {{
      "name": "화면 이름",
      "purpose": "한 줄 목적",
      "wireframe": "+------------------+\\n| 텍스트 와이어프레임 |\\n+------------------+",
      "actions": ["액션1", "액션2"]
    }}
  ],
  "data_model": ["엔티티 1", "엔티티 2"],
  "tech_hints": ["구현 힌트 1", "구현 힌트 2"]
}}

규칙:
- screens는 3~5개로 작성합니다.
- data_model은 3개 이하로 작성합니다.
- 사용자가 말하지 않은 내용은 "(가정: ...)"로 표시합니다.
- 너무 거대한 서비스가 아니라 개인이 바로 검증할 수 있는 MVP로 줄입니다.
""".strip()


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LlmSpecError(f"API 요청 실패 HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise LlmSpecError(f"API 연결 실패: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise LlmSpecError(f"API 응답 JSON 파싱 실패: {body[:500]}") from exc


def _extract_openai_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]

    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if chunks:
        return "\n".join(chunks)
    raise LlmSpecError(f"OpenAI 응답에서 텍스트를 찾지 못했습니다: {response}")


def _extract_anthropic_text(response: dict[str, Any]) -> str:
    chunks = [
        item.get("text", "")
        for item in response.get("content", [])
        if item.get("type") == "text" and isinstance(item.get("text"), str)
    ]
    if chunks:
        return "\n".join(chunks)
    raise LlmSpecError(f"Anthropic 응답에서 텍스트를 찾지 못했습니다: {response}")


def _loads_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LlmSpecError(f"JSON 객체를 찾지 못했습니다: {text[:500]}")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LlmSpecError(f"명세 JSON 파싱 실패: {cleaned[:500]}") from exc
    if not isinstance(data, dict):
        raise LlmSpecError("명세 JSON 최상위 값이 객체가 아닙니다.")
    return data


def _spec_from_dict(data: dict[str, Any]) -> SpecDocument:
    screens = []
    for screen in data.get("screens", []):
        if not isinstance(screen, dict):
            continue
        screens.append(
            ScreenWireframeText(
                name=str(screen.get("name", "화면")),
                purpose=str(screen.get("purpose", "")),
                wireframe=str(screen.get("wireframe", "")),
                actions=[str(action) for action in screen.get("actions", [])],
            )
        )

    return SpecDocument(
        title=str(data.get("title", "아이디어")),
        summary=str(data.get("summary", "")),
        user_stories=[str(item) for item in data.get("user_stories", [])],
        screens=screens,
        data_model=[str(item) for item in data.get("data_model", [])],
        tech_hints=[str(item) for item in data.get("tech_hints", [])],
    )
