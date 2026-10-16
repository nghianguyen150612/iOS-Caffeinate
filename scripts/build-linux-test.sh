#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p build/test
cc -std=c11 -Wall -Wextra -Werror -O2 -DIOSCAFFEINATE_TEST_MOCK \
  src/daemon.c src/power.c -o build/test/ioscaffeinated
cc -std=c11 -Wall -Wextra -Werror -O2 src/cli.c -o build/test/ioscaffeinate
