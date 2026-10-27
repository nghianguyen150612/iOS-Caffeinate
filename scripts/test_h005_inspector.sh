#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CC_BIN="${CC:-cc}"
OUTPUT_DIR="${H005_TEST_OUTPUT_DIR:-build/h005}"
mkdir -p "$OUTPUT_DIR"
"$CC_BIN" -std=c11 -Wall -Wextra -Werror -O2 -Isrc \
  src/h005_power_inspector_core.c tests/h005_power_inspector_test.c \
  -o "$OUTPUT_DIR/h005-power-inspector-mock-tests"
"$OUTPUT_DIR/h005-power-inspector-mock-tests"
