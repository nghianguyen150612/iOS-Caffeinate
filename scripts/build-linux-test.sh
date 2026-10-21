#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd -P)"
SOURCE_SHA="$(git rev-parse HEAD)"
PACKAGE_VERSION="$(cat packaging/rootful/VERSION)"
RELEASE_CHANNEL='DEVELOPMENT'
BUILD_KIND='DEVELOPMENT'
if [[ -n "$(git status --porcelain)" ]]; then
  BUILD_KIND='DEVELOPMENT_DIRTY'
fi
if TAG="$(git describe --exact-match --tags HEAD 2>/dev/null)"; then
  if [[ "$TAG" == *'rc'* || "$TAG" == *'~'* ]]; then
    RELEASE_CHANNEL='PRE_RELEASE'
  else
    RELEASE_CHANNEL='STABLE'
  fi
fi
CLI_BUILD_IDENTITY=(
  "-DIOSCAFFEINATE_BUILD_SHA=\"$SOURCE_SHA\""
  "-DIOSCAFFEINATE_PACKAGE_VERSION=\"$PACKAGE_VERSION\""
  "-DIOSCAFFEINATE_BUILD_KIND=\"$BUILD_KIND\""
  "-DIOSCAFFEINATE_RELEASE_CHANNEL=\"$RELEASE_CHANNEL\""
  "-DIOSCAFFEINATE_MANAGER_PATH=\"$ROOT/packaging/rootful/manager\""
  "-DIOSCAFFEINATE_EVIDENCE_TOOL_PATH=\"$ROOT/scripts/p018_evidence.py\""
  "-DIOSCAFFEINATE_PYTHON_PATH=\"$(command -v python3)\""
)
mkdir -p build/test
cc -std=c11 -Wall -Wextra -Werror -O2 -DIOSCAFFEINATE_TEST_MOCK \
  src/daemon.c src/schedule.c src/recovery.c src/power.c -o build/test/ios-caffeinated
cc -std=c11 -Wall -Wextra -Werror -O2 -DIOSCAFFEINATE_TEST_MOCK \
  "${CLI_BUILD_IDENTITY[@]}" \
  src/cli.c src/schedule.c src/recovery.c src/wake_capability.c src/server_mode.c src/server_policy.c src/service.c \
  src/health.c src/health_ios.c src/health_policy.c -o build/test/ios-caffeinate

ln -sfn ios-caffeinate build/test/ic
