# P016 — Validation

Cloud validation is deterministic and offline. The C11 tests exercise zero and full percentages, invalid ranges, charging transitions, unknown/unrecognized thermal categories, partial failures, source disagreement, bounded freshness, future timestamps, monotonic rollback, boot changes, policy adaptation, and safe unavailable defaults. Python CLI tests check output, exit codes, redaction, read-only behavior, P015/P014 blocking, and absence of automatic polling or network/service operations.

The `p016-health-telemetry-validation` CI job records the exact source SHA, runs the P016 and compatibility tests, and uploads a deterministic validation report. It depends on the iOS ARM64 cross-build and P015 policy validation jobs. Linux fixtures remain `MOCK` or simulated.

Expected local checks:

```sh
./scripts/build-linux-test.sh
cc -std=c11 -Wall -Wextra -Werror -O2 -DIOSCAFFEINATE_TEST_MOCK -Isrc \
  tests/p016_health_unit.c src/health.c src/health_ios.c src/health_mock.c \
  src/health_policy.c src/server_policy.c src/server_mode.c src/recovery.c \
  -o /tmp/p016-health-unit
/tmp/p016-health-unit
python3 -m unittest discover -s tests -p 'test_p016_health.py' -v
```

Physical sensor behavior, power overhead, battery impact, thermal transitions, and daemon uptime accuracy have not been measured on the iPad. No CPU, battery, or memory overhead claim is made. Device acceptance remains pending.

Latest local offline run: 78 native C11 checks, 10 P016 CLI/adapter tests, 3 P015 policy CLI tests, 55 P009 tests, 52 P012 tests, and 52 daemon integration tests passed. These results use Linux mock/simulated paths. The iOS ARM64 cross-build is recorded by exact-head CI; no local Linux result is described as device validation.
