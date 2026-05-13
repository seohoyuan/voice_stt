from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from voice2spec.agents import run_pipeline
from voice2spec.storage import (
    find_deleted_idea,
    find_idea,
    list_deleted_ideas,
    list_ideas,
    restore_idea,
    save_idea,
    soft_delete_idea,
    update_idea,
)


class StorageManagementTests(unittest.TestCase):
    def test_update_soft_delete_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ideas_dir = root / "ideas"
            trash_dir = root / "trash"

            transcript, idea, spec, validation = run_pipeline("회의 내용을 정리해서 할 일을 뽑아주는 도구")
            markdown_path, json_path = save_idea(ideas_dir, transcript, idea, spec, validation)

            self.assertEqual(len(list_ideas(ideas_dir)), 1)
            self.assertTrue(markdown_path.exists())
            self.assertTrue(json_path.exists())

            updated = run_pipeline("읽은 책을 요약하고 다음 질문을 만드는 독서 기록 앱")
            update_idea(markdown_path, json_path, *updated)

            edited = find_idea(ideas_dir, "1")
            self.assertIsNotNone(edited)
            assert edited is not None
            self.assertEqual(edited["title"], "읽은책을")
            self.assertTrue(edited["updated_at"])

            moved = soft_delete_idea(ideas_dir, trash_dir, "1")
            self.assertIsNotNone(moved)
            self.assertEqual(len(list_ideas(ideas_dir)), 0)
            self.assertEqual(len(list_deleted_ideas(trash_dir)), 1)

            deleted = find_deleted_idea(trash_dir, "1")
            self.assertIsNotNone(deleted)

            restored = restore_idea(trash_dir, ideas_dir, "1")
            self.assertIsNotNone(restored)
            self.assertEqual(len(list_ideas(ideas_dir)), 1)
            self.assertEqual(len(list_deleted_ideas(trash_dir)), 0)


if __name__ == "__main__":
    unittest.main()
