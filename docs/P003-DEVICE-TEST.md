# P003 — Hardware Validation & Rollback Checklist

**Target:** iPad mini 2 A1489 (Apple A7 ARM64, iOS 12.5.7, Amethyst/Procursus rootful)
**Status:** PENDING (Deferred until physical device access is restored)

---

## Prerequisite Checks
1. Establish USB / Wi-Fi SSH connection to the iPad as root.
2. Ensure physical access to power/home button is available for manual recovery if needed.
3. Verify existing system state before installing P003 binaries.

## Step 1: Binary Transfer & Code Signing
```bash
scp dist/ios-caffeinate dist/ios-caffeinated root@<ipad-ip>:/usr/local/bin/
ssh root@<ipad-ip> "chmod 0755 /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated && \
                    ln -sfn ios-caffeinate /usr/local/bin/ic && \
                    ldid -S /usr/local/bin/ios-caffeinate && \
                    ldid -S /usr/local/bin/ios-caffeinated"
```

## Step 2: On-Device Daemon Manual Launch
Start daemon in foreground in Session A:
```bash
/usr/local/bin/ios-caffeinated --foreground
```
Verify stdout/stderr logs contain ISO-8601 timestamps and backend `IOKit_RUNTIME_UNVERIFIED`.

## Step 3: Probe & Assertion Verification (Session B)
```bash
ic probe
```
Confirm output:
- `OK probe=acquire_release`
- Valid `assertion_id` returned from kernel IOKit.
- Return code 0.

## Step 4: Bounded Power Hold Test (5 minutes)
```bash
ic start --for 5m
ic status
```
Verify:
- `state=ACTIVE`, `active=yes`, `remaining_seconds=300`.
- Display lock device manually.
- Monitor LAN ping and SSH connectivity over 5 minutes.
- Confirm assertion automatically expires and status returns to `state=IDLE`, `active=no`.

## Step 5: Failure & Signal Recovery Test
1. Start hold: `ic start --for 5m`
2. Stop hold: `ic stop`
3. Verify release status: `active=no release_rc=0x00000000`.
4. Send SIGTERM to daemon process and verify socket `/var/run/ioscaffeinated.sock` and lock file are cleaned up safely.

## Rollback Procedure
If any issue occurs or system sleep fails to restore:
1. Kill daemon process: `pkill -9 ios-caffeinated`.
2. Remove socket and lock files: `rm -f /var/run/ioscaffeinated.sock*`.
3. Remove binaries: `rm -f /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated /usr/local/bin/ic`.
4. Reboot iPad if power assertion remains held by system: `reboot`.
