# ioscaffeinate (P001 prototype)

CLI and daemon for rootful jailbroken iOS 12.5.7 (Amethyst/Procursus), initially targeting iPad mini 2 (arm64).

Executables: **ioscaffeinate** (CLI), **ioscaffeinated** (daemon).

## Implemented

- Local root-only Unix socket: /var/run/ioscaffeinated.sock
- Commands: probe, start --for DURATION, status, stop
- Bounded duration: 1 second through 24 hours, automatic expiry
- Runtime IOKit assertion symbol lookup
- Linux mock tests; CI iOS ARM64 unsigned cross-build
- Disabled launchd template (not installed or activated)

## Run (manual, root)

First launch ioscaffeinated --foreground. In a second root shell run:

    ioscaffeinate probe
    ioscaffeinate start --for 5m
    ioscaffeinate status
    ioscaffeinate stop

## Tests

Linux mock backend (does NOT affect power):

    ./scripts/build-linux-test.sh
    python3 tests/integration.py

macOS with Xcode/iPhoneOS SDK:

    ./scripts/build-macos.sh

Outputs are unsigned. Copy to iPad ONLY after arranging LAN or physical recovery. Sign with ldid on iPad, test the daemon manually in the foreground and use a <=5 minute hold for first validation. Do not enable launchd before proving assertion effects, safe stop and screen-off LAN SSH. API acceptance alone does NOT prove Wi-Fi or Tailscale availability.

## Unverified / out of scope

Actual iOS 12 assertion support, screen-off network availability, and long-term thermal safety are UNVERIFIED. No GUI, tweak injection, Apple daemon modifications, reboot or remote device deployment.

Permanent server mode, recurrent schedules, --until, timed deep-sleep wake and signed .deb packaging are NOT implemented. True scheduled wake needs hardware/OS evidence; launchd calendar jobs alone are insufficient.

See docs/PLAN.md, docs/ARCHITECTURE.md and docs/P001-HANDOFF.md.
