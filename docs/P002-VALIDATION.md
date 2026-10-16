# P002 audit and evidence — 2026-10-16

P002 status: PARTIAL overall; all cloud/local engineering gates are complete. Hardware gates remain PENDING. No iPad changes have been made.

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
| SOURCE VALIDATED | PASS | P001 files reviewed and P002 fixes inspected; final source/diff review and whitespace checks passed |
| MOCK TESTED | PASS locally | `./scripts/build-linux-test.sh` + `python3 tests/integration.py`; 20 integration tests, UID 1000, C11 `-Wall -Wextra -Werror`; latest source run: 20/20 OK in 10.031 seconds; no power effect |
| CROSS-BUILD VALIDATED | PASS in macOS Actions | Exact implementation SHA `8534e88716623dbb25d589a3843a29c3fb618a46`; all three jobs SUCCESS in [run 38867358085](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/38867358085); official iPhoneOS 26.5 SDK, ARM64 device platform, min iOS 12.0 |
| DEVICE RUNTIME VALIDATED | PENDING | No reachable authorized iPad session |
| ASSERTION API VALIDATED | PENDING | No real IOKit load/symbol/create/release measurements |
| NETWORK EFFECT VALIDATED | PENDING | No screen-locked LAN SSH or independent Tailscale measurements |

Mock coverage: invalid/zero/overflow/>24h durations, 24h acceptance followed by STOP, missing/unknown/extra CLI args, exact exit codes, malformed/fragmented IPC, incomplete and timed-out replies, concurrent startup, stale/crashed socket recovery, 0600 ownership, live endpoint preservation, unsafe file/symlink refusal, replacement-inode cleanup, active conflicts, probe, STOP with/without a hold, expiry, idle clients, unexpected disconnect, SIGTERM/SIGINT during an active hold, and acquire/release failures. Build output and temporary-directory symlink behavior are tested. Non-owner file replacement is refused by source inspection; changing ownership is not required by unprivileged tests.

Additional local checks: Python syntax compilation, Bash syntax checks, and `git diff --check` passed. Compiling `src/power.c` without the mock definition failed at the expected `#error`, confirming the gate. Running `./scripts/build-macos.sh` on Linux intentionally returned exit 1 with `iPhoneOS SDK required. Run with Xcode on macOS.`; it did not build against a host or unofficial SDK.

## Current-branch CI history

- Implementation commit `434f85a78f356cd8804c9ebb1638614884ca8f54`, [run 38867232447](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/38867232447): Linux SUCCESS; iOS cross-build FAILED; inspection SKIPPED. Official iPhoneOS26.5 SDK under Xcode 26.6 reported hidden `O_NOFOLLOW`, `flock`/`LOCK_EX`/`LOCK_NB`, and `MSG_DONTWAIT` declarations under strict `_POSIX_C_SOURCE`.
- Fix: enable `_DARWIN_C_SOURCE` before system headers in CLI and daemon on Apple builds, retaining C11 and the same deployment target. No fallback constants or manually invented API declarations.

## Verified cross-build and Mach-O evidence

Tested implementation commit: **`8534e88716623dbb25d589a3843a29c3fb618a46`**, [Actions run 38867358085](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/38867358085), completed 2026-10-16 07:28:24 UTC.

| Job | Result | Evidence |
|---|---|---|
| `linux-protocol` | SUCCESS | 20 tests OK in 9.964s; ungated Linux compile rejected |
| `ios-cross-build` | SUCCESS | Both binaries compiled/linked; official iPhoneOS 26.5 SDK / Xcode 26.6; Apple clang 21.0.0; symlink and disabled plist checks passed |
| `ios-artifact-inspection` | SUCCESS | Downloaded the uploaded unsigned binaries on a separate macOS runner; file/lipo/otool/vtool/codesign checks passed; evidence report uploaded |

Actual build target is `arm64-apple-ios12.0`. The compiler's `--version` host target (`arm64-apple-darwin25.6.0`) describes the runner/compiler default, not these artifacts. Both artifacts have `MH_MAGIC_64`, `ARM64 ALL`, `EXECUTE`, `NOUNDEFS DYLDLINK TWOLEVEL PIE`; `LC_BUILD_VERSION platform 2` / vtool `IOS`, `minos 12.0`, SDK `26.5`. No simulator or macOS platform slice is present. Loader is `/usr/lib/dyld`.

- CLI direct dependencies: `/usr/lib/libSystem.B.dylib` only.
- Daemon direct dependencies: `/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation` and `/usr/lib/libSystem.B.dylib` only.
- IOKit assertion symbols remain runtime lookups, not unresolved build-time imports. No IOKit, private framework, host SDK, or simulator linkage is used. Deployment compatibility beyond SDK availability checks still needs actual iOS 12 execution.
- Both binaries have no `LC_CODE_SIGNATURE`; `codesign -d` reports `code object is not signed at all`. This verifies unsigned state; it is not device signing evidence.

Unsigned binary SHA256 values for this tested commit:

```text
2ffdfda404bb901beec56280e067e17bebe2fbed637e1bb442661c76afb1eb7b  ios-caffeinate
a60497ea6a7c055ba03f25105e511f0abff6fe722974f00536574e68e6fab74b  ios-caffeinated
```

Artifact name: `iOS-Caffeinate-ios12-arm64-UNSIGNED-HARDWARE-UNVERIFIED`, ID `12031248138`, zip SHA256 `bafdf73bdb07e8f82dd7d899c0d833075ed0801b3ded58eeeb3ceb61f7ca81c7`. Separate evidence artifact: `iOS-Caffeinate-ios12-arm64-inspection-evidence`. See the [full extracted inspection stdout](evidence/P002-8534e88-inspection.txt), retained in Git so evidence survives Actions artifact expiration.

The cloud workspace's `gh run download` attempt returned HTTP 403 from artifact storage. No binary was downloaded here and no local Mach-O/signing result is claimed. The separate CI inspection job successfully downloaded and inspected the artifact, and its full stdout was retrieved using `gh run view --log`. Obtain the unsigned files through the linked Actions run before hardware testing. Later documentation-only commits do not change this tested implementation; their exact-commit CI result is reported separately in the final delivery report.

## Hardware evidence record

Signing: PENDING. Runtime: PENDING. IOKit load: PENDING. Both symbol lookups: PENDING. Create return code/ID: PENDING. Release return code: PENDING. STOP/expiry/SIGTERM/socket cleanup on iOS: PENDING. Battery/thermal observation: PENDING.

LAN display-on/locked, without assertion/during bounded assertion/after release: PENDING. Tailscale display-locked in each condition: PENDING. No latency or reachability values have been fabricated. Follow [device testing and rollback](P002-DEVICE-TEST.md) and record timestamps, raw output, return codes, hashes and independent measurements before promoting any evidence level.

Known limitations: iOS API support is unknown; dynamic symbol resolution can fail or return unsupported. A userspace deadline cannot force cleanup while the daemon is suspended or an API blocks. Failed release stays unresolved until measured successful; daemon exit is not evidence of an iOS release. A disconnected START may succeed despite missing its reply; inspect status and STOP it. No scheduled wake or indefinite mode exists. Screen-lock network trials require confirmed physical recovery.
