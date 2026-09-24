#!/usr/bin/env bash
set -euo pipefail

DEST_DIR="${1:-src-tauri/resources/bin}"
TARGET_ARCH="${PYMSS_MACOS_TOOLS_ARCH:-$(uname -m)}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script only supports macOS." >&2
  exit 1
fi

case "$TARGET_ARCH" in
  arm64)
    EXPECTED_MACHO_ARCH="arm64"
    FFMPEG_URL="${PYMSS_FFMPEG_URL:-https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip}"
    FFMPEG_SHA256="${PYMSS_FFMPEG_SHA256:-c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924}"
    FFPROBE_URL="${PYMSS_FFPROBE_URL:-https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip}"
    FFPROBE_SHA256="${PYMSS_FFPROBE_SHA256:-fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6}"
    ARIA2_URL="${PYMSS_ARIA2_URL:-https://github.com/FerroDownload/aria2-static-builds/releases/download/v1.37.0/aria2c-1.37.0-macos-arm64}"
    ARIA2_SHA256="${PYMSS_ARIA2_SHA256:-47f4f54095e2bde1774c344dc376d1c84d92c4bcff90eed4117055091e197dd2}"
    ;;
  x86_64|amd64)
    EXPECTED_MACHO_ARCH="x86_64"
    FFMPEG_URL="${PYMSS_FFMPEG_URL:-https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/ffmpeg.zip}"
    FFMPEG_SHA256="${PYMSS_FFMPEG_SHA256:-7c6b4125b191cbf773832dc51f424cf2b6bb7da43007d1e066f95909e47cacd4}"
    FFPROBE_URL="${PYMSS_FFPROBE_URL:-https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/ffprobe.zip}"
    FFPROBE_SHA256="${PYMSS_FFPROBE_SHA256:-2322438ed2f6319a691291b247d09c69dcaa3a982460d1f269a7e1af335cfdfd}"
    ARIA2_URL="${PYMSS_ARIA2_URL:-https://github.com/FerroDownload/aria2-static-builds/releases/download/v1.37.0/aria2c-1.37.0-macos-x64}"
    ARIA2_SHA256="${PYMSS_ARIA2_SHA256:-c96de7025d9c4fba2e2607a979d61d154a2ec66b110f6dedfbf9d78a3f6ab0ee}"
    ;;
  *)
    echo "Unsupported macOS architecture: $TARGET_ARCH" >&2
    exit 1
    ;;
esac

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
mkdir -p "$DEST_DIR"

download_checked() {
  local url="$1"
  local expected_sha256="$2"
  local destination="$3"
  local actual_sha256

  curl --fail --location --silent --show-error \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --output "$destination" "$url"
  actual_sha256="$(shasum -a 256 "$destination" | awk '{print $1}')"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    echo "Checksum mismatch for $url" >&2
    echo "Expected: $expected_sha256" >&2
    echo "Actual:   $actual_sha256" >&2
    exit 1
  fi
}

install_zip_binary() {
  local name="$1"
  local url="$2"
  local sha256="$3"
  local archive="$WORK_DIR/$name.zip"
  local extract_dir="$WORK_DIR/$name"
  local source

  download_checked "$url" "$sha256" "$archive"
  mkdir -p "$extract_dir"
  ditto -x -k "$archive" "$extract_dir"
  source="$(find "$extract_dir" -type f -name "$name" -print -quit)"
  if [[ -z "$source" ]]; then
    echo "$name was not found in $url" >&2
    exit 1
  fi
  install -m 755 "$source" "$DEST_DIR/$name"
}

install_direct_binary() {
  local name="$1"
  local url="$2"
  local sha256="$3"
  local source="$WORK_DIR/$name"

  download_checked "$url" "$sha256" "$source"
  install -m 755 "$source" "$DEST_DIR/$name"
}

assert_portable_macho() {
  local binary="$1"
  local architectures dependencies invalid_dependencies

  if ! file -b "$binary" | grep -q 'Mach-O'; then
    echo "Bundled tool is not a Mach-O executable: $binary" >&2
    file "$binary" >&2
    exit 1
  fi
  architectures="$(lipo -archs "$binary")"
  if ! tr ' ' '\n' <<<"$architectures" | grep -qx "$EXPECTED_MACHO_ARCH"; then
    echo "Bundled tool has the wrong architecture: $binary ($architectures)" >&2
    exit 1
  fi

  dependencies="$(otool -L "$binary" | tail -n +2 | awk '{print $1}')"
  invalid_dependencies="$(printf '%s\n' "$dependencies" | grep -Ev '^(/usr/lib/|/System/Library/|$)' || true)"
  if [[ -n "$invalid_dependencies" ]]; then
    echo "Bundled tool still has non-system dynamic dependencies: $binary" >&2
    printf '%s\n' "$invalid_dependencies" >&2
    exit 1
  fi
}

install_zip_binary ffmpeg "$FFMPEG_URL" "$FFMPEG_SHA256"
install_zip_binary ffprobe "$FFPROBE_URL" "$FFPROBE_SHA256"
install_direct_binary aria2c "$ARIA2_URL" "$ARIA2_SHA256"

for tool in ffmpeg ffprobe aria2c; do
  assert_portable_macho "$DEST_DIR/$tool"
  xattr -d com.apple.quarantine "$DEST_DIR/$tool" 2>/dev/null || true
  codesign --force --sign - --timestamp=none "$DEST_DIR/$tool"
done

"$DEST_DIR/ffmpeg" -version >/dev/null
"$DEST_DIR/ffprobe" -version >/dev/null
"$DEST_DIR/aria2c" --version >/dev/null

cat > "$DEST_DIR/THIRD_PARTY_TOOLS.txt" <<EOF
This directory contains self-contained command-line tools bundled for Pymss Studio macOS releases.

Bundled tools:
- FFmpeg / ffprobe
  Version: $("$DEST_DIR/ffmpeg" -version | head -n 1)
  Architecture: $EXPECTED_MACHO_ARCH
  Source: $FFMPEG_URL
  FFmpeg SHA-256: $FFMPEG_SHA256
  FFprobe SHA-256: $FFPROBE_SHA256
  Project: https://ffmpeg.org/
  License information: https://ffmpeg.org/legal.html

- aria2 / aria2c
  Version: $("$DEST_DIR/aria2c" --version | head -n 1)
  Architecture: $EXPECTED_MACHO_ARCH
  Source: $ARIA2_URL
  SHA-256: $ARIA2_SHA256
  Project: https://aria2.github.io/
  License information: https://github.com/aria2/aria2/blob/master/COPYING

The release build verifies each download by SHA-256 and rejects binaries that
link to non-system dynamic libraries. No Homebrew runtime files are bundled.
EOF
