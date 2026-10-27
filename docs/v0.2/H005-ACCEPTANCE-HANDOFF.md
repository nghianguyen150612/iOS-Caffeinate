# H005 — H004 acceptance handoff

## Disposition

H005 is host-side preparation only. It does not certify H004 as `PASS`, establish P011 acceptance, or qualify v0.2.0-rc1. The current H004 state remains `INCOMPLETE / REVIEW_PENDING`; physical acceptance has not been performed. No official iOS-Caffeinate installation, daemon start, package transfer, assertion operation, reboot, or device control was performed by this work.

The H005 assertion inspector is not part of the package and must not be staged or transferred under H004 authorization. Physical deployment/execution needs a separate reviewed and authorized session. If available local read-only methods cannot directly establish driver and process assertion state/ownership during H004, record `UNKNOWN` and stop.

## Previously reported observations

The following are retained as **operator-reported preliminary observations**. They are not independently reviewed device evidence and have no raw output bundle attached to this repository.

| Reported item | Preserved value | Review boundary |
|---|---|---|
| Target | iPad mini 2 A1489 (`iPad4,4`), iOS 12.5.7, Amethyst/Procursus rootful | Must be confirmed directly during the attended session. |
| Boot time | `2026-10-25 20:41:49`, as displayed by the device | A boot-time display does not prove that all assertions are clear or that no assertion was recreated after boot. |
| Official iOS-Caffeinate installation | None detected | Must be confirmed from the live package database and paths. |
| Project state and log directories | Reported absent | Must be confirmed by read-only metadata checks; do not read unrelated logs. |
| Project process/socket/launchd observations | Previously absent | Must be repeated locally and captured with exact commands and exit results. |
| Driver assertion | `IOPMrootDomain`, type mask `0x100`, owner `en0`, ID `500`, level `255` | This is a reported positive driver assertion observation. It is not independently verified and must not be treated as absent or cleared. |
| Process-level assertion ownership | Not yet verified | This remains a stop condition until directly and completely observed. |
| Historical October 18 trial logs | Unavailable | Do not reconstruct or infer trial acceptance from memory. |
| Physical acceptance | Not performed | H004 and P011 remain pending. |

## Exact next physical session: attended H004 Phase 0

This is a checklist for the next separately authorized physical inspection. It authorizes read-only H004 observation only; it does not authorize transfer or execution of the H005 inspector, package installation, daemon startup, assertion changes, reboot, or P011 acceptance.

### Before any command

- [ ] An operator is physically beside the device and can observe it throughout the session.
- [ ] A second person is assigned to independently review the raw evidence and H004 disposition.
- [ ] The device is directly confirmed as A1489 / `iPad4,4`, iOS 12.5.7, Amethyst/Procursus rootful. Stop on mismatch or unknown bootstrap identity.
- [ ] Independent local physical recovery is present, understood, and available. It does not depend on SSH, Tailscale, a network route, or the project daemon. Record only the method and availability; do not record credentials or test a state-changing recovery action.
- [ ] Power, charge, temperature, and charging setup are safe by direct observation. Do not change battery or thermal controls. Stop if power is unsafe, temperature is abnormal, or safe handling is uncertain.
- [ ] The operator has separately approved the narrow, local, read-only H004 scope and stop rules. This is not P011 installation approval.
- [ ] A secure, access-restricted evidence destination outside the device, repository, CI, and shared artifacts is ready. Capture raw stdout and stderr separately, exit codes/signals, exact command text, executable path/hash, UTC/timebase/uncertainty, and hashes of preserved files.
- [ ] Start a unique non-identifying H004 session ID. Do not collect serial, UDID, Apple ID, passwords, tokens, process environments, unrelated application data, or raw logs.

### Read-only inspection order

1. Follow [H004 Phase 0 checklist](H004-PHASE0-CHECKLIST.md), [read-only command plan](H004-READONLY-COMMANDS.md), and [stop conditions](H004-STOP-CONDITIONS.md). Record device clocks and boot time separately from observer time; do not adjust clocks or reboot.
2. Reconfirm package state and project paths, process, socket, lock, launchd registration/plist, P014 journal and project-directory metadata. Do not execute project binaries unless the installed help and H004 checklist permit that read-only command after all earlier gates.
3. Run `LC_ALL=C dpkg --audit` once and preserve the complete raw output, stderr, and exit code. Follow [the H005 dpkg exception procedure](H005-DPKG-AUDIT-EXCEPTION.md) for every warning package and its status/file-list/database records. The expected 173-entry shape remains only a reported hypothesis until the independent reviewer accepts it.
4. Recheck driver and process assertion state using only an already installed, separately approved, read-only local method. Record type, owner, level/current status, query completeness, privilege failures, raw output references, and exit codes. Do not infer clearance from absent project processes/sockets/launchd entries or the reported boot time. Do not stage or transfer the H005 binary during this H004 session.
5. If any assertion is active, ownership is unknown, an API is unavailable, enumeration is incomplete, or sources conflict, stop and preserve the exact observation. Do not release, acquire, or modify assertions. No assertion result from this phase can certify ongoing safety.
6. If historical October 18 trial records cannot be located through the operator's reviewed private archive, record them `UNAVAILABLE`; do not recreate missing logs or count them as acceptance.
7. Complete the H004 result worksheet only with actual session observations. The independent reviewer compares raw records and provenance, records unresolved points, and assigns at most `OBSERVATIONS_RECORDED_REVIEW_PENDING`, `STOPPED`, `INCOMPLETE`, or `BLOCKED` as applicable. Do not write `PASS`, `DEVICE_VERIFIED`, or P011 acceptance.

### Stop conditions

Stop immediately if recovery or evidence handling is unavailable; power/temperature becomes unsafe; identity differs; package audit contains any unreviewed warning or inconsistent record; assertion state or ownership is positive/unknown/incomplete; process, path, socket, lock, or launchd observations conflict; the device changes state unexpectedly; or capture would expose unrelated personal data. Leave all device state as found. Do not repair packages, create/delete files, start services, alter launchd, export evidence, or reboot.

## Gate after H004

P011 remains blocked until the complete H004 observation set is independently reviewed, the dpkg exception is explicitly accepted or the audit is otherwise resolved through an authorized plan, current assertion status and ownership/cleanup are directly established, first-install history/recovery is reviewed, the exact approved package and host receipts are verified, safe backup and independent recovery are confirmed, and a separate attended P011 installation scope is authorized.

A later H005 inspector deployment is its own review point. Its host build and mocks do not resolve current device process-level ownership, establish target runtime API behavior, or authorize P011. P012/P013/P014/P016/P018/P019 physical evidence and signed-candidate-bound review remain outstanding. The R05A signed RC and release state are not changed by this handoff.
