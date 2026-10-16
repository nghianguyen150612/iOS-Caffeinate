# P004 — Device Test & Hardware Verification Guidelines

## Hardware Status

- **Device**: iPad mini 2 A1489 (Apple A7)
- **Status**: **UNAVAILABLE / PENDING**

## Verification Scope for P004

Physical hardware tests for timed awake schedules and restart recovery remain **PENDING** until the iPad mini 2 becomes available.

### Planned Physical Tests

1. **Absolute Deadline (`start --until`)**:
   - Verify power assertion duration matches wall clock duration accurately.
2. **Recurring Schedule Wakes**:
   - Verify daily/weekly schedule triggers fire when display is locked while daemon process is running in foreground/background.
3. **Daemon Restart Recovery**:
   - Kill `ios-caffeinated` during active scheduled window, restart daemon, and verify it recovers remaining assertion duration.
4. **Scheduled Deep-Sleep Wake**:
   - **NOT CLAIMED / NOT IMPLEMENTED IN P004**. Scheduled wake from system deep sleep requires RTC hardware timer setup, which is out of scope for P004 and deferred to P005-P007.

## Recovery & Safety Instructions

- Always test with physical access to the device or SSH access over USB.
- In case of persistent assertion lock, kill `ios-caffeinated` or remove `/var/lib/ioscaffeinate/schedules.json` and reboot device.
