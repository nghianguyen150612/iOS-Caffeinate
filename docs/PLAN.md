# Roadmap — iOS-Caffeinate

| Milestone | Deliverable | Status |
|---|---|---|
| P001 | Native C CLI/daemon, bounded hold, mock tests, unsigned iOS cross-build and disabled launchd template | Baseline `069ad94eb344da08d414c9478b6e212146c8fc28` verified |
| P002 | Source audit, canonical names, runtime diagnostics, iOS 12 ARM64 build/inspection, safe hardware and network validation | Cloud/local engineering complete; hardware PENDING; see P002 evidence |
| P003 | Robust daemon state machine, lifecycle management, Unix IPC peer credential security, efficient deadline event loop, bounded release retries and diagnostics | Cloud/local engineering complete; hardware PENDING; see P003 validation evidence |
| P004 | --until, persisted one-time/daily/weekly schedules, daemon restart recovery | Implemented on the P004 branch; target assertion and network behavior remain hardware PENDING |
| P005 | Scheduled-wake feasibility, read-only capability diagnostics, tests, and deferred hardware procedure | Cloud engineering complete; final-commit CI and hardware remain PENDING; scheduled wake UNVERIFIED |
| P006 | Server 24/7 mode, battery/thermal and remote connectivity validation | NOT AUTHORIZED; readiness assessment only |
| P007 | Rootful .deb packaging, rollback, regression testing | NOT STARTED |

P004/P005 hardware gate: iPad binary execution, IOKit create/release results, a bounded first timed hold, STOP/expiry/SIGTERM cleanup, controlled screen-lock observations, separate LAN and Tailscale measurements, and confirmed physical recovery. API acceptance alone cannot pass network or scheduled-wake gates. P005 does not run device experiments and does not add a wake alarm command.

P005 is based on verified P004 SHA `0b10c4a277e5a05327dd584fb21252e9b8d5ed4a`. The P004-to-main integration debt is recorded in [P005 validation](P005-VALIDATION.md); no prior history is rewritten here.
