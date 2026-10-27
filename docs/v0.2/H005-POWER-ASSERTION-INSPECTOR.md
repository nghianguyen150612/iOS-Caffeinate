# H005 — Read-only power assertion inspector

## Scope

This is a standalone C11 ARM64 command-line diagnostic for the iPad mini 2 A1489 (`iPad4,4`), iOS 12.5.7, Amethyst/Procursus rootful. It does not link to, install, start, stop, or require the iOS-Caffeinate daemon. It is built outside the rootful package and is not included in package inputs.

The source and host checks do not authorize device transfer or execution. The H004 scope excludes staging this binary. Physical deployment or execution requires a separately reviewed and authorized session.

## API investigation

| Interface | Declaration and result shape | iOS 12 evidence | Inspector use |
|---|---|---|---|
| `IOPMCopyAssertionsByProcess` | `IOReturn IOPMCopyAssertionsByProcess(CFDictionaryRef *AssertionsByPID)`. Success returns a caller-owned dictionary keyed by PID (`CFNumber`), with a `CFArray` of assertion dictionaries containing `AssertType` (`CFString`) and `AssertLevel` (`CFNumber`). | The shared `IOPMLib.h` declaration is annotated `AVAILABLE_MAC_OS_X_VERSION_10_5_AND_LATER`, so that header does not promise iOS availability. The iOS 12.4 ARM64 IOKit stub nevertheless exports `_IOPMCopyAssertionsByProcess`. | Resolve by `dlsym`; call only if present; inspect PID, type, and level. A missing symbol or denied/ambiguous result cannot yield a clear result. |
| `IOPMCopyAssertionsStatus` | `IOReturn IOPMCopyAssertionsStatus(CFDictionaryRef *AssertionsStatus)`. Success returns a caller-owned dictionary from assertion type to aggregate `CFNumber` level. | It has the same macOS-only header annotation, while the iOS 12.4 ARM64 IOKit stub exports `_IOPMCopyAssertionsStatus`. | Resolve by `dlsym`; report the aggregate type and level. A nonzero aggregate is positive evidence even if the per-process response is empty. |
| `IOPMrootDomain` driver properties | `IORegistryEntryCreateCFProperties` returns a read-only property snapshot. XNU 4903.221.2 documents `DriverPMAssertions` as an aggregate bit mask and `DriverPMAssertionsDetailed` as an array with `ID`, `Owner`, `Level`, and `Assertions` fields. | These properties are published by the XNU power assertion tracker. The iOS 12.4 IOKit stub exports the IOKit registry query functions used here. | Match `IOPMrootDomain`, read its property snapshot, and serialize only the two assertion properties. The complete snapshot is never printed or written. |

Sources checked:

- [`IOPMLib.h` at theos/headers commit `13c1f17176d7efe6871551cd69a75b71ac4eeaf1`](https://github.com/theos/headers/blob/13c1f17176d7efe6871551cd69a75b71ac4eeaf1/IOKit/pwr_mgt/IOPMLib.h), declarations and availability annotations. SHA-256 of the retrieved header: `99a6ba4a5e3fee627cda996fb6e401a489223d51388f4f742eed56fa2afc7b66`.
- [`IOKit.tbd` in theos/sdks iPhoneOS 12.4 SDK commit `0222fd5413cf4b9af096f37b4621afa2688572f7`](https://github.com/theos/sdks/blob/0222fd5413cf4b9af096f37b4621afa2688572f7/iPhoneOS12.4.sdk/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit.tbd). Its arm64 exports include both IOPM functions and the registry functions. SHA-256: `b2b3ce6f0264dc8b885a2a29616df5e982972e579de283f0302e4b23104ce027`.
- [Apple `kIOMasterPortDefault` documentation](https://developer.apple.com/documentation/iokit/kiomasterportdefault) states that a NULL primary-port argument selects the default; current iPhoneOS headers mark the named constant unavailable on iOS.
- [Apple XNU `IOPM.h` at tag `xnu-4903.221.2`](https://github.com/apple-oss-distributions/xnu/blob/xnu-4903.221.2/iokit/IOKit/pwr_mgt/IOPM.h) and [the matching `IOPMrootDomain.cpp`](https://github.com/apple-oss-distributions/xnu/blob/xnu-4903.221.2/iokit/Kernel/IOPMrootDomain.cpp), which document and publish the driver assertion properties. This XNU source is an iOS 12 era reference, not a measurement of the target device's kernel build.

The public declaration establishes the IOPM return type and dictionary ownership: `IOReturn` is a 32-bit IOKit result, and the output is a `CFDictionaryRef *` released by its caller. The iOS SDK stub establishes that the named symbols are linkable/exported by that SDK build; it does not establish that the private-on-iOS entry points are callable on iOS 12.5.7 or accessible to a rootful command-line process. The inspector therefore uses the header-derived function-pointer ABI with runtime symbol lookup and checks each `IOReturn`. It does not hard-link either optional IOPM function.

## Driver masks and sleep-prevention ownership

The driver mask is a separate assertion domain from `IOPMCopyAssertionsByProcess` and `IOPMCopyAssertionsStatus`. Apple XNU `xnu-4903.221.2` [`IOPM.h`](https://github.com/apple-oss-distributions/xnu/blob/xnu-4903.221.2/iokit/IOKit/pwr_mgt/IOPM.h#L315-L382) defines the following driver bits:

| Bit | XNU meaning | Inspector interpretation |
|---:|---|---|
| `0x001` | CPU bit: prefer to keep CPU/core hardware running in Dark Wake instead of sleeping | Driver-domain sleep-related evidence; owner label must be present. |
| `0x004` | External USB device attached | Driver observation; not a user-space sleep assertion. |
| `0x008` | Bluetooth HID paired | Driver observation; not a user-space sleep assertion. |
| `0x010` | External media mounted | Driver observation; not a user-space sleep assertion. |
| `0x020` | Reserved for Thunderbolt | Reserved driver bit. |
| `0x040` | Keep display powered while the system is awake | Display-domain driver observation. |
| `0x080` | Reserved for storage family | Reserved driver bit. |
| `0x100` | Magic-packet wake enabled | Network wake configuration; not equivalent to user-space `PreventUserIdleSystemSleep`. |
| `0x200` | Network interface held up for TCP keep-alive | Network driver observation; not a user-space sleep assertion. |

The JSON category token for bit `0x100` is `MAGIC_PACKET_WAKE_ENABLED`.

This is an interpretation of the iOS 12 era XNU source, not a live measurement of the iPad's private kernel. The previously reported `IOPMrootDomain` mask `0x100`, owner `en0`, ID `500`, level `255` is a positive driver-domain observation. The cited source defines bit `0x100` as magic-packet wake enabled. That record alone does not establish a process assertion preventing idle system sleep or iOS-Caffeinate ownership. The global classification still reports `ASSERTIONS_PRESENT` for the record.

Process records are grouped by PID and assertion type. The inspector does not query process names or paths, so a valid PID is reported as `PID_ONLY`; it identifies a numeric owner key, not an application identity. Recognized active user-space sleep-prevention types are `PreventSystemSleep`, `PreventUserIdleSystemSleep`, and the documented legacy `NoIdleSleepAssertion` and `NoDisplaySleepAssertion`. `NetworkAccess`, `PreventDiskIdle`, and `BackgroundTask` are categorized separately. `PreventUserIdleDisplaySleep` is reported as display-only. An active unrecognized type, unknown PID/driver owner, inconsistent driver summary/details, unknown driver bit, or incomplete critical source cannot establish clearance.

Schema v2 adds `assertion_domain`, per-record `assertion_role` and owner state, driver-bit category names, `execution_timeout_seconds=15`, `project_assertion_attribution=NOT_PERFORMED_NO_PROCESS_NAMES_QUERIED`, and `sleep_prevention_ownership`:

| Value | Meaning |
|---|---|
| `ACTIVE_SLEEP_PREVENTION_OWNER_IDENTIFIED` | A recognized active sleep-prevention type is tied to a PID, or the documented CPU Dark Wake driver bit is tied to a driver owner label. This does not identify a process name or attribute it to iOS-Caffeinate. |
| `ACTIVE_SLEEP_PREVENTION_OWNER_UNKNOWN` | A relevant active aggregate has no matching per-process owner, or a relevant active owner key is missing. This blocks clearance. |
| `NO_ACTIVE_SLEEP_PREVENTION_OBSERVED_COMPLETE` | All critical sources are complete and recognized, with no active sleep-prevention owner observed. This is a bounded snapshot, not a safety certificate or proof that a project process is absent. |
| `UNESTABLISHED` | A critical source is unavailable/incomplete, an active type/driver bit is unknown, a driver owner is unknown, or evidence conflicts. This blocks clearance. |

The global `classification` remains separate. Any observed process record, nonzero aggregate, driver mask, or driver record yields `ASSERTIONS_PRESENT`, including known unrelated system assertion types and network wake configuration. A recognized unrelated network assertion is not automatically labeled an unresolved iOS-Caffeinate sleep assertion; this diagnostic does not perform project-process attribution.

The root-domain query also may be denied or may expose a different property shape on the target build. The current iPhoneOS SDK marks `kIOMasterPortDefault` unavailable on iOS, so the read-only registry query passes `MACH_PORT_NULL` (the zero-valued default port) to `IOServiceGetMatchingService`; Apple documents a NULL primary-port argument as “use the default.” It does not import a macOS-only port constant. Rootful UID alone is not treated as proof of IOKit privilege. The code makes no entitlement change and never retries through a different user, executable, or transport. `UNAVAILABLE` records a missing symbol/service/property or explicit privilege denial; unexplained return codes and malformed property/data shapes are `UNKNOWN`.

## Read-only and privacy contract

The binary calls only IOPM copy/query and IOKit registry read functions. It has no call or import for assertion creation, retention, release, level changes, or property changes. The JSON contains `"assertion_mutation_attempted": false`. `CFRelease` disposes of the copied dictionaries after reading them; `IOObjectRelease` disposes of the IOKit service reference. Neither operation releases or changes a power assertion.

Output is one bounded JSON object on stdout. It includes process PIDs, assertion types and levels, aggregate types and levels, and driver assertion masks, owner labels, IDs, and levels when present. It omits process names, assertion names/details, bundle IDs/paths, driver service pointers, registry entry IDs, and timestamps. Type and owner strings are restricted to short ASCII tokens; other values are reported as `REDACTED`. The raw IOKit property snapshot is never serialized.

The inspector caps process owners at 32, process assertion records at 64, aggregate types at 32, driver records at 32, and JSON output at 16 KiB. It arms a process-local 15-second `alarm()` around the three queries, then cancels it before serialization. If the deadline fires, the OS terminates the one-shot process; the operator records the signal and treats the query as incomplete. A deadline cannot guarantee interruption of a kernel operation that is itself uninterruptible. Any count or output overflow marks enumeration incomplete and cannot produce `NO_ASSERTIONS_OBSERVED`.

| Classification | Meaning | Exit |
|---|---|---:|
| `NO_ASSERTIONS_OBSERVED` | All three sources returned complete, well-formed snapshots and no assertion records or nonzero status were observed. This is a single sequential snapshot, not proof of safety or a guarantee that state cannot change immediately afterward. | 0 |
| `ASSERTIONS_PRESENT` | At least one process owner/record, nonzero aggregate status, nonzero driver mask, or driver record was observed. This is a domain-neutral positive observation, not a claim that an iOS-Caffeinate assertion is active. | 10 |
| `UNAVAILABLE` | No positive observation was available and at least one required source was unavailable, including a missing symbol or explicit privilege denial. | 20 |
| `UNKNOWN` | No positive observation settled the result, but one or more sources failed ambiguously, returned malformed data, or exceeded a bound. | 21 |

Positive evidence remains `ASSERTIONS_PRESENT` even if another source is incomplete; `enumeration_complete=false` still blocks a clean interpretation. The operator uses the JSON classification, source states, record domains, and sleep-prevention ownership assessment, not a zero exit code as a safety certificate. PIDs are not resolved to process identities; correlate them only with separately authorized evidence and do not infer iOS-Caffeinate ownership from assertion type alone.

## Build and validation

On macOS with Xcode, the native cross-build uses the official iPhoneOS SDK and targets `arm64-apple-ios12.0`:

```sh
./scripts/build_h005_inspector.sh
```

The build writes only under `build/h005/`. `scripts/h005_macho_audit.py` inspects the Mach-O architecture, iOS platform and minimum OS load command, linked IOKit/CoreFoundation frameworks, runtime lookup names, and absence of assertion-mutation imports. The IOPM functions remain runtime lookups rather than hard imports. The build is unsigned and is not fed into `scripts/package_rootful.py`.

Portable mock cases exercise complete empty results, the `en0`/`0x100` network-wake driver case, CPU Dark Wake driver evidence, active user assertions, a recognized `NetworkAccess` assertion, unknown owners and types, unmatched aggregate ownership, missing symbols, privilege denial, mixed/incomplete sources, malformed results, nonstandard levels, bounded output, JSON escaping, and result-specific exit codes:

```sh
./scripts/test_h005_inspector.sh
python3 -m unittest tests.test_h005_dpkg_exception -v
```

CI runs the mocks and the standalone iOS cross-build. H005B separately signs the standalone inspector with the pinned R05A signer/profile, audits the Mach-O independently, and runs Apple `codesign --verify --strict --verbose=4` against the exact signed binary. The signed binary is uploaded as `H005B-SIGNED-DEVICE-UNVERIFIED`, outside every package, daemon, CLI, launchd, and stable release asset. Cross-building, signing, and Apple host verification do not test IOPM runtime behavior, driver-property visibility, privilege, or assertion enumeration on iOS 12.5.7. No device transfer or execution is recorded by H005 host validation.

## Device-use boundary

Do not stage or transfer this diagnostic under H004. During the next H004 session, use only already available and separately approved read-only inspection methods. If process-level ownership or current driver assertion state cannot be established from those methods, record `UNKNOWN` and stop. A later physical inspector run requires its own reviewed authorization and evidence plan; it does not install or start the iOS-Caffeinate daemon. Follow the [separate H005B diagnostic runbook](H005B-DIAGNOSTIC-RUNBOOK.md).
