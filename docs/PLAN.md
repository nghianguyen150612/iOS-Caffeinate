# Roadmap — iOS-Caffeinate

| Milestone | Deliverable | Status |
|---|---|---|
| P001 | Native C CLI/daemon, bounded hold, mock tests, unsigned iOS cross-build and disabled launchd template | Baseline `069ad94eb344da08d414c9478b6e212146c8fc28` verified |
| P002 | Source audit, canonical names, runtime diagnostics, iOS 12 ARM64 build/inspection, safe hardware and network validation | Cloud/local engineering complete; hardware PENDING; see P002 evidence |
| P003 | Robust daemon state machine, lifecycle management, Unix IPC peer credential security, efficient deadline event loop, bounded release retries and diagnostics | Cloud/local engineering complete; hardware PENDING; see P003 validation evidence |
| P004 | --until, persisted one-time/daily/weekly schedules, daemon restart recovery | Implemented on the P004 branch; target assertion and network behavior remain hardware PENDING |
| P005 | Scheduled-wake feasibility, read-only capability diagnostics, tests, and deferred hardware procedure | Cloud engineering and exact-commit CI complete; hardware PENDING; scheduled wake UNVERIFIED |
| P006 | Server-mode foundation, health monitoring, safety policy, connectivity evidence, and deferred hardware validation plan | Engineering implemented; hardware PENDING; 24/7 NOT VALIDATED |
| P007 | Rootful `.deb` packaging, installation safety, artifact verification, rollback and regression testing | Cloud packaging implementation in progress on `feat/p007-rootful-packaging`; exact-commit CI and hardware gates pending |

P004/P005 hardware gate: iPad binary execution, IOKit create/release results, a bounded first timed hold, STOP/expiry/SIGTERM cleanup, controlled screen-lock observations, separate LAN and Tailscale measurements, and confirmed physical recovery. API acceptance alone cannot pass network or scheduled-wake gates. P005 does not run device experiments and does not add a wake alarm command.

P005 was integrated at verified SHA `77f3f15dda5c75f10e40b48fc0575d47fa38b80e`. P006 was merged at `dfe32d2b7edfd0677f282ce6e391c43706f19ac5`, the base for P007. P004–P006 hardware limitations remain pending; no prior milestone history is rewritten here. P007's artifact remains unsigned and device-unverified. See [P006 validation](P006-VALIDATION.md), [P007 validation](P007-VALIDATION.md), and [deferred P007 device gates](P007-DEVICE-TEST.md).
