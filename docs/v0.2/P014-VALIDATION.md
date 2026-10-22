# P014 — Cloud Validation

## Local deterministic commands

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
cc -std=c11 -Wall -Wextra -Werror -O2 \
  -DIOSCAFFEINATE_RECOVERY_TESTING -DIOSCAFFEINATE_SERVICE_TESTING \
  tests/p014_recovery_unit.c src/service.c src/recovery.c \
  -o build/p014-recovery-unit
build/p014-recovery-unit
```

The P014 native harness covers recovery classifications and decisions, injected supervisor observation and callback failure, the 5/15/60 second backoff sequence, three-attempt suppression, rolling-window expiry, duplicate event IDs, durable attempt consumption, monotonic identity and rollback ambiguity, healthy reset, cleanup and supervisor gates, SIGKILL uncertainty, release failure, strict journal parsing, permissions/owner/link checks, and interrupted atomic replacement. The integration suite covers read-only recovery diagnostics, missing/corrupt/unreviewed journal blocking across manual and scheduled assertions, SIGKILL simulation, schedule behavior after a trusted clean journal, and unchanged P013 mutation gates.

P009–P013 and rootful packaging regressions are part of the P014 job. The exact source SHA, deterministic test output, mock/simulation scope, and explicit absence of launchd or real assertion side effects are uploaded as the `iOS-Caffeinate-P014-crash-recovery-validation` artifact. The job also reruns Linux protocol integration, P013 native and daemon read-only checks, and `p013_validate` against the generated managed profile.

## Evidence scope

All P014 CI recovery events are synthetic or mock observations. No target iPad, launchd mutation, real power assertion, package install, SSH connection, or network service is used. P009 v1 already names `DAEMON_LAUNCH`, `DAEMON_EXIT`, `SIGTERM`, and `ASSERTION_RELEASE`; recovery category and cleanup confidence can be recorded in event details without changing v1 semantics. Record `SIGTERM` only when its handler or an observer actually saw it; never infer SIGKILL, exit code, or successful cleanup from an absent process/socket. Preserve each event's timestamp, `timebase_id`, and `uncertainty_ms`.

Use source `SIMULATED` or `MOCK` for cloud runs, `OPERATOR_RECORDED` for operator statements, `DEVICE_REPORTED` for genuine device-origin observations, and `EXTERNAL_OBSERVER` for independent observer records. The P009 v1 replay does not interpret P014's internal exit classes or prove cleanup from a generic daemon exit record. A future evidence-focused milestone can add a versioned recovery event contract if those distinctions need semantic validation. P014 does not change P009 v1 behavior or promote synthetic data to device evidence.

## Known limitations

No iOS 12 supervisor adapter is enabled. No cloud result demonstrates what the kernel does with an assertion after SIGKILL, whether launchd accepts a future restart policy, whether a reboot preserves the journal, whether the OS remains awake, whether SSH remains reachable, or whether 24/7 operation is reliable. These remain `UNVERIFIED` or `PENDING` for supervised acceptance.
