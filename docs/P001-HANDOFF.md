# P001 Handoff (2026-10-16)

Target: iPad mini 2 (A1489 / Apple A7, ARM64), iOS 12.5.7, Amethyst rootful, Procursus. Existing Go runtime works; ioscaffeinate is intentionally native C.

Symptoms: Wi-Fi / SSH / Tailscale connection becomes slow or unreachable when the screen locks. Root cause not fully isolated. Avoid claiming that a power assertion fixes it until tested.

Delivered:
- ioscaffeinate CLI
- ioscaffeinated daemon
- Runtime-resolved Apple power assertion backend
- Local root-only IPC with bounded timer and cleanup
- Explicit Linux mock tests
- macOS iOS12 ARM64 cross-build script and Actions workflow
- Disabled launchd template

Verified: Linux mock tests.
Not verified: iOS cross-build, iOS API availability, LAN/Tailscale reachability with screen locked, battery/thermal effects.
No device changes have been made.

Next: P002 must run real iOS binaries in the foreground, after signing with ldid on iPad, using no permanent assertion. Compare TCP/22 through LAN via POS before and after lock, then test Tailscale separately. Do not alter existing jailbreak, launchd or network services without recovery.
