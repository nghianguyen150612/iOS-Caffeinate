# P019 Incident Response

When a mandatory stop condition occurs, stop testing, preserve records, and keep the operator present. The tool does not attempt repair or recovery.

## Record

- Session, phase, trial/cycle, protocol version, source/build/package identity.
- UTC time, observer and device timebase IDs, clock uncertainty, monotonic elapsed values when available.
- Actual state and last known assertion ownership, daemon/process, socket, P014 journal, package, screen, route, battery/thermal availability.
- Exact failure category, operator action already taken, and whether the independent physical recovery path remains available.
- Original terminal output and P009/P012/P019 references with hashes. Keep sensitive raw material private and do not copy it into CI.
- Whether testing stopped, which trials are incomplete, and any deviation from protocol.

Do not overwrite incomplete records or use a later successful cleanup to conceal an earlier failure. Do not automatically restart, reboot/respring, send SIGKILL, delete sockets, reset recovery state, install/remove/rollback, mutate launchd, or acquire a new assertion. Recovery is a separate manual action requiring its own authorization.

Classify release failure, unknown ownership, journal corruption, unexpected restart/exit, unexplained reboot/respring, unexpected scheduled assertion, host-key failure, loss of recovery, resource concern, attendance loss, package mismatch, state inconsistency, persistent corruption, lost required observation, and duration overrun as safety incidents. Preserve the exact outcome; do not label an unsupported launchd feature failure as a failure of an enabled feature.
