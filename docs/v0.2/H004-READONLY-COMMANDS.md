# H004 — Read-only Command Plan

This plan is for a separately authorized, physically attended Phase 0 inspection only. It has not been run on the iPad. Commands run locally at the device; do not connect over SSH/Tailscale, transfer files, redirect output to the device, or invoke a command that changes package, service, launchd, assertion, recovery, schedule, policy, power, or evidence state.

Use the local shell and installed system utilities that are already present. Capture output on the secure separate destination; do not redirect or `tee` output to the iPad, create on-device evidence files, or persist device shell history. Capture the exact command, UTC observation time, exit code, and unedited stdout/stderr in the private session record. Never include credentials in commands. An `UNAVAILABLE` or `UNKNOWN` result stays explicit.

For the previously reported assertion and package-audit context, use the [H005 acceptance handoff](H005-ACCEPTANCE-HANDOFF.md), [power inspector compatibility note](H005-POWER-ASSERTION-INSPECTOR.md), and [dpkg exception procedure](H005-DPKG-AUDIT-EXCEPTION.md). H004 does not authorize staging or transferring the standalone inspector; if currently available local read-only methods cannot establish complete assertion state and ownership, record `UNKNOWN` and stop.

## 0. Session context and timebase

Before the first device command, record session ID, operator attendance, power/charging observation, independent recovery method, host clock source, UTC, timebase ID, and uncertainty. Do not adjust clocks. At the device, run:

```sh
date -u '+%Y-%m-%dT%H:%M:%SZ'
date '+%s'
sysctl -n kern.boottime
id -u
```

These record the device wall clock, epoch reading, boot-time identity when exposed, and effective UID. A missing boot-time interface means the device monotonic timebase is `UNKNOWN`; do not substitute the host's clock. Record the result of each command separately. Do not assume root privileges or use `sudo` to change context.

## 1. Device and bootstrap identity

```sh
sysctl -n hw.machine
sw_vers -productVersion
uname -a
dpkg --print-architecture
```

These establish model identifier, iOS version, kernel/platform string, and Debian architecture when available. Expected target is `iPad4,4`, iOS `12.5.7`, and rootful `iphoneos-arm`. If a required command is absent, record `UNAVAILABLE`. If identity differs, stop.

Inspect only bootstrap/package database path metadata:

```sh
for p in /var/jb /opt/procursus /var/lib/dpkg /var/lib/dpkg/status /usr/bin/dpkg; do
  if [ -L "$p" ] || [ -e "$p" ]; then ls -ld "$p" || exit $?; else printf 'ABSENT %s\n' "$p"; fi
done
```

`/var/jb` presence is a rootless-layout indicator requiring review; do not alter it. This inventory and the architecture query inform the bootstrap classification but do not by themselves prove jailbreak provenance.

Expected bootstrap identity is Amethyst/Procursus rootful. Record that identity only when the local package metadata or another direct device observation establishes it. If bootstrap provenance cannot be established, record `UNKNOWN`; architecture or filesystem layout alone is not proof and the unknown blocks later P011 actions.

## 2. Installed package database

```sh
dpkg-query -W -f='${Status}|${Version}|${Architecture}\n' com.ioscaffeinate.cli
dpkg --audit
```

These report the package database record and incomplete-package audit. Preserve the command exit status even when “not installed” is reported. A partial, contradictory, or unreadable database is a blocker. Do not run `dpkg -i`, `dpkg --configure`, `dpkg --remove`, `apt`, or any repair command.

For the reported virtual-package warning, capture the complete audit output, stderr, and exit code. Follow the bounded [H005 dpkg review](H005-DPKG-AUDIT-EXCEPTION.md) for every warning package and its associated database records. Empty output or `install ok installed` status alone does not clear the audit gate.

## 3. Project executable paths, metadata, and hashes

Inspect paths before executing any project binary:

```sh
for p in /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated /usr/local/bin/ic /usr/local/libexec/ioscaffeinate-manager; do
  if [ -L "$p" ] || [ -e "$p" ]; then ls -ld "$p" || exit $?; else printf 'ABSENT %s\n' "$p"; fi
done
```

If `/usr/local/bin/ic` is a symlink, record its target with `readlink /usr/local/bin/ic`; do not follow an unexpected target. For each present regular executable, record owner, mode, size, and link count with the already available BSD `stat`:

```sh
for p in /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated /usr/local/libexec/ioscaffeinate-manager; do
  if [ -f "$p" ] && [ ! -L "$p" ]; then stat -f '%N|%HT|%u:%g|%Sp|%z|%l' "$p" || exit $?; fi
done
```

Then query ownership for each present project file:

```sh
for p in /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated /usr/local/bin/ic /usr/local/libexec/ioscaffeinate-manager; do
  if [ -L "$p" ] || [ -e "$p" ]; then dpkg-query -S "$p" || exit $?; fi
done
```

Do not query absent paths. A file with no owner, multiple/unexpected owners, or an owner that conflicts with the package database is a blocker. These commands do not prove the binary's source or authenticity.

Check availability with `command -v` and choose exactly one SHA-256 utility before hashing. Do not switch tools if the selected command errors. Use `shasum` if available:

```sh
for p in /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated /usr/local/libexec/ioscaffeinate-manager; do
  if [ -f "$p" ] && [ ! -L "$p" ]; then shasum -a 256 "$p" || exit $?; fi
done
```

If `shasum` is absent, use `sha256sum` if available:

```sh
for p in /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated /usr/local/libexec/ioscaffeinate-manager; do
  if [ -f "$p" ] && [ ! -L "$p" ]; then sha256sum "$p" || exit $?; fi
done
```

Only if both prior utilities are absent, use `openssl` if available:

```sh
for p in /usr/local/bin/ios-caffeinate /usr/local/bin/ios-caffeinated /usr/local/libexec/ioscaffeinate-manager; do
  if [ -f "$p" ] && [ ! -L "$p" ]; then openssl dgst -sha256 "$p" || exit $?; fi
done
```

Run only the selected command and record which utility was used.

Hash only paths that exist as regular files. If a binary or hashing utility is missing, record that field as `UNAVAILABLE`. If a selected utility is denied or fails unexpectedly, record the exact error and stop. Compare any later artifact only against its 64-hex-digit authoritative receipt; never infer an installed build from the H003 host result.

## 4. Process, socket, lock, and launchd state

Run the process listing without arguments that could contain credentials:

```sh
ps -axo pid,ppid,uid,stat,comm
```

Record relevant daemon rows and ownership. Do not kill, signal, or attach to any process. Check socket and lock type/ownership without opening or deleting either path:

```sh
for p in /var/run/ioscaffeinated.sock /var/run/ioscaffeinated.sock.lock; do
  if [ -L "$p" ] || [ -e "$p" ]; then ls -ld "$p" || exit $?; else printf 'ABSENT %s\n' "$p"; fi
done
```

Inspect the staged and live plist paths and registration:

```sh
for p in /usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist /Library/LaunchDaemons/com.ioscaffeinate.daemon.plist; do
  if [ -L "$p" ] || [ -e "$p" ]; then ls -ld "$p" || exit $?; else printf 'ABSENT %s\n' "$p"; fi
done
launchctl list
```

If a plist is present and readable, record its metadata and run `plutil -lint` on that exact path only as a read-only syntax check. The default socket contract is a root-owned Unix socket with mode `0600`; the lock path contract is a root-owned regular file with mode `0600` and one link. A lock-file path can remain after its lock is released, and `ls`/`stat` do not reveal active `flock` ownership. Do not open or attempt to acquire the lock; report active lock state as `UNKNOWN` unless an installed read-only diagnostic explicitly establishes it. `launchctl list` is the only launchctl command in this plan. Do not use `load`, `unload`, `bootstrap`, `bootout`, `enable`, `disable`, `kickstart`, or `print`. Compare the exact label `com.ioscaffeinate.daemon`; preserve unrelated launchd output privately and redact it in derivatives.

For each present regular, non-symlink plist, record its SHA-256 with the single utility selected in section 3. If the selected utility fails, record the exact error and stop; do not switch utilities.

Before continuing, compare process, socket, lock, assertion, and launchd observations. A mismatch, unexpected owner, assertion state/ownership that remains `UNKNOWN`, loaded service with no explainable registration, or other ambiguous service state is an immediate stop. Do not invoke project status commands to work around a stop condition. Unknown assertion state blocks all progression beyond Phase 0.

The reported driver assertion (`0x100`, owner `en0`, ID `500`, level `255`) is not independently verified and remains a potential active assertion. Preserve it as positive operator-reported context. Do not infer that a reboot cleared it or that an absent project process/socket/launchd registration proves assertion clearance.

## 5. P014 recovery journal metadata

Inspect metadata only for `/var/lib/ioscaffeinate/recovery-state.json` using `ls -ld` and BSD `stat` as above. The P014 contract expects a root-owned regular single-link file, mode `0600`, bounded to 4 KiB; do not open it to check contents:

```sh
stat -f '%N|%HT|%u:%g|%Sp|%z|%l' /var/lib/ioscaffeinate/recovery-state.json
```

Run `stat` only if the file is present and not a symlink. Do not `cat`, edit, replace, chmod, chown, delete, or reset the journal. Missing journal metadata is recorded exactly; do not assume it proves a safe first run. If the journal owner or mode is unexpected, stop. After CLI discovery, a read-only recovery status query is allowed only if the journal exists and no earlier stop condition applies. Missing, corrupt, unsafe, unsupported, unreadable, unknown, or unvalidated recovery state is a stop condition and blocks progression beyond Phase 0. `service recovery reset` is never part of Phase 0.

Before invoking project commands, capture the initial metadata snapshot for persistent configuration, evidence, and logs. Existing schedule and Server Mode files are expected to be root-owned, regular, single-link files with mode `0600`; compare metadata only and stop on a mismatch:

```sh
for p in /var/lib/ioscaffeinate/schedules.json /var/lib/ioscaffeinate/server-mode.json /var/lib/ioscaffeinate/evidence /var/log/ioscaffeinate /var/log/ioscaffeinate/daemon.log /var/log/ioscaffeinate/daemon.err; do
  if [ -L "$p" ] || [ -e "$p" ]; then ls -ld "$p" || exit $?; else printf 'ABSENT %s\n' "$p"; fi
done
```

## 6. Read-only project CLI discovery and ownership

Only proceed if the executable path was inspected, its hash was recorded when possible, and earlier service/recovery observations did not trigger a stop. First discover supported syntax:

```sh
/usr/local/bin/ios-caffeinate --help
```

If the help output documents `--version`, run it separately; otherwise record `UNAVAILABLE` without invoking it:

```sh
/usr/local/bin/ios-caffeinate --version
```

If the main help advertises topic help, inspect only relevant command syntax:

```sh
/usr/local/bin/ios-caffeinate help service
/usr/local/bin/ios-caffeinate help server
/usr/local/bin/ios-caffeinate help schedule
/usr/local/bin/ios-caffeinate help health
/usr/local/bin/ios-caffeinate help package
/usr/local/bin/ios-caffeinate help evidence
```

Use only commands explicitly listed by that installed CLI as read-only. The following P018/P014 status commands may be used when supported:

```sh
/usr/local/bin/ios-caffeinate service recovery status
/usr/local/bin/ios-caffeinate status
/usr/local/bin/ios-caffeinate doctor
/usr/local/bin/ios-caffeinate wake status
/usr/local/bin/ios-caffeinate service status
/usr/local/bin/ios-caffeinate service doctor
/usr/local/bin/ios-caffeinate service recovery plan
```

Run `service recovery status` first. These may report daemon availability and assertion ownership without starting a daemon. If ownership is not safely observable, record it `UNKNOWN`; do not infer no assertion from a missing PID, socket, or IPC response. An active or ambiguous assertion ends the inspection after preserving observations.

## 7. P015 Server Mode policy

If help confirms each operation is read-only and supported, query the existing policy:

```sh
/usr/local/bin/ios-caffeinate server policy show
/usr/local/bin/ios-caffeinate server policy validate
/usr/local/bin/ios-caffeinate server policy explain
/usr/local/bin/ios-caffeinate server policy plan
```

Record the policy version, configuration presence/validity, and execution authorization exactly as reported. Do not migrate or apply policy, start a trial, or treat eligibility as execution permission. Unsupported operations are `UNAVAILABLE`.

## 8. P017 schedule diagnostics

If help confirms support, use only read-only schedule inspection:

```sh
/usr/local/bin/ios-caffeinate schedule list
/usr/local/bin/ios-caffeinate schedule validate
/usr/local/bin/ios-caffeinate schedule next
/usr/local/bin/ios-caffeinate schedule conflicts
/usr/local/bin/ios-caffeinate schedule doctor
```

Record storage validity, schedule count/IDs as private references, next-time/timezone data, P014/P015 blockers, and runtime availability. Do not change schedules, test an occurrence, or infer that a preview will execute or wake the iPad. If a schedule appears to have acquired an assertion unexpectedly, stop.

## 9. P016 health availability

If supported as read-only by the installed CLI, query once:

```sh
/usr/local/bin/ios-caffeinate health sources
/usr/local/bin/ios-caffeinate health status
/usr/local/bin/ios-caffeinate health battery
/usr/local/bin/ios-caffeinate health thermal
/usr/local/bin/ios-caffeinate health doctor
```

Record source, timestamp/freshness, and availability. `UNAVAILABLE` is not zero, full charge, nominal temperature, or proof of safety. Do not alter charging or thermal controls, induce load, or repeat sampling. Stop if direct observation or a supported reading indicates an unsafe condition.

## 10. Logs, evidence inventory, and resource constraints

Repeat the initial project-state metadata snapshot and compare it with the earlier output. Inspect only project directory and file metadata; do not print raw log contents:

```sh
for p in /var/lib/ioscaffeinate /var/lib/ioscaffeinate/schedules.json /var/lib/ioscaffeinate/server-mode.json /var/lib/ioscaffeinate/recovery-state.json /var/lib/ioscaffeinate/evidence /var/log/ioscaffeinate /var/log/ioscaffeinate/daemon.log /var/log/ioscaffeinate/daemon.err; do
  if [ -L "$p" ] || [ -e "$p" ]; then ls -ld "$p" || exit $?; else printf 'ABSENT %s\n' "$p"; fi
done
```

If the installed CLI supports them, run the P018 read-only inventory commands:

```sh
/usr/local/bin/ios-caffeinate evidence status
/usr/local/bin/ios-caffeinate evidence inventory
/usr/local/bin/ios-caffeinate evidence validate
/usr/local/libexec/ioscaffeinate-manager verify
```

The manager command is optional and only runs if that exact executable exists and the P011 contract identifies `verify` as read-only. Do not run any export command in Phase 0. Preserve raw inventory privately; record sanitized output references only.

Read resource and storage snapshots:

```sh
df -Pk / /var
uptime
sysctl hw.memsize
vm_stat
```

`df` establishes filesystem availability. The remaining utilities are optional snapshots; record unsupported commands as `UNAVAILABLE`. Do not use a memory or storage snapshot to claim resource safety beyond the observation.

## 11. End of inspection

Compare before/after service, socket, lock, recovery, schedule, policy, and evidence metadata when safely available. If state changed unexpectedly during inspection, stop and preserve the exact observations. Do not take corrective action. Complete [H004 result template](H004-RESULT-TEMPLATE.md), then follow [H004 evidence guide](H004-EVIDENCE-GUIDE.md).
