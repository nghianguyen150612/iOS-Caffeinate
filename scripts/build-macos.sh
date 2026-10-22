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
SOURCE_SHA="$(git rev-parse HEAD)"
PACKAGE_VERSION="${IOSCAFFEINATE_PACKAGE_VERSION:-$(cat packaging/rootful/VERSION)}"
OUTPUT_DIR="${IOSCAFFEINATE_OUTPUT_DIR:-dist}"
if [[ ! "$PACKAGE_VERSION" =~ ^[0-9][A-Za-z0-9.+:~_-]*$ ]]; then
    echo "ERROR: invalid Debian package version: $PACKAGE_VERSION" >&2
    exit 2
fi
WORKTREE_CLEAN='false'
BUILD_KIND='DEVELOPMENT_DIRTY'
if [[ -z "$(git status --porcelain)" ]]; then
    WORKTREE_CLEAN='true'
    BUILD_KIND='DEVELOPMENT'
fi
RELEASE_CHANNEL='DEVELOPMENT'
if [[ "$PACKAGE_VERSION" == *'~rc'* ]]; then
    RELEASE_CHANNEL='PRE_RELEASE'
fi
if TAG="$(git describe --exact-match --tags HEAD 2>/dev/null)"; then
    if [[ "$TAG" == *'rc'* || "$TAG" == *'~'* ]]; then
        RELEASE_CHANNEL='PRE_RELEASE'
    else
        RELEASE_CHANNEL='STABLE'
    fi
fi
if [[ -L "$OUTPUT_DIR" ]]; then
    echo "ERROR: output directory must not be a symlink: $OUTPUT_DIR" >&2
    exit 2
fi
mkdir -p "$OUTPUT_DIR"
FLAGS=(-std=c11 -O2 -Wall -Wextra -Werror -target arm64-apple-ios12.0 -isysroot "$SDK" -Wl,-no_adhoc_codesign
  "-DIOSCAFFEINATE_BUILD_SHA=\"$SOURCE_SHA\""
  "-DIOSCAFFEINATE_PACKAGE_VERSION=\"$PACKAGE_VERSION\""
  "-DIOSCAFFEINATE_BUILD_KIND=\"$BUILD_KIND\""
  "-DIOSCAFFEINATE_RELEASE_CHANNEL=\"$RELEASE_CHANNEL\"")
"$CLANG" "${FLAGS[@]}" src/daemon.c src/schedule.c src/recovery.c src/power.c -framework CoreFoundation -o "$OUTPUT_DIR/ios-caffeinated"
"$CLANG" "${FLAGS[@]}" src/cli.c src/schedule.c src/recovery.c src/wake_capability.c src/server_mode.c src/server_policy.c src/service.c \
  src/health.c src/health_ios.c src/health_policy.c -framework CoreFoundation -o "$OUTPUT_DIR/ios-caffeinate"
python3 - "$OUTPUT_DIR" "$SDK_VERSION" "$XCODE_VERSION" "$CLANG_VERSION" "$SOURCE_SHA" "$PACKAGE_VERSION" "$WORKTREE_CLEAN" "$BUILD_KIND" "$RELEASE_CHANNEL" <<'PY'
import json
import sys

output_dir, sdk_version, xcode_version, clang_version, source_sha, package_version, worktree_clean, build_kind, release_channel = sys.argv[1:]
with open(f"{output_dir}/build-info.json", "w", encoding="utf-8") as output:
    json.dump({
        "target_platform": "iPad mini 2 A1489 / Apple A7 ARM64 / iOS 12.5.7 / Amethyst + Procursus rootful",
        "target_triple": "arm64-apple-ios12.0",
        "minimum_ios_version": "12.0",
        "sdk": {"name": "iPhoneOS", "version": sdk_version},
        "xcode": xcode_version,
        "clang": clang_version,
        "signing_status": "UNSIGNED",
        "source_commit_sha": source_sha,
        "source_tree_clean": worktree_clean == "true",
        "package_version": package_version,
        "build_kind": build_kind,
        "release_channel": release_channel,
    }, output, indent=2)
    output.write("\n")
PY
file "$OUTPUT_DIR/ios-caffeinate" "$OUTPUT_DIR/ios-caffeinated"
printf '%s\n' "Binaries are UNSIGNED; iOS 12 power behavior remains unverified."

ln -sfn ios-caffeinate "$OUTPUT_DIR/ic"
(cd "$OUTPUT_DIR" && shasum -a 256 ios-caffeinate ios-caffeinated > SHA256SUMS)
