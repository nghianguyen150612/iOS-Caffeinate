# P013 — Validation

## Local cloud checks

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
cc -std=c11 -Wall -Wextra -Werror -O2 -DIOSCAFFEINATE_SERVICE_TESTING \
  tests/p013_service_unit.c src/service.c -o build/p013-service-unit
build/p013-service-unit
python3 -m unittest discover -s tests -p 'test_p013_service.py' -v
python3 -m unittest discover -s tests/packaging -p 'test_rootful_package.py' -v
```

The native harness injects `help`/`list` results and rejects every other launchctl command. It covers generated plist invariants, atomic no-replace installation, exact-content validation, symlink/hardlink/owner/mode/collision failures, read-only output, capability detection, permission errors, and fail-closed mutations. A daemon socketpair test verifies that both status protocols leave a due assertion untouched by the request handler; the event loop still owns timer expiry. The integration suite exercises graceful `SHUTDOWN`, successful assertion release before exit, and failed release without a false success.

The dedicated GitHub job is `p013-launchd-lifecycle-validation`. It builds C11 code, runs the injected lifecycle and CLI tests, validates staged and generated plist invariants, syntax-checks package scripts, runs package regressions, records the exact source SHA, and uploads deterministic evidence. The job never invokes launchctl, installs a package, or acquires a power assertion.

Existing `linux-protocol`, iOS cross-build, Mach-O inspection, rootful package, P009 evidence, P010 signing, P011 preflight, and P012 research jobs remain in the workflow. P008 attestation remains guarded by its existing branch condition.

## Service output and exit codes

`ic service status` includes fields such as:

```text
state=STAGED_ONLY
package.installation=INSTALLED
package.database_identity=INSTALLED
package.staged_template=PRESENT_VALID
managed_plist=ABSENT
configured_enablement=NOT_CONFIGURED
launchd.registration=NOT_REGISTERED
runtime.process=NOT_OBSERVED
ipc.availability=UNAVAILABLE
assertion.state=UNKNOWN
last_shutdown_result=UNAVAILABLE
boot_persistence=UNVERIFIED
device_awake=UNVERIFIED
changed=no
```

These are independent facts; the example assumes a successful package database query and a complete launchd listing. If either observation fails, its field remains `UNVERIFIED` and the top-level state is conservative. `doctor` adds blockers and readiness. `plan` describes the conservative intended profile and never applies it.

| Exit | Meaning |
|---:|---|
| 0 | Read-only report succeeded or lifecycle operation was confirmed |
| 1 | System/IO error |
| 2 | Invalid command or arguments |
| 3 | Unsupported or unverified operation |
| 4 | Root privilege required |
| 5 | Invalid lifecycle state or required evidence absent |
| 6 | Unsafe or inconsistent state; cleanup unresolved |

Every mutating result includes `changed=yes`, `changed=no`, or `changed=unknown` based on available confirmation. Linux mocks prove code paths only. They do not prove iOS launchd compatibility, boot persistence, daemon crash recovery, device awake behavior, SSH reliability, or 24/7 operation.
