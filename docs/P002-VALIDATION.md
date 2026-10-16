# P002 audit and evidence — 2026-10-16

P002 status: PARTIAL until hardware gates are measured. No iPad changes have been made.

## Baseline and available environment

- Starting `main`, local HEAD and fetched `origin/main`: `069ad94eb344da08d414c9478b6e212146c8fc28`, matching the supplied P001 baseline exactly. Clean clone; no unrelated local modifications.
- Feature branch: `feat/p002-ios-runtime-validation`; created from that verified baseline using local Git. No merge into main.
- Linux x86_64 cloud workspace, UID 1000. No macOS/Xcode locally. iOS build and inspection run on GitHub macOS runners with the official iPhoneOS SDK.
- No iPad hostname/address, credentials, device session or physical-recovery confirmation supplied. Environment policy lists no VPN and no device TCP grants. Device tests are PENDING, not attempted over a guessed connection.
- Read all repository sources/docs, build/test scripts, workflow and disabled plist. No separate Project Handoff v0.3 was supplied or found in `/workspace`; `docs/P001-HANDOFF.md` was read completely.
- Baseline Linux suite passed before edits. Existing baseline Actions run [38841619453](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/38841619453) reports `linux-protocol` SUCCESS and `ios-cross-build` SUCCESS for the exact baseline. This runner returned no baseline log text to `gh run view --log`; no stronger platform/SDK/deployment evidence is inferred from that old job status.

## Audit findings and implemented fixes

| Area | Verified issue/finding | P002 resolution |
|---|---|---|
| Naming/layout | Deprecated executable names across build, help, tests, docs and plist | `ios-caffeinate`, `ios-caffeinated`; relative build/test `ic` symlink; planned absolute rootful symlink documented; socket unchanged |
| C11 / iOS compatibility | No iOS-only static IOKit API assumption, but baseline inspection lacked device/minimum/dependency assertions | Keep dynamic IOKit; official SDK target `arm64-apple-ios12.0`; enforce Mach-O checks in a third CI job |
| Durations | Existing overflow/24h checks were sound; wall clock could extend a bounded test | Preserve limits, add negative and boundary tests; use monotonic deadlines |
| Request framing | Single recv rejected valid fragments; accepted unterminated/truncated, NUL-hidden or extra queued commands | Assemble bounded ASCII/newline frames, reject malformed frames and slow/incomplete requests |
| CLI framing/disconnect | Single read accepted partial OK reply; write could terminate on SIGPIPE | Assemble complete reply, four-second total read deadline, send timeout, ignore SIGPIPE; meaningful exit codes |
| CLI arguments | Help accepted trailing arguments | Reject extra arguments with exit 2 |
| Socket security | 0600/owner checks existed; concurrent prepare/bind/listen could replace a newly bound socket | Stable owner-only advisory sidecar lock; nonblocking stale check; preserve unexpected files and socket replacements |
| Release lifecycle | STOP always reported OK and discarded state after release failure | Return ERR/exit 1; retain assertion ID and pending state; rate-limited release retry; nonzero unresolved shutdown |
| Probe lifecycle | Failed release lost the probe assertion ID | Track probe as a hold until successful release; refuse probing while active |
| Signals/expiry | Baseline signal path existed; client reads could delay it, and error reporting hid final release failure | Bounded client polling with expiry checks; test SIGINT/SIGTERM; log release evidence and unresolved exit |
| Diagnostics | No successful raw API return codes, assertion ID or individual symbol state in probe reply | Report load/symbol/create/release results, type and ID without equating API success with network efficacy |

No architectural replacement, launchd activation, installer, entitlement expansion, Apple service change or P003 feature was introduced. Mock failure injection is compile-time gated along with the mock backend.

## Evidence levels

| Level | Status | Evidence / limitation |
|---|---|---|
| SOURCE VALIDATED | PASS | P001 files reviewed and P002 fixes inspected; final diff check required before each commit |
| MOCK TESTED | PASS locally | `./scripts/build-linux-test.sh` + `python3 tests/integration.py`; 20 integration tests, UID 1000, C11 `-Wall -Wextra -Werror`; latest full local run: 20/20 OK in 10.042 seconds; no power effect |
| CROSS-BUILD VALIDATED | PENDING current branch CI | Will record exact tested SHA, SDK, artifact hashes, platform and linked libraries after Actions |
| DEVICE RUNTIME VALIDATED | PENDING | No reachable authorized iPad session |
| ASSERTION API VALIDATED | PENDING | No real IOKit load/symbol/create/release measurements |
| NETWORK EFFECT VALIDATED | PENDING | No screen-locked LAN SSH or independent Tailscale measurements |

Mock coverage: invalid/zero/overflow/>24h durations, 24h acceptance followed by STOP, missing/unknown/extra CLI args, exact exit codes, malformed/fragmented IPC, incomplete and timed-out replies, concurrent startup, stale/crashed socket recovery, 0600 ownership, live endpoint preservation, unsafe file/symlink refusal, replacement-inode cleanup, active conflicts, probe, STOP with/without a hold, expiry, idle clients, unexpected disconnect, SIGTERM/SIGINT during an active hold, and acquire/release failures. Build output and temporary-directory symlink behavior are tested. Non-owner file replacement is refused by source inspection; changing ownership is not required by unprivileged tests.

Additional local checks: Python syntax compilation, Bash syntax checks, and `git diff --check` passed. Compiling `src/power.c` without the mock definition failed at the expected `#error`, confirming the gate. Running `./scripts/build-macos.sh` on Linux intentionally returned exit 1 with `iPhoneOS SDK required. Run with Xcode on macOS.`; it did not build against a host or unofficial SDK.

## Current-branch CI history

- Implementation commit `434f85a78f356cd8804c9ebb1638614884ca8f54`, [run 38867232447](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/38867232447): Linux SUCCESS; iOS cross-build FAILED; inspection SKIPPED. Official iPhoneOS26.5 SDK under Xcode 26.6 reported hidden `O_NOFOLLOW`, `flock`/`LOCK_EX`/`LOCK_NB`, and `MSG_DONTWAIT` declarations under strict `_POSIX_C_SOURCE`.
- Fix: enable `_DARWIN_C_SOURCE` before system headers in CLI and daemon on Apple builds, retaining C11 and the same deployment target. No fallback constants or manually invented API declarations.

## Hardware evidence record

Signing: PENDING. Runtime: PENDING. IOKit load: PENDING. Both symbol lookups: PENDING. Create return code/ID: PENDING. Release return code: PENDING. STOP/expiry/SIGTERM/socket cleanup on iOS: PENDING. Battery/thermal observation: PENDING.

LAN display-on/locked, without assertion/during bounded assertion/after release: PENDING. Tailscale display-locked in each condition: PENDING. No latency or reachability values have been fabricated. Follow [device testing and rollback](P002-DEVICE-TEST.md) and record timestamps, raw output, return codes, hashes and independent measurements before promoting any evidence level.

Known limitations: iOS API support is unknown; dynamic symbol resolution can fail or return unsupported. A userspace deadline cannot force cleanup while the daemon is suspended or an API blocks. Failed release stays unresolved until measured successful; daemon exit is not evidence of an iOS release. A disconnected START may succeed despite missing its reply; inspect status and STOP it. No scheduled wake or indefinite mode exists. Screen-lock network trials require confirmed physical recovery.
