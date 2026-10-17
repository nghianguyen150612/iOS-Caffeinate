# P006 Validation Evidence

## Baseline and scope

- Verified P005 integration SHA: `77f3f15dda5c75f10e40b48fc0575d47fa38b80e`
- Feature branch: `feat/p006-server-mode-foundation`
- Hardware: iPad mini 2 A1489, Apple A7 ARM64, iOS 12.5.7; unavailable during P006.
- Linux tests use only `IOSCAFFEINATE_TEST_MOCK`; this backend has no power effect.

## Local validation

The P006 Linux mock build and integration suite were run with:

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
```

Result: **40 integration tests passed**. Coverage includes disabled default, read-only status/doctor/plan, fail-closed schema and filesystem checks, unavailable daemon versus incompatible daemon protocol, mock backend errors, invalid-state fault injection, no diagnostic assertion acquisition, unchanged schedule state, schedule CRUD, P005 wake status, bounded trial start/stop/expiry, finite release retries, SIGTERM cleanup, restart without trial resumption, IPC malformed-input handling, single-owner enforcement, separate LAN/Tailscale schema, and the disabled launchd template.

The iOS cross-build and Mach-O inspection require the official iPhoneOS SDK on macOS. Exact-commit results are recorded by the [`linux-protocol`, `ios-cross-build`, and `ios-artifact-inspection` checks on P006 PR #4](https://github.com/nghianguyen150612/iOS-Caffeinate/pull/4). The final report records the exact feature SHA and workflow-run URLs after those checks finish. Artifacts remain unsigned and hardware-unverified.

## CPU methodology

The daemon blocks in `poll()` when idle with no schedules or active hold. A 30.000-second Linux mock idle observation read user+system ticks from `/proc/<pid>/stat` at the host's `SC_CLK_TCK` resolution: **0.000 CPU seconds observed, 0.0000% over the interval**, with the process waiting in `do_sys_poll`. This measurement describes only that Linux host and mock backend; timer resolution means it is not a claim of exactly zero work. It must not be converted into iPad battery or thermal estimates. No battery percentage, temperature, SSH latency, or Tailscale result is claimed by CI.

## Deferred evidence

- iOS 12 IOKit create/release: **PENDING**
- Bounded physical trial and cleanup: **PENDING**
- Display-locked LAN SSH: **PENDING**
- Display-locked Tailscale: **PENDING**
- Battery and thermal observations: **PENDING**
- Physical recovery and rollback: **PENDING**
- 24/7 unattended operation: **NOT VALIDATED**

Cloud validation does not pass any physical-device gate. See [P006-DEVICE-TEST.md](P006-DEVICE-TEST.md) before any hardware session.
