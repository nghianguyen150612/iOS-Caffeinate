#!/usr/bin/env bash
# Cross-build with official iPhoneOS SDK. Never signs or deploys.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "$(uname -s)" != Darwin ]]; then
    echo "ERROR: iPhoneOS SDK required. Run with Xcode on macOS." >&2
    exit 1
fi
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
CLANG="$(xcrun --sdk iphoneos --find clang)"
mkdir -p dist
FLAGS=(-std=c11 -O2 -Wall -Wextra -Werror -target arm64-apple-ios12.0 -isysroot "$SDK")
"$CLANG" "${FLAGS[@]}" src/daemon.c src/power.c -framework CoreFoundation -o dist/ioscaffeinated
"$CLANG" "${FLAGS[@]}" src/cli.c -o dist/ioscaffeinate
file dist/ioscaffeinate dist/ioscaffeinated
printf '%s\n' "Binaries are UNSIGNED; iOS 12 power behavior remains unverified."
