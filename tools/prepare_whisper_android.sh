#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_REPO_URL="${WHISPER_REPO_URL:-https://github.com/ggml-org/whisper.cpp.git}"
WHISPER_REF="${WHISPER_REF:-v1.8.4}"
WHISPER_DIR="$ROOT_DIR/external/whisper.cpp"
BUILD_DIR="$WHISPER_DIR/build-android"
NDK_VERSION="${ANDROID_NDK_VERSION:-26.3.11579264}"
MODEL_NAME="${VOICE2SPEC_WHISPER_MODEL_NAME:-ggml-small-q5_1.bin}"
MODEL_URL="${VOICE2SPEC_WHISPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin}"

mkdir -p "$ROOT_DIR/bin" "$ROOT_DIR/models" "$ROOT_DIR/external"

if [[ ! -s "$ROOT_DIR/models/$MODEL_NAME" ]]; then
  echo "Downloading Whisper model: $MODEL_NAME"
  curl -L --retry 3 --fail \
    -o "$ROOT_DIR/models/$MODEL_NAME" \
    "$MODEL_URL"
else
  echo "Whisper model already exists: models/$MODEL_NAME"
fi
test -s "$ROOT_DIR/models/$MODEL_NAME"

if [[ ! -x "$ROOT_DIR/bin/whisper-cli" ]]; then
  if [[ ! -d "$WHISPER_DIR/.git" ]]; then
    git clone --depth 1 --branch "$WHISPER_REF" "$WHISPER_REPO_URL" "$WHISPER_DIR"
  fi

  if [[ -z "${ANDROID_HOME:-}" ]]; then
    echo "ANDROID_HOME is not set" >&2
    exit 1
  fi

  SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
  if [[ ! -x "$SDKMANAGER" ]]; then
    SDKMANAGER="$ANDROID_HOME/tools/bin/sdkmanager"
  fi
  if [[ ! -x "$SDKMANAGER" ]]; then
    echo "sdkmanager not found under ANDROID_HOME=$ANDROID_HOME" >&2
    exit 1
  fi

  yes | "$SDKMANAGER" --licenses >/dev/null || true
  "$SDKMANAGER" "ndk;$NDK_VERSION" "cmake;3.22.1"

  export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/$NDK_VERSION"
  TOOLCHAIN_FILE="$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake"
  if [[ ! -f "$TOOLCHAIN_FILE" ]]; then
    echo "Android NDK toolchain not found: $TOOLCHAIN_FILE" >&2
    exit 1
  fi

  cmake -S "$WHISPER_DIR" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DANDROID_ABI=arm64-v8a \
    -DANDROID_PLATFORM=android-29 \
    -DBUILD_SHARED_LIBS=OFF \
    -DWHISPER_BUILD_TESTS=OFF

  cmake --build "$BUILD_DIR" --target whisper-cli -j 2 || cmake --build "$BUILD_DIR" -j 2

  WHISPER_BIN="$(find "$BUILD_DIR" -type f -name whisper-cli | head -n 1)"
  if [[ -z "$WHISPER_BIN" ]]; then
    echo "whisper-cli was not produced by the Android build" >&2
    exit 1
  fi
  cp "$WHISPER_BIN" "$ROOT_DIR/bin/whisper-cli"
  chmod 755 "$ROOT_DIR/bin/whisper-cli"
else
  echo "Android whisper-cli already exists: bin/whisper-cli"
fi

ls -lh "$ROOT_DIR/bin/whisper-cli" "$ROOT_DIR/models/$MODEL_NAME"
