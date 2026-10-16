# Roadmap — iOS-Caffeinate

| Milestone | Deliverable | Status |
|---|---|---|
| P001 | Native C CLI/daemon, bounded hold, mock tests, unsigned iOS cross-build and disabled launchd template | Baseline `069ad94eb344da08d414c9478b6e212146c8fc28` verified |
| P002 | Source audit, canonical names, runtime diagnostics, iOS 12 ARM64 build/inspection, safe hardware and network validation | Engineering in progress; hardware PENDING; see P002 evidence |
| P003 | Further lifecycle/health work and launchd integration | NOT AUTHORIZED |
| P004 | --until, scheduled and recurrent awake windows | NOT STARTED |
| P005 | Validate possible system/RTC scheduled wake, or mark unsupported | NOT STARTED |
| P006 | Server 24/7 mode, battery/thermal and remote connectivity validation | NOT STARTED |
| P007 | Rootful .deb packaging, rollback, regression testing | NOT STARTED |

Full P002 hardware gate: iPad binary execution, verified ldid signing, IOKit create/release results, <=5m first timed hold, STOP/expiry/SIGTERM cleanup, controlled display-lock LAN TCP/22 comparison and independent Tailscale measurements, with confirmed physical recovery. API acceptance alone cannot pass network gates.

P002 includes fixes demonstrated by the P001 audit, not permanent service integration or a final installer. Do not load the disabled launchd template. P003 readiness is an assessment only; no P003 work is authorized.
