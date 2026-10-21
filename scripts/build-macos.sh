#!/usr/bin/env bash
# Cross-build with official iPhoneOS SDK. Never signs or deploys.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "$(uname -s)" != Darwin ]]; then
    echo "ERROR: iPhoneOS SDK required. Run with Xcode on macOS." >&2
    exit 1
fi
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
SDK_VERSION="$(xcrun --sdk iphoneos --show-sdk-version)"
CLANG="$(xcrun --sdk iphoneos --find clang)"
XCODE_VERSION="$(xcodebuild -version)"
CLANG_VERSION="$("$CLANG" --version | head -n 1)"
mkdir -p dist
FLAGS=(-std=c11 -O2 -Wall -Wextra -Werror -target arm64-apple-ios12.0 -isysroot "$SDK" -Wl,-no_adhoc_codesign)
"$CLANG" "${FLAGS[@]}" src/daemon.c src/schedule.c src/recovery.c src/power.c -framework CoreFoundation -o dist/ios-caffeinated
"$CLANG" "${FLAGS[@]}" src/cli.c src/schedule.c src/recovery.c src/wake_capability.c src/server_mode.c src/server_policy.c src/service.c \
  src/health.c src/health_ios.c src/health_policy.c -framework CoreFoundation -o dist/ios-caffeinate
python3 - "$SDK" "$SDK_VERSION" "$XCODE_VERSION" "$CLANG_VERSION" <<'PY'
import json
import sys

sdk_path, sdk_version, xcode_version, clang_version = sys.argv[1:]
with open("dist/build-info.json", "w", encoding="utf-8") as output:
    json.dump({
        "target_platform": "iPad mini 2 A1489 / Apple A7 ARM64 / iOS 12.5.7 / Amethyst + Procursus rootful",
        "target_triple": "arm64-apple-ios12.0",
        "minimum_ios_version": "12.0",
        "sdk": {"name": "iPhoneOS", "version": sdk_version, "path": sdk_path},
        "xcode": xcode_version,
        "clang": clang_version,
        "signing_status": "UNSIGNED",
    }, output, indent=2)
    output.write("\n")
PY
file dist/ios-caffeinate dist/ios-caffeinated
printf '%s\n' "Binaries are UNSIGNED; iOS 12 power behavior remains unverified."

ln -sfn ios-caffeinate dist/ic
(cd dist && shasum -a 256 ios-caffeinate ios-caffeinated > SHA256SUMS)
