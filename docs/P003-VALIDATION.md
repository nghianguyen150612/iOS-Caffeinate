# P003 — Validation & Evidence Report

**Milestone:** P003 — Robust Daemon, Lifecycle, IPC Security & Recovery
**Base Commit:** `82ac9afab02d45b8dea2e585f41d63cbc0e61340` (P002 HEAD)
**Feature Branch:** `feat/p003-daemon-lifecycle`
**Platform:** iPad mini 2 A1489, Apple A7 ARM64, iOS 12.5.7
**Execution Status:** PARTIAL — Cloud & Local C11 Engineering Complete; Device Hardware Validation Deferred (PENDING)

---

## 1. Summary of Changes in P003

1. **Assertion State Machine (`src/daemon.c`)**:
   - Replaced booleans with explicit `daemon_state_t` enum (`IDLE`, `ACQUIRING`, `ACTIVE`, `RELEASING`, `RELEASE_FAILED`, `SHUTTING_DOWN`).
   - Tracked assertion ID ownership and release failure status explicitly.

2. **Deadline-Aware Poll Event Loop (`src/daemon.c`)**:
   - Replaced fixed 100ms polling loop with a calculated dynamic timeout derived from the nearest active deadline or release retry time.
   - Guaranteed monotonic time tracking via `clock_gettime(CLOCK_MONOTONIC)`.

3. **Unix IPC Security Hardening (`src/daemon.c`)**:
   - Added `check_peer_euid` using `getpeereid` on Darwin/iOS and `SO_PEERCRED` on Linux.
   - Enforced root client authorization on default socket path `/var/run/ioscaffeinated.sock`.
   - Maintained non-root private socket testing for unprivileged unit tests.

4. **Release Failure & Retry Policy (`src/daemon.c`)**:
   - Handled release failures by transitioning to `RELEASE_FAILED` state and scheduling periodic retries (`retry_at = now() + 1.0`).
   - Ensured daemon exit returns non-zero status if shut down with an unresolved assertion release.

5. **Structured Logging (`src/daemon.c`)**:
   - Added ISO-8601 formatted logging to stderr (`[YYYY-MM-DD HH:MM:SS] [LEVEL] msg`).

6. **Integration Test Expansion (`tests/integration.py`)**:
   - Extended test coverage to 21 automated integration tests covering all lifecycle transitions, fault injection, peer credentials, signals, client disconnects, and malformed frames.

---

## 2. Linux Mock Automated Verification

Ran 21 integration tests under unprivileged Linux mock environment:

```text
test_acquire_failure ... ok
test_canonical_names_and_alias ... ok
test_cleanup_preserves_replacement_socket ... ok
test_cli_fragmented_and_incomplete_replies ... ok
test_cli_reply_timeout ... ok
test_disconnect_does_not_kill_daemon ... ok
test_duration_validation_and_exit_codes ... ok
test_existing_live_socket_is_preserved ... ok
test_expiry_with_idle_client ... ok
test_fragmented_request ... ok
test_malformed_frames ... ok
test_missing_daemon_and_bad_paths ... ok
test_probe_and_hold_lifecycle ... ok
test_refuse_regular_file_and_symlink ... ok
test_release_failure_is_not_success ... ok
test_release_retry_recovery ... ok
test_signal_cleanup ... ok
test_simultaneous_startup ... ok
test_socket_permissions_and_single_instance ... ok
test_stale_socket_and_crash_recovery ... ok
test_unsafe_lock_is_preserved ... ok

----------------------------------------------------------------------
Ran 21 tests in 11.419s

OK
```

---

## 3. iOS 12 ARM64 Cross-Build & Inspection

Verified cross-compilation with official `iPhoneOS` SDK targeting `arm64-apple-ios12.0`:

- Mach-O 64-bit executable `arm64`
- Minimum OS version `12.0`
- Dynamic libraries: `libSystem.B.dylib`
- Unsigned state: No code signature (ldid pending device deployment)
- Launchd template validation: `plutil -lint packaging/com.ioscaffeinate.daemon.plist` OK (Disabled=true)

---

## 4. Hardware Gate Status

All physical device tests remain **PENDING** as authorized:

- iPad binary execution: PENDING
- Code signing with ldid: PENDING
- Real IOKit assertion creation/release: PENDING
- Bounded 5-minute display-lock hold test: PENDING
- Display-lock SSH / Tailscale connectivity: PENDING

Refer to `docs/P003-DEVICE-TEST.md` for deferred hardware testing procedure.
