# P005 — Validation Record

## Source and branch baseline

- Repository: `nghianguyen150612/iOS-Caffeinate`
- P004 base branch: `feat/p004-timed-scheduling-381823536033500942`
- Verified P004 base SHA: `0b10c4a277e5a05327dd584fb21252e9b8d5ed4a`
- P005 branch: `feat/p005-wake-feasibility`
- P005 is stacked directly on that verified P004 commit. No P002–P004 history was rewritten.
- The checked-out P004 baseline passed the requested Linux command before P005 changes: 26 integration tests passed. The P004 validation document's older count of 24 is stale; P005 records the observed baseline without refactoring P004 documentation.

## P005 checks

`ic wake status` is a standalone CLI path compiled from `src/wake_capability.c`. Its report is deterministic and has no dependency on an active daemon or an optional IOKit probe. The Linux binary identifies itself as `platform=linux`, `backend=MOCK_NO_POWER_EFFECT` and reports `scheduled_wake=unverified`, `wake_guarantee=no`, and `hardware_validation=pending`.

The added Linux integration coverage verifies:

- status works with no daemon socket and also while an idle daemon is present;
- stable key ordering and explicit unverified/unsupported-mock capability fields;
- the P004 schedule file remains byte-for-byte unchanged;
- an idle daemon remains inactive after the query;
- unavailable runtime probes do not crash;
- invalid wake command forms return usage exit code 2;
- existing P004 `--until` and schedule CRUD regressions remain covered by the full suite.

Run the project validation commands:

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
```

The Linux mock is not hardware evidence and cannot pass a wake experiment.

P005 local result: `./scripts/build-linux-test.sh && python3 tests/integration.py` completed successfully; **28/28 tests passed**.

## iOS build and CI evidence

The iOS CLI build includes the new pure C11 capability module. The target remains `arm64-apple-ios12.0`; the daemon, warning level, unsigned policy, and Mach-O inspection rules are unchanged. No new framework or library dependency is introduced.

The exact P005 commit must pass all three existing GitHub Actions jobs:

1. `linux-protocol` — strict C11 Linux mock build and integration suite;
2. `ios-cross-build` — official iPhoneOS SDK cross-build and symlink/plist checks;
3. `ios-artifact-inspection` — device ARM64, iOS 12 minimum, dependencies, and unsigned-state inspection.

The authoritative final-commit run is linked in the P005 completion report. It must be associated with the final pushed commit SHA, and all three job conclusions must be successful. Cross-compilation and Mach-O inspection do not prove binary execution or IOKit behavior on the iPad.

## Hardware state

- iPad mini 2 A1489 / Apple A7 / iOS 12.5.7: unavailable.
- Screen lock and LAN/Tailscale reachability: pending.
- `IOPMAssertionCreateWithName` target availability/effect: pending; current Apple API docs list macOS and Mac Catalyst, not iOS.
- Scheduled wake: pending and unverified; no experiment or wake API call was made.
- Assertion support: pending.
- Binaries remain unsigned and hardware-unverified.

## Existing branch integration debt

P005 is correctly based on P004. At the verified baseline, P004 was four commits ahead of `main`; the named P002 and P003 refs were parallel/divergent refs rather than P004's direct parent chain. This milestone leaves that pre-existing integration history intact. Any later integration should compare the full P004 stack with `main` before selecting a base; this note does not authorize history reconstruction or a merge.
