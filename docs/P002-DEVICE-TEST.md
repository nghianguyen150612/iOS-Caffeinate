# P002 safe iPad staging, testing and rollback

**All hardware steps below are PENDING and have not been executed.** Target: iPad mini 2 A1489, Apple A7 ARM64, iOS 12.5.7, Amethyst/Procursus rootful. No on-device clang, caffeinate or pmset is required. `/usr/bin/ldid` is expected; verify it exists.

## Preconditions and evidence

Use only the binaries from a successful exact-commit P002 Actions run, named `iOS-Caffeinate-ios12-arm64-UNSIGNED-HARDWARE-UNVERIFIED`. Download its inspection-evidence artifact too. Record commit SHA, Actions URL, both SHA256 hashes and SDK/platform/minimum/dependencies from `inspection.txt`. Inspect on macOS using `python3 scripts/inspect-ios.py` if building locally.

Confirm someone can physically unlock/recover the iPad and arrange a local/root shell in addition to SSH before any bounded assertion or display-lock test. Record recovery method, battery level and observable thermal condition. Stop if hot, low on battery or behavior is unexpected. If SSH is the only recovery path, skip screen-lock tests and leave network validation PENDING. Do not guess a device address or change SSH/Tailscale settings to obtain access.

No reboot, respring, SpringBoard changes, powerd/assertiond changes, jailbreak/bootstrap changes, tweak dependencies, Apple launchd changes, persistent power settings, service activation, indefinite assertion or final installer is permitted here.

## Isolated staging

Replace `IPAD_HOST` with the already authorized reachable iPad SSH destination. Use an existing SSH identity. The commands below are operator instructions, not a request to install anything persistently.

On the iPad, create a private unique directory under `/var/tmp` and record the resulting path:

```sh
umask 077
TESTDIR=$(mktemp -d /var/tmp/ios-caffeinate-p002.XXXXXX) || exit 1
printf '%s\n' "$TESTDIR"
```

On the build/transfer machine, assign that exact printed path (do not regenerate it remotely), then transfer only the two binaries:

```sh
TESTDIR=/var/tmp/ios-caffeinate-p002.REPLACE_WITH_ACTUAL_SUFFIX
scp dist/ios-caffeinate dist/ios-caffeinated "IPAD_HOST:$TESTDIR/"
```

Back on iPad, set `TESTDIR` to the recorded path in each shell. Keep all logs and binaries here; do not overwrite `/usr/local/bin` or use the production socket.

```sh
cd "$TESTDIR" || exit 1
chmod 0700 ios-caffeinate ios-caffeinated
ln -s ios-caffeinate ic
ls -ld "$TESTDIR"
ls -l ios-caffeinate ios-caffeinated ic
command -v file >/dev/null 2>&1 && file ios-caffeinate ios-caffeinated
command -v shasum >/dev/null 2>&1 && shasum -a 256 ios-caffeinate ios-caffeinated
command -v sha256sum >/dev/null 2>&1 && sha256sum ios-caffeinate ios-caffeinated
```

At least one hash tool must be available to compare with the unsigned artifact evidence before signing. If `file` or a hash tool is absent, document that limitation and use already available inspection tools or retrieve byte-for-byte copies for inspection on macOS. Do not install toolchains or modify bootstrap files for this test.

## Minimal signing and verification

Check `/usr/bin/ldid` is executable. Sign with no supplied entitlement plist (no unrestricted entitlements):

```sh
test -x /usr/bin/ldid || exit 1
/usr/bin/ldid -S "$TESTDIR/ios-caffeinate" > "$TESTDIR/ldid-cli.log" 2>&1
printf 'CLI ldid exit=%s\n' "$?"
/usr/bin/ldid -S "$TESTDIR/ios-caffeinated" > "$TESTDIR/ldid-daemon.log" 2>&1
printf 'daemon ldid exit=%s\n' "$?"
/usr/bin/ldid -e "$TESTDIR/ios-caffeinate" > "$TESTDIR/cli-entitlements.xml" 2> "$TESTDIR/cli-entitlements.err"
printf 'CLI entitlement inspection exit=%s\n' "$?"
/usr/bin/ldid -e "$TESTDIR/ios-caffeinated" > "$TESTDIR/daemon-entitlements.xml" 2> "$TESTDIR/daemon-entitlements.err"
printf 'daemon entitlement inspection exit=%s\n' "$?"
```

Require both signing exit codes to be zero; preserve stdout/stderr and inspect any emitted entitlements. Empty entitlement output is possible and does **not** prove signature integrity. Do not proceed after a signing error or respond by adding broad entitlements.

Retrieve the **signed** files into a separate directory on a macOS machine and validate the embedded signatures (signed hashes will differ from unsigned artifact hashes):

```sh
mkdir -p signed-device
scp "IPAD_HOST:$TESTDIR/ios-caffeinate" "IPAD_HOST:$TESTDIR/ios-caffeinated" signed-device/
codesign --display --verbose=4 signed-device/ios-caffeinate
codesign --verify --strict --verbose=4 signed-device/ios-caffeinate
codesign --display --verbose=4 signed-device/ios-caffeinated
codesign --verify --strict --verbose=4 signed-device/ios-caffeinated
shasum -a 256 signed-device/ios-caffeinate signed-device/ios-caffeinated
```

Record all exit codes and displayed signature details. If no signature verifier is available, mark signing **verification PENDING** even if ldid exits 0; successful execution is separate runtime evidence. Preserve dyld/signature errors; do not disable validation or patch system binaries. This source's unsigned-artifact inspection script intentionally rejects signed files, so do not run it as a signed verification replacement.

## Foreground backend probe

In the first iPad root shell, capture foreground output using terminal session logging or redirect it into the staging directory while keeping the daemon attached to that terminal:

```sh
"$TESTDIR/ios-caffeinated" --socket "$TESTDIR/runtime.sock" --foreground 2> "$TESTDIR/daemon.log"
printf 'daemon exit=%s\n' "$?"
```

In the second shell:

```sh
"$TESTDIR/ios-caffeinate" --socket "$TESTDIR/runtime.sock" probe
printf 'probe exit=%s\n' "$?"
"$TESTDIR/ic" --socket "$TESTDIR/runtime.sock" status
printf 'status exit=%s\n' "$?"
ls -ln "$TESTDIR/runtime.sock" "$TESTDIR/runtime.sock.lock"
```

Record raw output. Required probe evidence: `backend=IOKit_RUNTIME_UNVERIFIED`, `type=PreventUserIdleSystemSleep`, `load=ok`, `create_symbol=resolved`, `release_symbol=resolved`, `create_rc=0x00000000`, a nonzero `assertion_id`, and `release_rc=0x00000000`. STATUS should show `active=no`. Missing symbols or nonzero API return codes establish a backend limitation; stop further hold trials and retain evidence. Neither successful loading nor symbols alone validates power management.

If probe release fails, its ID remains tracked as active with `release_pending=yes`. Run STOP and inspect the foreground log; do not start another hold. A failed release is unresolved, not a successful stop or a safe basis for a lock trial.

## First bounded hold, explicit STOP, expiry and signals

Proceed only after successful probe create/release and confirmed physical recovery. Do not lock the display during the initial API/lifecycle checks. First hold is at most five minutes:

```sh
"$TESTDIR/ios-caffeinate" --socket "$TESTDIR/runtime.sock" start --for 5m
"$TESTDIR/ios-caffeinate" --socket "$TESTDIR/runtime.sock" status
"$TESTDIR/ios-caffeinate" --socket "$TESTDIR/runtime.sock" stop
"$TESTDIR/ios-caffeinate" --socket "$TESTDIR/runtime.sock" status
```

Record each exit code, ID, remaining duration, acquire code and successful release code. STATUS must become `active=no`. To test automatic expiry separately, start `--for 10s`, wait at least 11 seconds, inspect STATUS and the release log. To test SIGTERM separately, start another `--for 30s`, then send `kill -TERM DAEMON_PID` from the recovery shell to the **verified test daemon PID** (identify using available `ps` output and the exact staging path; never `killall`). Record the first terminal's daemon exit code, successful release log, and disappearance of `runtime.sock`. The sidecar `runtime.sock.lock` deliberately remains. An optional Ctrl-C trial checks SIGINT in the same way.

All test holds stay <=5m. A daemon may be suspended; userspace expiry cannot guarantee a five-minute kernel lease. If any release fails, record the unresolved result, keep the display unlocked and recovery available, and stop additional assertions. STOP may be retried on the tracked daemon. On exit the daemon retries once and returns nonzero if release still fails. Do not claim the assertion was released merely because the process exited; verify using available device evidence before declaring cleanup complete. No reboot or Apple-service intervention is authorized.

## Independent LAN and Tailscale comparison

Only perform this after confirming physical recovery and successful initial lifecycle checks. Restart the foreground test daemon if necessary. Use an independent LAN machine, preferably the Windows POS. Keep routes/SSH/Tailscale configuration unchanged. For each phase collect at least 10 TCP-22 probes per address, timestamp/latency/success, an actual authenticated SSH command such as `date -u` over each route, the display state, assertion status and elapsed time after lock. Use consistent intervals before comparing results.

| Condition | Display / hold | LAN address TCP-22 + SSH | Tailscale address TCP-22 + SSH / peer ping |
|---|---|---|---|
| Control A1 | On, no assertion | PENDING | PENDING |
| Control A2 | Locked, no assertion | PENDING | PENDING |
| Trial B1 | On, bounded assertion active | PENDING | PENDING |
| Trial B2 | Locked, same bounded assertion | PENDING | PENDING |
| Trial C | Locked, after successful STOP or expiry | PENDING | PENDING |

Example PowerShell TCP probe (replace each address explicitly; it changes no configuration):

```powershell
function Measure-Tcp22([string]$Address, [string]$Route, [string]$Phase) {
    $client = [Net.Sockets.TcpClient]::new()
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $ok = $false
    try {
        $task = $client.ConnectAsync($Address, 22)
        if ($task.Wait(3000)) { $ok = $client.Connected }
    } catch { $ok = $false }
    finally { $timer.Stop(); $client.Dispose() }
    [pscustomobject]@{
        UTC = [DateTime]::UtcNow.ToString('o'); Phase = $Phase; Route = $Route
        Address = $Address; Success = $ok; ElapsedMs = $timer.ElapsedMilliseconds
    }
}
# Assign $LanAddress and $TailAddress to the iPad's known addresses first.
1..10 | ForEach-Object {
    Measure-Tcp22 $LanAddress 'LAN' 'A2'
    Measure-Tcp22 $TailAddress 'Tailscale' 'A2'
    Start-Sleep -Seconds 2
} | Export-Csv -NoTypeInformation -Path './p002-A2.csv'
```

Change the phase label/output filename for A1/B1/B2/C. If the POS has Tailscale, also record `tailscale ping` to the known peer and its direct/relay result, separately from TCP reachability. A TCP handshake is not a complete SSH measurement, LAN success is not Tailscale success, and API acceptance is not Wi-Fi evidence. If the hold expires before B2 completes, label those observations after-expiry and repeat only with recovery and another <=5m hold. If either route becomes unavailable, use physical recovery, stop the test assertion, preserve timestamps/errors and do not restart network services.

## Rollback and evidence retention

1. From a recovery shell, STOP the tracked hold and require release success / `active=no`.
2. Send SIGTERM only to the verified foreground test daemon. Require clean exit, successful release logs and no `runtime.sock`. If release failed, retain an unresolved record; do not relabel it PASS after process exit.
3. Copy logs, unsigned/signed hashes, signature checks, runtime replies, return codes, PID, battery/thermal observations and independent CSV/SSH results to the evidence machine.
4. After the test daemon has exited and evidence is saved, remove only the two staged test executables, `ic` symlink and `runtime.sock.lock` in the exact private test directory. Remove remaining test logs only after saving them, then `rmdir` the exact directory. Never unlink a live lock or delete production paths.

No persistent service was installed, so no launchd operation or system configuration rollback is needed. Record each evidence level separately in `P002-VALIDATION.md`. P003 remains unauthorized.
