from __future__ import annotations

from pathlib import Path


REQUIRED_FILES = [
    "main.py",
    "buildozer.spec",
    ".github/workflows/build-apk.yml",
    "assets/fonts/.gitkeep",
    "voice2spec/android_recorder.py",
    "voice2spec/stt.py",
    "voice2spec/agents.py",
    "voice2spec/storage.py",
    "bin/.gitkeep",
    "models/.gitkeep",
]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    missing = [path for path in REQUIRED_FILES if not (root / path).exists()]

    if missing:
        print("Missing required files:")
        for path in missing:
            print(f"- {path}")
        raise SystemExit(1)

    spec = (root / "buildozer.spec").read_text(encoding="utf-8")
    required_snippets = [
        "requirements = python3,kivy,pyjnius",
        "android.permissions = RECORD_AUDIO",
        "android.archs = arm64-v8a",
        "android.accept_sdk_license = True",
    ]
    missing_snippets = [snippet for snippet in required_snippets if snippet not in spec]

    if missing_snippets:
        print("Missing required buildozer.spec settings:")
        for snippet in missing_snippets:
            print(f"- {snippet}")
        raise SystemExit(1)

    print("Mobile project sanity check OK")


if __name__ == "__main__":
    main()
