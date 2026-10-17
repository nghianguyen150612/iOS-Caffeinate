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
FLAGS=(-std=c11 -O2 -Wall -Wextra -Werror -target arm64-apple-ios12.0 -isysroot "$SDK" -Wl,-no_adhoc_codesign)
"$CLANG" "${FLAGS[@]}" src/daemon.c src/schedule.c src/power.c -framework CoreFoundation -o dist/ios-caffeinated
"$CLANG" "${FLAGS[@]}" src/cli.c src/schedule.c src/wake_capability.c src/server_mode.c -o dist/ios-caffeinate
xcrun --sdk iphoneos --show-sdk-version
"$CLANG" --version
file dist/ios-caffeinate dist/ios-caffeinated
printf '%s\n' "Binaries are UNSIGNED; iOS 12 power behavior remains unverified."

ln -sfn ios-caffeinate dist/ic
