from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from voice2spec.desktop_pipeline import generate_spec_from_text
from voice2spec.llm_specifier import AnthropicSpecProvider, ApiSpecProvider, ApiSpecifier
from voice2spec.models import RefinedIdea


class FakeProvider(ApiSpecProvider):
    def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return json.dumps(
            {
                "title": "회의정리",
                "summary": "회의 내용을 결정사항과 할 일로 정리합니다.",
                "user_stories": [
                    "회의가 끝났을 때, 결정사항을 보고 싶다, 왜냐하면 놓치면 안 되기 때문이다.",
                    "할 일을 나눌 때, 담당자를 보고 싶다, 왜냐하면 실행이 필요하기 때문이다.",
                    "다시 볼 때, 원문을 확인하고 싶다, 왜냐하면 맥락이 필요하기 때문이다.",
                ],
                "screens": [
                    {
                        "name": "입력",
                        "purpose": "회의 내용을 입력합니다.",
                        "wireframe": "+---+\n|입력|\n+---+",
                        "actions": ["녹음", "저장"],
                    },
                    {
                        "name": "결과",
                        "purpose": "정리 결과를 보여줍니다.",
                        "wireframe": "+---+\n|결과|\n+---+",
                        "actions": ["수정", "내보내기"],
                    },
                    {
                        "name": "목록",
                        "purpose": "이전 회의를 보여줍니다.",
                        "wireframe": "+---+\n|목록|\n+---+",
                        "actions": ["검색", "열기"],
                    },
                ],
                "data_model": ["Meeting", "Decision", "ActionItem"],
                "tech_hints": ["Python에서 먼저 검증합니다."],
            },
            ensure_ascii=False,
        )


class LlmSpecifierTests(unittest.TestCase):
    def test_anthropic_default_model_is_opus_46(self) -> None:
        provider = AnthropicSpecProvider(api_key="fake-key")

        self.assertEqual(provider.model, "claude-opus-4-6")

    def test_api_specifier_parses_provider_json(self) -> None:
        specifier = ApiSpecifier(FakeProvider())
        spec = specifier.specify(
            RefinedIdea(
                core="회의 내용을 정리하는 앱",
                ambiguities=["대상 사용자가 모호함"],
                assumptions=["개인용 MVP"],
            )
        )

        self.assertEqual(spec.title, "회의정리")
        self.assertEqual(len(spec.screens), 3)
        self.assertIn("Meeting", spec.data_model)

    def test_generate_spec_from_text_saves_markdown_with_rule_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            *_items, markdown_path, json_path = generate_spec_from_text(
                "회의 내용을 말하면 결정사항과 할 일을 정리하는 앱",
                ideas_dir=Path(temp_dir),
                spec_provider="rule",
            )

            self.assertTrue(markdown_path.exists())
            self.assertTrue(json_path.exists())


if __name__ == "__main__":
    unittest.main()
