#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p build/test
cc -std=c11 -Wall -Wextra -Werror -O2 -DIOSCAFFEINATE_TEST_MOCK \
  src/daemon.c src/schedule.c src/power.c -o build/test/ios-caffeinated
cc -std=c11 -Wall -Wextra -Werror -O2 -DIOSCAFFEINATE_TEST_MOCK \
  src/cli.c src/schedule.c src/wake_capability.c src/server_mode.c src/service.c -o build/test/ios-caffeinate

ln -sfn ios-caffeinate build/test/ic
