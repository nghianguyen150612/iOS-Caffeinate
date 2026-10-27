#!/usr/bin/env bash
# Cross-build a standalone, unsigned H005 diagnostic. It is not a package input.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ "$(uname -s)" != Darwin ]]; then
  echo "ERROR: the official iPhoneOS SDK requires Xcode on macOS." >&2
  exit 1
fi

SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
SDK_VERSION="$(xcrun --sdk iphoneos --show-sdk-version)"
CLANG="$(xcrun --sdk iphoneos --find clang)"
CLANG_VERSION="$("$CLANG" --version | head -n 1)"
XCODE_VERSION="$(xcodebuild -version | tr '\n' ';')"
OUTPUT_DIR="${H005_OUTPUT_DIR:-build/h005}"
BINARY="$OUTPUT_DIR/ios-power-preflight-inspector"

mkdir -p "$OUTPUT_DIR"
"$CLANG" -std=c11 -O2 -Wall -Wextra -Werror \
  -target arm64-apple-ios12.0 -isysroot "$SDK" -I src \
  -Wl,-no_adhoc_codesign \
  src/h005_power_inspector_ios.c src/h005_power_inspector_core.c \
  -framework CoreFoundation -framework IOKit -o "$BINARY"

python3 scripts/h005_macho_audit.py \
  --binary "$BINARY" \
  --sdk-version "$SDK_VERSION" \
  --xcode-version "$XCODE_VERSION" \
  --clang-version "$CLANG_VERSION" \
  --output "$OUTPUT_DIR/ABI-INSPECTION.txt"
file "$BINARY"
echo "H005 iOS diagnostic cross-build PASS; unsigned; not packaged or transferred."
