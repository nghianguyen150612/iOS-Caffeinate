# P020 Verified Integration Matrix

Cloud status below reflects source review, the exact P019 CI baseline, and the P020 validation job design. Cloud tests do not count as iPad acceptance. “Runtime acceptance” is target hardware acceptance, not mock execution.

| Component | Owning milestone and source | Current behavior and dependencies | Coverage | Limitations | Runtime acceptance | Release significance |
|---|---|---|---|---|---|---|
| CLI and daemon protocol | P003/P018: `src/cli.c`, `src/daemon.c`, `src/service.c` | Bounded text commands; status and diagnostics are read-only; default socket requires root peer UID; one client is serviced at a time. | `tests/integration.py`, `tests/test_p018_cli.py`, `tests/test_p013_service.py`, native integration CI. | No concurrent worker pool; a client can occupy the command loop for at most the bounded read/write timeout. | Pending P011/P013/P019 device review. | Core privileged interface. |
| Assertion ownership and expiry | P003/P011/P012: `src/power.c`, `src/daemon.c` | One owned assertion; manual holds have explicit limits; STOP/expiry release through one path; release failure preserves ownership and blocks new work. | Native mock protocol suite, Linux compile gate, iOS ARM64 cross-build and Mach-O inspection. | Linux mock is not IOKit behavior. OS suspension and SSH continuity are not guaranteed. | Pending P011 package acceptance and P019 cycles. | Release-critical safety path. |
| Graceful shutdown | P003/P013: `src/daemon.c`, `src/service.c` | Shutdown requires a resolved state and confirmed assertion release; SIGTERM/SIGINT request cleanup. | Integration, service lifecycle, recovery unit tests. | A failed release leaves unresolved state and nonzero exit. No automatic SIGKILL fallback. | P013/P014 physical cleanup pending. | Release-critical cleanup path. |
| Schedule persistence and diagnostics | P004/P017: `src/schedule.c`, `src/daemon.c`, `src/cli.c` | v1 storage is retained; recurrence is calendar/timezone aware; updates use generation preconditions; previews and conflicts are diagnostic. | `tests/p017_schedule_unit.c`, `tests/test_p017_schedule_cli.py`, P017 DST/conflict CI. | Future occurrences are not execution authorization and are not polled for assertion acquisition. Deep-sleep wake is unverified. | P017 device review pending. | Disabled by policy for unattended execution. |
| P013 service observations | P013: `src/service.c`, `packaging/com.ioscaffeinate.daemon.plist` | Status/doctor/plan are read-only; unknown registration remains unknown; package template is staged and disabled. Managed profile requires `KeepAlive=false`, `RunAtLoad=false`. | `tests/p013_service.c`, `tests/test_p013_service.py`, package template tests. | iOS 12 launchctl semantics and target registration are unverified; lifecycle commands remain gated. | Pending target acceptance. | Do not activate or mutate launchd. |
| P014 recovery journal and startup gate | P014: `src/recovery.c`, `src/daemon.c`, `src/service.c` | Bounded 3-attempt/10-minute accounting, 5/15/60 second policy, healthy reset, atomic journal; missing/corrupt/unknown cleanup blocks acquisition. | `tests/p014_recovery_unit.c`, filesystem fault injection, P014 CI. | Policy eligibility does not execute a restart; physical supervisor/cleanup state is unknown. | Pending physical recovery review. | Release-critical safety gate. |
| P015 Server Mode policy | P015: `src/server_mode.c`, `src/server_policy.c`, `src/server_policy.h` | Strict v1/v2 read-only evaluation and bounded attended-session policy; default denies unattended execution. | `tests/p015_policy_unit.c`, `tests/test_p015_policy_cli.py`, P015 CI. | No automatic daemon, assertion, schedule, network, wake, or launchd action. | Pending target review; no unattended mode. | Keep denial intact. |
| P016 health and telemetry | P016: `src/health.c`, `src/health_ios.c`, `src/health_policy.c` | On-demand snapshots preserve missing/unknown values; critical thermal observations can block conservatively; diagnostics cannot grant authorization. | `tests/p016_health_unit.c`, `tests/test_p016_health.py`, P016 CI. | Battery/charging/thermal APIs may be unavailable on iOS 12.5.7; no calibrated battery-health claim or safe unattended envelope. | Availability review pending. | Release limitation and safety input. |
| P017 recurrence and authorization | P017: `src/schedule.c`, `src/daemon.c`, `src/server_policy.c` | DST/timezone and occurrence identity are deterministic; v1 data is preserved; proposals are bounded; policy denies scheduled assertion execution. | Schedule/DST/conflict tests and daemon safety checks. | Automatic scheduled execution remains disabled; no chaining shorter holds into an unlimited hold. | Pending diagnostic review only. | Required policy boundary. |
| P018 package and evidence tools | P018: `packaging/rootful/manager`, `scripts/p018_*.py`, maintainer scripts | Read-only preflight, safe inventory/export, archive checks, update/removal guards, rollback preview. | `tests/test_p018_manager.py`, package-preflight and export suites, root-owned isolated tests. | A sanitized export is a derivative; hashes prove file consistency, not empirical truth. | No target export accepted. | Protect private P009 originals and package state. |
| P019 supervised trial framework | P019: `scripts/p019_session.py`, `experiments/p019/*`, `docs/v0.2/P019-*` | Preregistered 24-trial P012 matrix and 12 attended cycles across 3 dates; strict schemas and simulated-only cloud fixtures. | `tests/test_p019_session.py`, P009/P012/P018 compatibility suites, P019 CI. | No physical P019 trial is accepted. A clean simulated report is not hardware evidence. | Pending independent review. | Release-critical evidence gate. |
| P020 candidate and release gate | P020: `scripts/p020_build_provenance.py`, `scripts/p020_release_gate.py`, schemas, CI | Two unsigned `0.2.0~rc1-1` builds/packages are compared; the offline gate uses exact source and signed evidence/review references. | P020 negative-path tests and final exact-head workflow. | Provenance JSON is not a digital signature. Review signatures need an externally managed trusted keyring; physical observations still need human review. | Not installed; hardware gates pending. | Blocks stable publication until evidence and authorization pass. |

## Dependency chain

P011 #10 → P012 #11 → P013 #12 → P014 #13 → P015 #14 → P016 #15 → P017 #16 → P018 #17 → P019 #18. GitHub has merged the nine PRs into `main` in this order. P020 retains the exact P019 source commit as its parent/merge-base and targets the now-integrated `main`; earlier milestone history is preserved and is not changed by P020.

## Feature and release-claim matrix

Each row records the strongest current implementation/acceptance label. A cross-build is not target execution; a cloud test is not physical acceptance.

| Capability | Current category | Evidence boundary / release claim |
|---|---|---|
| Manual bounded holds | `CROSS_BUILT_IOS` | Native iOS build path exists; actual signed-package/device acceptance remains pending. |
| Explicit STOP and expiry | `CROSS_BUILT_IOS` | Release is safety-gated; successful cleanup still needs target review. |
| Native assertion backend | `CROSS_BUILT_IOS` | IOKit backend is compiled for iOS; runtime lifecycle is not device-verified. |
| Graceful shutdown | `CROSS_BUILT_IOS` | Failed release remains failure and blocks cleanup; P013/P014 hardware acceptance pending. |
| Schedule storage and diagnostics | `CROSS_BUILT_IOS` | Recurrence, DST, generation, and conflict checks are cloud-tested; future events do not acquire assertions. |
| Automatic scheduled execution | `DISABLED_BY_POLICY` | P017 explicitly denies execution; schedule storage is diagnostic only. |
| Launchd management | `DISABLED_BY_POLICY` | Read-only status/doctor/plan exist; activation and unverified launchctl mutations stay gated. |
| Crash classification | `CROSS_BUILT_IOS` | Classification/accounting exists; it does not restart a process. |
| Restart-loop suppression | `CROSS_BUILT_IOS` | Bounded accounting and startup gates exist; not an automatic restart executor. |
| Actual automatic restart | `NOT_IMPLEMENTED` | No production restart executor. |
| Server Mode v2 evaluation | `CROSS_BUILT_IOS` | Policy-only evaluation; unattended execution remains denied. |
| Battery/thermal telemetry | `HARDWARE_REVIEW_PENDING` | On-demand interfaces preserve unavailable/unknown; source availability is not established on the target. |
| CLI diagnostics | `CROSS_BUILT_IOS` | Read-only diagnostics are implemented; they do not grant execution authorization. |
| Package preflight | `IMPLEMENTED_CLOUD_TESTED` | Read-only archive, identity, and state checks; no target package installation. |
| Evidence export | `IMPLEMENTED_CLOUD_TESTED` | Privacy-filtered derivative; hashes do not establish that observations occurred. |
| LAN/Tailscale research | `HARDWARE_REVIEW_PENDING` | Trial protocol and analyzer exist; no accepted physical P012 trial set. |
| Physical endurance reliability | `HARDWARE_REVIEW_PENDING` | P019 specifies 12 supervised cycles over three dates; none has been accepted. |
| Device-verified v0.2 behavior | `HARDWARE_REVIEW_PENDING` | No capability currently has the `DEVICE_VERIFIED` category; all target acceptance is pending. |
| Scheduled deep-sleep wake | `UNSUPPORTED` | No wake guarantee or verified scheduled wake support. |
| Calibrated battery-health monitoring | `UNSUPPORTED` | No calibrated battery-health source or claim. |

`IMPLEMENTED_CLOUD_TESTED`, `CROSS_BUILT_IOS`, `DEVICE_VERIFIED`, `HARDWARE_REVIEW_PENDING`, `DISABLED_BY_POLICY`, `UNSUPPORTED`, and `NOT_IMPLEMENTED` are release inventory labels, not interchangeable acceptance claims.
