from __future__ import annotations

import unittest

from voice2spec.agents import detect_domain, run_pipeline


class PipelineTests(unittest.TestCase):
    def test_reading_domain_generates_reading_screens(self) -> None:
        _, _, spec, validation = run_pipeline("읽은 책을 음성으로 남기면 요약과 다음 질문을 만들어주는 독서 기록 앱")

        self.assertTrue(validation.passed)
        self.assertEqual(detect_domain("독서 기록 앱").key, "reading")
        self.assertIn("Book", spec.data_model)
        self.assertTrue(any(screen.name == "요약 결과" for screen in spec.screens))

    def test_delivery_domain_generates_order_model(self) -> None:
        _, _, spec, validation = run_pipeline("동네 반찬가게 메뉴를 모아서 빠르게 배달 주문하는 앱")

        self.assertTrue(validation.passed)
        self.assertEqual(detect_domain("배달 주문 앱").key, "delivery")
        self.assertIn("Order", spec.data_model)
        self.assertTrue(any(screen.name == "주문 확인" for screen in spec.screens))

    def test_meeting_domain_generates_action_items(self) -> None:
        _, _, spec, validation = run_pipeline("아이디어 회의 내용을 입력하면 할 일과 화면 초안을 뽑아주는 도구")

        self.assertTrue(validation.passed)
        self.assertEqual(detect_domain("회의 할 일 정리").key, "meeting")
        self.assertIn("ActionItem", spec.data_model)
        self.assertTrue(any(screen.name == "정리 결과" for screen in spec.screens))


if __name__ == "__main__":
    unittest.main()
