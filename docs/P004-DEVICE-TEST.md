# P004 — Device Test & Hardware Verification Guidelines

This procedure is a P004 milestone snapshot. The target was unavailable then; later operator-reported execution and assertion results are in [P010 hardware findings](P010-HARDWARE-FINDINGS.md). P004 schedule/restart tests and scheduled wake remain unverified.

## Hardware Status

- **Device**: iPad mini 2 A1489 (Apple A7)
- **P004 status at that milestone**: **UNAVAILABLE / PENDING**

## Verification Scope for P004

Physical hardware tests for timed awake schedules and restart recovery were **PENDING** at P004 and remain unverified in P010.

### Planned Physical Tests

1. **Absolute Deadline (`start --until`)**:
   - Verify power assertion duration matches wall clock duration accurately.
2. **Recurring Schedule Wakes**:
   - Verify daily/weekly schedule triggers fire when display is locked while daemon process is running in foreground/background.
3. **Daemon Restart Recovery**:
   - Kill `ios-caffeinated` during active scheduled window, restart daemon, and verify it recovers remaining assertion duration.
4. **Scheduled Deep-Sleep Wake**:
   - **NOT CLAIMED / NOT IMPLEMENTED IN P004**. Whether a usable platform or hardware wake mechanism exists on the iOS 12 target is unknown; P005 records the source-level feasibility findings and leaves device validation pending.

## Recovery & Safety Instructions

- Always test with physical access to the device or SSH access over USB.
- In case of persistent assertion lock, kill `ios-caffeinated` or remove `/var/lib/ioscaffeinate/schedules.json` and reboot device.
