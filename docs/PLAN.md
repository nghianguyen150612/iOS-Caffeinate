# Roadmap — iOS-Caffeinate

| Milestone | Deliverable | Status |
|---|---|---|
| P001 | Native C CLI/daemon, bounded hold, mock tests, unsigned iOS cross-build and disabled launchd template | Baseline `069ad94eb344da08d414c9478b6e212146c8fc28` verified |
| P002 | Source audit, canonical names, runtime diagnostics, iOS 12 ARM64 build/inspection, safe hardware and network validation | Cloud/local engineering complete; hardware PENDING; see P002 evidence |
| P003 | Robust daemon state machine, lifecycle management, Unix IPC peer credential security, efficient deadline event loop, bounded release retries and diagnostics | Cloud/local engineering complete; hardware PENDING; see P003 validation evidence |
| P004 | --until, persisted one-time/daily/weekly schedules, daemon restart recovery | Integrated on the P004 aggregate branch; target assertion and network behavior remain hardware PENDING |
| P005 | Scheduled-wake feasibility, read-only capability diagnostics, tests, and deferred hardware procedure | Cloud engineering and exact-commit CI complete; hardware PENDING; scheduled wake UNVERIFIED |
| P006 | Server-mode foundation, health monitoring, safety policy, connectivity evidence, and deferred hardware validation plan | Engineering implemented; hardware PENDING; 24/7 NOT VALIDATED |
| P007 | Rootful `.deb` packaging, installation safety, artifact verification, rollback and regression testing | Integrated at the P007 merge baseline; package remains unsigned and hardware validation is PENDING |
| P008 | Full P001–P007 integration audit, regression, package consistency, release manifest and readiness gates | Cloud candidate validation is tied to the exact P008 source SHA; hardware validation is PENDING; v0.1 has not shipped |
| P009 | Versioned device-evidence contract, offline validator/replay, readiness gates, integrity checks, operator runbook, and CI | Cloud engineering implemented; exact-final-SHA CI pending; all physical gates PENDING; scheduled wake UNVERIFIED; 24/7 NOT VALIDATED |

P004/P005 hardware gate: iPad binary execution, IOKit create/release results, a bounded first timed hold, STOP/expiry/SIGTERM cleanup, controlled screen-lock observations, separate LAN and Tailscale measurements, and confirmed physical recovery. API acceptance alone cannot pass network or scheduled-wake gates. P005 does not run device experiments and does not add a wake alarm command. P008 cloud CI does not pass any device gate.

P005 was integrated at verified SHA `77f3f15dda5c75f10e40b48fc0575d47fa38b80e`. P006 was merged at `dfe32d2b7edfd0677f282ce6e391c43706f19ac5`, and P007 at `c8512508a80be5fc09d0c62b2e26877717af23df`. P004–P007 hardware limitations remain pending; no prior milestone history is rewritten here. P007's artifact remains unsigned and device-unverified. P008 run-specific CI evidence and the generated release-readiness matrix are linked from [P008 validation](P008-VALIDATION.md). See [deferred P007 device gates](P007-DEVICE-TEST.md).

P009 starts at the verified P008 source SHA `256611b97004f798c7dadd41ff25c8ebf95b6db5` on a stacked branch targeting `release/p008-v01-integration`. Offline P009 fixture results do not establish physical acceptance. The iPad mini 2 remains unavailable; hardware acceptance and 24/7 readiness are not inferred. See [P009 validation](P009-VALIDATION.md) and [P009 project readiness](P009-READINESS.md).
