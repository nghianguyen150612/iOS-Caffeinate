# Roadmap — ioscaffeinate

| Milestone | Deliverable | Status |
|---|---|---|
| P001 | Native C CLI/daemon, bounded hold, mock tests, unsigned iOS cross-build and disabled launchd template | Source ready; Linux mock PASS; iOS unverified |
| P002 | Signed device trial, probe, controlled screen-off LAN SSH/Tailscale comparison | PENDING |
| P003 | Robust lifecycle, health diagnostics, launchd integration | NOT STARTED |
| P004 | --until, scheduled and recurrent awake windows | NOT STARTED |
| P005 | Validate possible system/RTC scheduled wake, or mark unsupported | NOT STARTED |
| P006 | Server 24/7 mode, battery/thermal and remote connectivity validation | NOT STARTED |
| P007 | Rootful .deb packaging, rollback, regression testing | NOT STARTED |

P002 gate: real iOS ARM64 build, ldid signing, assertion acquisition/release verification, <=5m timed hold, LAN TCP/22 before/after display lock, Tailscale separately tested, safe stop and disconnect recovery.

No GUI, tweak injection, powerd modifications or automatic installation in P001.
